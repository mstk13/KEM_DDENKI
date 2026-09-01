"""ローカル推論（ADR-0010 層B）のテスト。

- local_llm クライアントの契約（Schema必須・失敗時 None・例外を投げない）
- llm_advisor のディスパッチとフォールバック
- AILog が「要求した実行先」ではなく「実際の実行先」を記録すること
- matching 戦略5 のローカル優先と候補数ガード

Ollama への実通信は行わない。urlopen をモックして応答を固定する。
"""

import json
import urllib.error
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from apps.ai.models import AILog
from apps.ai.services import llm_advisor, local_llm
from apps.estimation.models import EstimationItem
from apps.estimation.services import matching


def _ollama_response(payload: dict, *, model: str = "qwen3:8b",
                     prompt_eval_count: int = 120, eval_count: int = 30):
    """Ollama /api/chat の応答を模した file-like オブジェクトを返す。"""
    body = json.dumps({
        "model": model,
        "message": {"role": "assistant",
                    "content": json.dumps(payload, ensure_ascii=False)},
        "prompt_eval_count": prompt_eval_count,
        "eval_count": eval_count,
    }).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *args: False
    return resp


def _raw_ollama_response(text: str):
    """content が JSON として壊れている応答。"""
    body = json.dumps({
        "model": "qwen3:8b",
        "message": {"role": "assistant", "content": text},
        "prompt_eval_count": 1,
        "eval_count": 1,
    }).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *args: False
    return resp


SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
}


# ---------------------------------------------------------------------------
# local_llm クライアント
# ---------------------------------------------------------------------------


class TestLocalLlmClient:
    def test_schema_is_required(self, settings):
        settings.OLLAMA_CHAT_ENABLED = True
        with pytest.raises(ValueError):
            local_llm.chat_json("なにか", {})

    def test_disabled_by_default(self, settings):
        """既定は無効。精度を実測してから有効化する運用にしている。"""
        settings.OLLAMA_CHAT_ENABLED = False
        assert local_llm.is_configured() is False
        assert local_llm.chat_json("なにか", SCHEMA) is None

    def test_returns_parsed_payload(self, settings):
        settings.OLLAMA_CHAT_ENABLED = True
        with patch("urllib.request.urlopen",
                   return_value=_ollama_response({"ok": True})):
            result = local_llm.chat_json("なにか", SCHEMA)

        assert result["parsed"] == {"ok": True}
        assert result["input_tokens"] == 120
        assert result["output_tokens"] == 30
        assert result["model_id"] == "qwen3:8b"

    def test_unreachable_returns_none_without_raising(self, settings):
        settings.OLLAMA_CHAT_ENABLED = True
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("connection refused")):
            assert local_llm.chat_json("なにか", SCHEMA) is None

    def test_timeout_returns_none(self, settings):
        settings.OLLAMA_CHAT_ENABLED = True
        with patch("urllib.request.urlopen", side_effect=TimeoutError()):
            assert local_llm.chat_json("なにか", SCHEMA) is None

    def test_broken_json_returns_none(self, settings):
        """壊れた出力を握り潰して空の結果にしない（labor_pdf の教訓）。"""
        settings.OLLAMA_CHAT_ENABLED = True
        with patch("urllib.request.urlopen",
                   return_value=_raw_ollama_response('{"ok": tr')):
            assert local_llm.chat_json("なにか", SCHEMA) is None

    def test_empty_content_returns_none(self, settings):
        settings.OLLAMA_CHAT_ENABLED = True
        with patch("urllib.request.urlopen",
                   return_value=_raw_ollama_response("")):
            assert local_llm.chat_json("なにか", SCHEMA) is None

    def test_request_carries_schema_and_keep_alive(self, settings):
        """format には Schema オブジェクトを渡す。文字列 "json" では守られない。"""
        settings.OLLAMA_CHAT_ENABLED = True
        captured = {}

        def _capture(req, timeout=None):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["url"] = req.full_url
            return _ollama_response({"ok": True})

        with patch("urllib.request.urlopen", side_effect=_capture):
            local_llm.chat_json("なにか", SCHEMA, keep_alive="10m")

        assert captured["url"].endswith("/api/chat")
        assert captured["body"]["format"] == SCHEMA
        assert captured["body"]["keep_alive"] == "10m"
        assert captured["body"]["think"] is False
        assert captured["body"]["options"]["temperature"] == 0

    def test_keep_alive_defaults_to_setting(self, settings):
        """ホストの OLLAMA_KEEP_ALIVE=0 を打ち消すため、必ず明示する。"""
        settings.OLLAMA_CHAT_ENABLED = True
        settings.OLLAMA_KEEP_ALIVE = "5m"
        captured = {}

        def _capture(req, timeout=None):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _ollama_response({"ok": True})

        with patch("urllib.request.urlopen", side_effect=_capture):
            local_llm.chat_json("なにか", SCHEMA)

        assert captured["body"]["keep_alive"] == "5m"


# ---------------------------------------------------------------------------
# llm_advisor のディスパッチ
# ---------------------------------------------------------------------------


