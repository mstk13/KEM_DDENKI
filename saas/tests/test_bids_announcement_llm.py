"""文字が (cid) 化した公告PDFを Claude に読ませる経路。

Claude API には接続しない。呼び先を差し替えて経路と正規化だけを見る。
"""
import pytest

from apps.bids import announcement_llm
from apps.bids.announcement_llm import _normalize, extract_with_llm
from apps.bids.models import BidProject
from apps.bids.services import fill_announcement

MINIMAL_PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"


class TestNormalize:
    def test_maps_to_the_same_shape_as_deterministic_extraction(self):
        result = _normalize({
            "work_outline": " 電気設備改修 一式 ",
            "requirements": "電気設備工事Ｂ等級又はＣ等級に認定されている者",
            "required_grades": "bc",
            "required_score": "780",
        })
        assert result["work_outline"] == "電気設備改修 一式"
        assert result["required_grades"] == "BC"
        assert result["required_score"] == 780
        # 下限表記はLLMに判定させない（列挙と混ざるため）
        assert result["required_grade"] == ""
        assert result["garbled"] is False
        assert result["by_llm"] is True

    def test_drops_junk_grades_and_scores(self):
        result = _normalize({
            "work_outline": "",
            "requirements": "",
            "required_grades": "該当なし",
            "required_score": "不明",
        })
        assert result["required_grades"] == ""
        assert result["required_score"] is None

    def test_missing_keys(self):
        result = _normalize({})
        assert result["work_outline"] == ""
        assert result["required_score"] is None


@pytest.mark.django_db
class TestExtractWithLLM:
    def _stub_call(self, monkeypatch, parsed):
        calls = {}

        def fake(**kwargs):
            calls.update(kwargs)
            return {"parsed": parsed, "raw": "", "ai_log_id": 1, "cost_usd": 0}

        monkeypatch.setattr(
            "apps.ai.services.llm_advisor.call_claude_with_log", fake,
        )
        return calls

    def test_sends_the_pdf_as_a_document_block(self, monkeypatch, company_a):
        calls = self._stub_call(monkeypatch, {
            "work_outline": "電気設備改修", "requirements": "Ｂ等級",
            "required_grades": "B", "required_score": None,
        })
        result = extract_with_llm(MINIMAL_PDF, company=company_a)

        assert result["work_outline"] == "電気設備改修"
        block = calls["content"][0]
        assert block["type"] == "document"
        assert block["source"]["media_type"] == "application/pdf"
        # 予算チェックとログのためにテナントを渡している
        assert calls["company"] == company_a

    def test_rejects_non_pdf(self, monkeypatch, company_a):
        self._stub_call(monkeypatch, {})
        assert extract_with_llm(b"<html>", company=company_a) is None

    def test_requires_company_for_budget_check(self, monkeypatch):
        self._stub_call(monkeypatch, {})
        assert extract_with_llm(MINIMAL_PDF, company=None) is None

    def test_rejects_oversized_pdf(self, monkeypatch, company_a):
        self._stub_call(monkeypatch, {})
        big = MINIMAL_PDF + b"0" * announcement_llm.MAX_PDF_BYTES
        assert extract_with_llm(big, company=company_a) is None

    def test_api_failure_returns_none(self, monkeypatch, company_a):
        def boom(**kwargs):
            raise ValueError("月間API使用量が上限に達しました")

        monkeypatch.setattr(
            "apps.ai.services.llm_advisor.call_claude_with_log", boom,
        )
        # 予算超過やAPI障害で案件取得を失敗させない
        assert extract_with_llm(MINIMAL_PDF, company=company_a) is None

    def test_unparseable_response_returns_none(self, monkeypatch, company_a):
        self._stub_call(monkeypatch, None)
        assert extract_with_llm(MINIMAL_PDF, company=company_a) is None


@pytest.mark.django_db
class TestGarbledFallback:
    """決定論的に読めたときは LLM を呼ばない。読めないときだけ呼ぶ。"""

    def _project(self, company_a, user_a, **kwargs):
        defaults = {
            "title": "立川防災合同庁舎（２６）電気設備改修工事",
            "source_url": "https://example.go.jp/a",
            "document_urls": "https://example.go.jp/a\nhttps://example.go.jp/b",
        }
        defaults.update(kwargs)
        return BidProject.unscoped.create(
            company=company_a, created_by=user_a, **defaults,
        )

    def _patch(self, monkeypatch, *, extract_result, llm_result, available=True):
        from apps.bids import announcement

        monkeypatch.setattr(announcement, "extract_from_url", extract_result)
        monkeypatch.setattr(announcement, "fetch_document", lambda url: MINIMAL_PDF)
        monkeypatch.setattr(announcement_llm, "is_available", lambda: available)
        monkeypatch.setattr(
            announcement_llm, "extract_with_llm",
            lambda data, company, user=None: llm_result,
        )

    GARBLED = {
        "work_outline": "", "requirements": "", "required_grade": "",
        "required_grades": "", "required_score": None,
        "headings": [], "garbled": True,
    }
    READABLE = {
        "work_outline": "決定論的に読めた概要", "requirements": "決定論的に読めた要件",
        "required_grade": "", "required_grades": "B", "required_score": None,
        "headings": [], "garbled": False,
    }

    def test_llm_is_used_only_when_text_is_garbled(
        self, monkeypatch, company_a, user_a,
    ):
        self._patch(
            monkeypatch,
            extract_result=lambda url: dict(self.GARBLED),
            llm_result={
                "work_outline": "LLMが読んだ概要",
                "requirements": "電気設備工事Ｂ等級に認定されている者",
                "required_grade": "", "required_grades": "B",
                "required_score": None, "headings": [], "garbled": False,
            },
        )
        project = self._project(company_a, user_a)
        assert fill_announcement(project) is True

        project.refresh_from_db()
        assert project.work_outline == "LLMが読んだ概要"
        assert project.required_grades == "B"

    def test_llm_is_not_called_when_deterministic_extraction_works(
        self, monkeypatch, company_a, user_a,
    ):
        def must_not_run(data, company, user=None):
            raise AssertionError("決定論的に読めたのに LLM を呼んでいる")

        from apps.bids import announcement

        monkeypatch.setattr(
            announcement, "extract_from_url", lambda url: dict(self.READABLE),
        )
        monkeypatch.setattr(announcement_llm, "extract_with_llm", must_not_run)

        project = self._project(company_a, user_a)
        assert fill_announcement(project) is True
        project.refresh_from_db()
        assert project.work_outline == "決定論的に読めた概要"

    def test_llm_unavailable_leaves_fields_empty(
        self, monkeypatch, company_a, user_a,
    ):
        self._patch(
            monkeypatch,
            extract_result=lambda url: dict(self.GARBLED),
            llm_result=None,
            available=False,
        )
        project = self._project(company_a, user_a)
        assert fill_announcement(project) is False
        project.refresh_from_db()
        assert project.work_outline == ""