class TestDispatchEligibility:
    def test_multimodal_content_is_not_eligible(self):
        """qwen3:8b は vision を持たない。画像ブロックはローカルに振らない。"""
        content = [{"type": "image", "source": {"data": "..."}}]
        assert llm_advisor._local_is_eligible(SCHEMA, content) is False

    def test_missing_schema_is_not_eligible(self):
        assert llm_advisor._local_is_eligible(None, "text") is False

    def test_plain_string_content_is_eligible(self, settings):
        settings.OLLAMA_CHAT_ENABLED = True
        assert llm_advisor._local_is_eligible(SCHEMA, "text") is True

    def test_disabled_is_not_eligible(self, settings):
        settings.OLLAMA_CHAT_ENABLED = False
        assert llm_advisor._local_is_eligible(SCHEMA, "text") is False


class TestDispatchRouting:
    def test_non_local_key_goes_straight_to_api(self):
        with patch.object(llm_advisor, "_call_claude") as claude:
            claude.return_value = {"text": "{}", "input_tokens": 1,
                                   "output_tokens": 1, "model_id": "claude-haiku-4-5",
                                   "cache_read_tokens": 0, "cache_write_tokens": 0}
            _resp, used = llm_advisor._dispatch_call(
                "p", "haiku", 100, None, schema=SCHEMA,
            )
        assert used == "haiku"

    def test_local_success_does_not_call_api(self, settings):
        settings.OLLAMA_CHAT_ENABLED = True
        with patch("urllib.request.urlopen",
                   return_value=_ollama_response({"ok": True})), \
             patch.object(llm_advisor, "_call_claude") as claude:
            _resp, used = llm_advisor._dispatch_call(
                "p", "local", 100, None, schema=SCHEMA,
            )
        assert used == "local"
        claude.assert_not_called()

    def test_local_failure_falls_back_to_api(self, settings):
        """機能は落とさない。コストを払って動かす（ADR-0010）。"""
        settings.OLLAMA_CHAT_ENABLED = True
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("down")), \
             patch.object(llm_advisor, "_call_claude") as claude:
            claude.return_value = {"text": "{}", "input_tokens": 1,
                                   "output_tokens": 1, "model_id": "claude-haiku-4-5",
                                   "cache_read_tokens": 0, "cache_write_tokens": 0}
            _resp, used = llm_advisor._dispatch_call(
                "p", "local", 100, None, schema=SCHEMA,
            )
        assert used == "haiku"
        claude.assert_called_once()

    def test_local_does_not_check_budget(self, settings):
        """ローカルは従量課金ではないので上限で止める理由が無い。

        ADR-0010 の主目的は「予算上限に当たるのを層Cだけにする」こと。
        ここで予算チェックを通すとその狙いが崩れる。
        """
        settings.OLLAMA_CHAT_ENABLED = True
        with patch("urllib.request.urlopen",
                   return_value=_ollama_response({"ok": True})), \
             patch("apps.ai.services.cost_monitor.check_budget_and_notify") as budget:
            _resp, used = llm_advisor._dispatch_call(
                "p", "local", 100, MagicMock(), schema=SCHEMA,
            )
        assert used == "local"
        budget.assert_not_called()


class TestLocalCost:
    def test_local_costs_nothing(self):
        cost = llm_advisor._calculate_cost(10_000, 10_000, "local")
        assert cost == Decimal("0.000000")

    def test_haiku_still_costs(self):
        cost = llm_advisor._calculate_cost(10_000, 10_000, "haiku")
        assert cost > Decimal("0")


@pytest.mark.django_db
class TestAILogRecordsActualProvider:
    def _call(self, company, model_key, **kwargs):
        return llm_advisor.call_claude_with_log(
            prompt="p", model_key=model_key, max_tokens=100,
            company=company, site=None,
            task_type=AILog.TaskType.GENERAL_ANALYSIS,
            input_data={}, schema=SCHEMA, **kwargs,
        )

    def test_local_is_logged_as_custom_with_zero_cost(self, company_a, settings):
        settings.OLLAMA_CHAT_ENABLED = True
        with patch("urllib.request.urlopen",
                   return_value=_ollama_response({"ok": True})):
            result = self._call(company_a, "local")

        log = AILog.unscoped.get(pk=result["ai_log_id"])
        assert log.model_used == AILog.ModelType.CUSTOM
        assert log.model_version == "qwen3:8b"
        assert log.cost_usd == Decimal("0.000000")
        assert result["model_key"] == "local"

    def test_fallback_is_logged_as_the_api_model(self, company_a, settings):
        """ローカルを頼んで API に落ちた回を local として記録しない。

        そうしないと cost_usd が 0 で埋まり、費用の出所が追えなくなる。
        """
        settings.OLLAMA_CHAT_ENABLED = True
        fake = {"text": '{"ok": true}', "input_tokens": 1000,
                "output_tokens": 1000, "model_id": "claude-haiku-4-5",
                "cache_read_tokens": 0, "cache_write_tokens": 0}
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("down")), \
             patch.object(llm_advisor, "_call_claude", return_value=fake):
            result = self._call(company_a, "local")

        log = AILog.unscoped.get(pk=result["ai_log_id"])
        assert log.model_used == AILog.ModelType.CLAUDE_HAIKU
        assert log.cost_usd > Decimal("0")
        assert result["model_key"] == "haiku"


# ---------------------------------------------------------------------------
# matching 戦略5
# ---------------------------------------------------------------------------


def _make_item(company, code, name):
    return EstimationItem.unscoped.create(
        company=company, code=code, canonical_name=name, unit="m",
    )


@pytest.mark.django_db
class TestMatchByLlmProvider:
    def test_schema_constrains_codes_to_candidates(self, company_a):
        schema = matching._build_match_schema(["A-001", "A-002"])
        props = schema["properties"]["matches"]["items"]["properties"]
        assert props["candidate_code"]["enum"] == ["A-001", "A-002"]

    def test_schema_omits_unused_reason_field(self, company_a):
        """reason は本文が読まないので出力させない（実測 5.4秒→1.4秒）。"""
        schema = matching._build_match_schema(["A-001"])
        props = schema["properties"]["matches"]["items"]["properties"]
        assert "reason" not in props

    def test_local_result_is_used(self, company_a, settings):
        settings.OLLAMA_CHAT_ENABLED = True
        item = _make_item(company_a, "A-001", "VVFケーブル 1.6mm 2芯")

        payload = {"matches": [{"candidate_code": "A-001", "confidence": 0.5}]}
        with patch("urllib.request.urlopen",
                   return_value=_ollama_response(payload)), \
             patch.object(matching, "_ask_claude") as claude:
            got, confidence = matching._match_by_llm(
                "VVF 1.6-2C", "VVF1.6-2C", company_a, candidate_items=[item],
            )

        assert got == item
        assert confidence == Decimal("50.0")
        claude.assert_not_called()

    def test_falls_back_to_claude_when_local_down(self, company_a, settings):
        settings.OLLAMA_CHAT_ENABLED = True
        item = _make_item(company_a, "A-001", "VVFケーブル 1.6mm 2芯")

        payload = {"matches": [{"candidate_code": "A-001", "confidence": 0.5}]}
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("down")), \
             patch.object(matching, "_ask_claude", return_value=payload) as claude:
            got, _confidence = matching._match_by_llm(
                "VVF 1.6-2C", "VVF1.6-2C", company_a, candidate_items=[item],
            )

        assert got == item
        claude.assert_called_once()

    def test_too_many_candidates_skips_local(self, company_a, settings):
        """ctx=8192 に100件を詰め込まない。絞れていないときは API を使う。"""
        settings.OLLAMA_CHAT_ENABLED = True
        items = [
            _make_item(company_a, f"A-{i:03d}", f"品目{i}")
            for i in range(matching.LOCAL_MAX_CANDIDATES + 1)
        ]
        payload = {"matches": [{"candidate_code": "A-000", "confidence": 0.5}]}

        with patch("urllib.request.urlopen") as urlopen, \
             patch.object(matching, "_ask_claude", return_value=payload):
            got, _confidence = matching._match_by_llm(
                "品目0", "品目0", company_a, candidate_items=items,
            )

        urlopen.assert_not_called()
        assert got == items[0]

    def test_confidence_stays_below_review_threshold(self, company_a, settings):
        """ローカル経由でも人間の承認を飛ばさない。"""
        settings.OLLAMA_CHAT_ENABLED = True
        item = _make_item(company_a, "A-001", "VVFケーブル 1.6mm 2芯")

        payload = {"matches": [{"candidate_code": "A-001", "confidence": 0.99}]}
        with patch("urllib.request.urlopen",
                   return_value=_ollama_response(payload)):
            _got, confidence = matching._match_by_llm(
                "VVF 1.6-2C", "VVF1.6-2C", company_a, candidate_items=[item],
            )

        assert confidence == Decimal("60.0")

    def test_unknown_code_yields_no_match(self, company_a, settings):
        settings.OLLAMA_CHAT_ENABLED = True
        item = _make_item(company_a, "A-001", "VVFケーブル 1.6mm 2芯")

        payload = {"matches": [{"candidate_code": "NOPE", "confidence": 0.5}]}
        with patch("urllib.request.urlopen",
                   return_value=_ollama_response(payload)):
            got, confidence = matching._match_by_llm(
                "VVF 1.6-2C", "VVF1.6-2C", company_a, candidate_items=[item],
            )

        assert got is None
        assert confidence == Decimal("0")

    def test_both_providers_down_returns_nothing(self, company_a, settings):
        settings.OLLAMA_CHAT_ENABLED = True
        item = _make_item(company_a, "A-001", "VVFケーブル 1.6mm 2芯")

        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("down")), \
             patch.object(matching, "_ask_claude", return_value=None):
            got, confidence = matching._match_by_llm(
                "VVF 1.6-2C", "VVF1.6-2C", company_a, candidate_items=[item],
            )

        assert got is None
        assert confidence == Decimal("0")
