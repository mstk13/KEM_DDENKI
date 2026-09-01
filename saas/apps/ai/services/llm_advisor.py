"""LLM によるコスト最適化・工程提案サービス。

ML予測の数値結果を踏まえて、LLMが分析・提案を行う。
全呼び出しは AILog に記録し、フィードバック収集の対象となる。

コスト最適化方針:
- Batch API（50%OFF）を基本とする。即時実行も可能。
- プロンプトキャッシュ（入力90%OFF）を全呼び出しで利用。
- OCR/抽出はHaiku、分析/提案はSonnet。
- 品質が価値の中核でないタスクはローカル推論に振る（ADR-0010 層B）。
  model_key="local" を指定すると Ollama を試し、駄目なら API に落ちる。

この関数群はプロバイダを跨ぐ唯一の関所であり、
apps.bids / apps.masters / apps.estimation の呼び出しも全てここを通る。
"""

import json
import logging
import time
from decimal import Decimal

from django.conf import settings

from apps.ai.models import AILog
from apps.ai.services import local_llm
from apps.ai.services.data_collector import (
    collect_schedule_data,
    collect_site_summary,
    find_similar_completed_sites,
)
from apps.ai.services.prompt_builder import (
    build_cost_optimization_prompt,
    build_schedule_risk_prompt,
    build_schedule_suggestion_prompt,
)

logger = logging.getLogger(__name__)

try:
    import anthropic

    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

# モデルIDと料金（USD / 1M tokens）
# バッチ料金 = 通常の50%。キャッシュ読み = 入力の10%。
MODEL_CONFIG = {
    "haiku": {
        "model_id": "claude-haiku-4-5",
        "input_price": 1.00,
        "output_price": 5.00,
        "cache_read_price": 0.10,   # input_price の 10%
        "cache_write_price": 1.25,  # input_price の 125%
        "display": AILog.ModelType.CLAUDE_HAIKU,
    },
    "sonnet": {
        "model_id": "claude-sonnet-5",
        "input_price": 3.00,
        "output_price": 15.00,
        "cache_read_price": 0.30,
        "cache_write_price": 3.75,
        "display": AILog.ModelType.CLAUDE_SONNET,
    },
    # ADR-0010 層B。ローカル推論（Ollama）。電気代しか掛からないので単価は0。
    # model_id は応答から実際のモデル名で上書きする。
    "local": {
        "model_id": "local",
        "input_price": 0.00,
        "output_price": 0.00,
        "cache_read_price": 0.00,
        "cache_write_price": 0.00,
        "display": AILog.ModelType.CUSTOM,
    },
}

# ローカルに振れる条件を満たさない呼び出しは、黙って API に戻す。
LOCAL_MODEL_KEY = "local"

# 分析系タスクの共通システムプロンプト（キャッシュ対象）
SYSTEM_PROMPT = (
    "あなたは建設業の業務管理システムのAIアシスタントです。"
    "コスト分析、工程提案、リスク分析を専門とします。"
    "常にJSON形式で回答してください。日本語で回答してください。"
    "データに基づいた具体的で実用的な提案を行ってください。"
)


def _calculate_cost(input_tokens, output_tokens, model_key,
                    is_batch=False, cache_read_tokens=0, cache_write_tokens=0):
    """API費用を計算する。バッチ・キャッシュ対応。"""
    config = MODEL_CONFIG.get(model_key, MODEL_CONFIG["haiku"])
    batch_factor = Decimal("0.5") if is_batch else Decimal("1")

    # 通常入力トークン（キャッシュされなかった分）
    normal_input = input_tokens - cache_read_tokens - cache_write_tokens
    if normal_input < 0:
        normal_input = 0

    cost = (
        Decimal(str(normal_input)) * Decimal(str(config["input_price"])) / 1_000_000
        + Decimal(str(cache_read_tokens)) * Decimal(str(config["cache_read_price"])) / 1_000_000
        + Decimal(str(cache_write_tokens)) * Decimal(str(config["cache_write_price"])) / 1_000_000
        + Decimal(str(output_tokens)) * Decimal(str(config["output_price"])) / 1_000_000
    )
    cost *= batch_factor
    return cost.quantize(Decimal("0.000001"))


def _first_text(message):
    """レスポンスから最初のテキストブロックを取り出す。

    content[0] がテキストとは限らない。Claude Sonnet 5 は thinking を指定しない
    と adaptive thinking が既定で有効になり、先頭が ThinkingBlock になる。
    thinking が入るかはモデルが都度決めるので、決め打ちすると
    'ThinkingBlock' object has no attribute 'text' で断続的に落ちる
    （2026-08-14 に本番で発生）。

    max_tokens は thinking と本文の合計に効くため、thinking で使い切ると
    テキストブロックが1つも無い応答になりうる。その場合は理由を添えて落とす。
    """
    for block in message.content:
        if getattr(block, "type", None) == "text":
            return block.text

    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "max_tokens":
        raise ValueError(
            "max_tokens に達したため本文が返りませんでした。"
            "thinking と本文の合計が上限に収まるよう max_tokens を増やしてください。"
        )
    kinds = ", ".join(sorted({getattr(b, "type", "?") for b in message.content}))
    raise ValueError(
        f"レスポンスにテキストブロックがありません（stop_reason={stop_reason}, "
        f"blocks={kinds or 'なし'}）。"
    )


def _parse_json_response(text):
    """LLMレスポンスからJSON部分を抽出してパースする。"""
    if "```json" in text:
        start = text.index("```json") + len("```json")
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + len("```")
        end = text.index("```", start)
        text = text[start:end].strip()

    return json.loads(text)


def get_api_key():
    """ANTHROPIC_API_KEY を settings → 環境変数の順で取得する。"""
    api_key = getattr(settings, "ANTHROPIC_API_KEY", None)
    if not api_key:
        import os

        api_key = os.environ.get("ANTHROPIC_API_KEY")
    return api_key or None


def check_availability():
    """LLM機能が使える状態かを返す。

    Returns:
        (available: bool, message: str | None)
        message は使えない理由。使える場合は None。
    """
    if not HAS_ANTHROPIC:
        return False, (
            "anthropic パッケージがインストールされていません。"
            "サーバー管理者に連絡してください。"
        )
    if not get_api_key():
        return False, (
            "Claude APIキーが未登録のため、AI機能は実行できません。"
            "サーバーの saas/.env に ANTHROPIC_API_KEY を設定し、"
            "コンテナを再起動してください。"
        )
    return True, None


def _call_claude(prompt, model_key="haiku", max_tokens=2000, company=None,
                 system_prompt=None, content=None):
    """Claude APIを呼び出す。プロンプトキャッシュ・予算チェック付き。

    Args:
        prompt: プロンプト文字列（contentが無い場合に使用）
        model_key: "haiku" or "sonnet"
        max_tokens: 最大出力トークン数
        company: テナント（予算チェック用）
        system_prompt: システムプロンプト（cache_control付きで送信）
        content: メッセージcontent（画像等を含む場合に直接指定）

    Returns:
        dict: {
            "text": str,
            "input_tokens": int,
            "output_tokens": int,
            "model_id": str,
            "cache_read_tokens": int,
            "cache_write_tokens": int,
        }
    """
    if not HAS_ANTHROPIC:
        raise ImportError("anthropic がインストールされていません。")

    # 月間予算チェック
    if company:
        from apps.ai.services.cost_monitor import check_budget_and_notify

        if not check_budget_and_notify(company):
            budget_jpy = getattr(settings, "AI_MONTHLY_BUDGET_JPY", 4000)
            raise ValueError(
                f"月間API使用量が上限(¥{budget_jpy:,})に達しました。"
                "来月まで AI 機能は利用できません。"
            )

    api_key = get_api_key()
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY が設定されていません。"
            ".env または settings.py で設定してください。"
        )

    config = MODEL_CONFIG.get(model_key, MODEL_CONFIG["haiku"])
    client = anthropic.Anthropic(api_key=api_key)

    # メッセージ構築
    messages = [{"role": "user", "content": content or prompt}]

    # システムプロンプト（キャッシュ対応）
    system = None
    if system_prompt:
        system = [{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }]

    kwargs = {
        "model": config["model_id"],
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system

    message = client.messages.create(**kwargs)

    # キャッシュトークンを取得
    usage = message.usage
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0

    return {
        "text": _first_text(message),
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "model_id": config["model_id"],
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
    }


def _local_is_eligible(schema, content):
    """この呼び出しをローカルに振ってよいか。

    振れないのは仕様であって異常ではないので、理由をログに残して静かに API へ戻す。
    """
    if content is not None and not isinstance(content, str):
        # 画像・PDF ブロック。qwen3:8b はテキスト専用で vision を持たない。
        logger.info("マルチモーダル入力のためローカルに振れません。APIを使います。")
        return False
    if not schema:
        # Schema 無しの format="json" は構造もキー名も守られない。
        # 実測で出力トークンが14倍、所要が13倍になるうえ結果も信用できない。
        logger.info("JSON Schema が無いためローカルに振れません。APIを使います。")
        return False
    return local_llm.is_configured()


def _call_local(prompt, schema, max_tokens=None, system_prompt=None,
                keep_alive=None):
    """ローカル推論を1回試す。失敗時は None を返す（例外は投げない）。

    月間予算チェックは通さない。ローカルは従量課金ではないので、
    上限に達していても止める理由が無い。むしろ ADR-0010 の狙いは
    「予算上限に当たるのを層Cだけにして、業務が止まる範囲を狭める」ことにある。
    """
    result = local_llm.chat_json(
        prompt, schema, system_prompt=system_prompt or "", keep_alive=keep_alive,
    )
    if result is None:
        return None

    return {
        "text": result["text"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        # 実際に応答したモデル名を記録する（qwen3:8b と 14b を取り違えない）。
        "model_id": result["model_id"],
        # ローカルにプロンプトキャッシュは無い。
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def _dispatch_call(prompt, model_key, max_tokens, company, system_prompt=None,
                   content=None, schema=None, local_keep_alive=None,
                   local_fallback_key="haiku"):
    """model_key に応じて実行先を選ぶ。

    model_key="local" のときだけローカルを試し、駄目なら
    local_fallback_key の Claude モデルに落とす。
    「機能を落とすのではなくコストを払って動かす」（ADR-0010）。

    Returns:
        (response, used_model_key)
    """
    if model_key != LOCAL_MODEL_KEY:
        response = _call_claude(
            prompt, model_key=model_key, max_tokens=max_tokens,
            company=company, system_prompt=system_prompt, content=content,
        )
        return response, model_key

    if _local_is_eligible(schema, content):
        response = _call_local(
            prompt, schema, max_tokens=max_tokens,
            system_prompt=system_prompt, keep_alive=local_keep_alive,
        )
        if response is not None:
            return response, LOCAL_MODEL_KEY

    response = _call_claude(
        prompt, model_key=local_fallback_key, max_tokens=max_tokens,
        company=company, system_prompt=system_prompt, content=content,
    )
    return response, local_fallback_key


def call_claude_with_log(prompt, model_key, max_tokens, company, site,
                         task_type, input_data, user=None,
                         system_prompt=None, content=None,
                         schema=None, local_keep_alive=None,
                         local_fallback_key="haiku"):
    """LLMを呼び出し、AILogに記録する共通関数。

    全てのAI機能はこの関数を通すことで、ログ記録・コスト計算を統一する。

    model_key="local" を渡すとローカル推論（ADR-0010 層B）を試し、
    到達不可・スキーマ違反なら local_fallback_key の Claude モデルに落ちる。
    ローカルを使うには schema（JSON Schema オブジェクト）が必須。
    AILog にはフォールバック後の実際の実行先が記録される。
    """
    start_time = time.time()

    response, used_model_key = _dispatch_call(
        prompt, model_key=model_key, max_tokens=max_tokens,
        company=company, system_prompt=system_prompt, content=content,
        schema=schema, local_keep_alive=local_keep_alive,
        local_fallback_key=local_fallback_key,
    )
    latency_ms = int((time.time() - start_time) * 1000)

    # 要求ではなく実績で記録する。ローカルを頼んで API に落ちた回は
    # API として記録されないと、コストの出所が追えなくなる。
    config = MODEL_CONFIG.get(used_model_key, MODEL_CONFIG["haiku"])

    # レスポンスをパース
    parsed = None
    status = AILog.Status.SUCCESS
    error_message = ""
    try:
        parsed = _parse_json_response(response["text"])
    except (json.JSONDecodeError, ValueError) as e:
        status = AILog.Status.ERROR
        error_message = f"JSON パース失敗: {e}"
        logger.warning("AIレスポンスのパースに失敗 (%s): %s", task_type, e)

    cost_usd = _calculate_cost(
        response["input_tokens"], response["output_tokens"], used_model_key,
        cache_read_tokens=response["cache_read_tokens"],
        cache_write_tokens=response["cache_write_tokens"],
    )

    ai_log = AILog.unscoped.create(
        company=company,
        site=site,
        task_type=task_type,
        model_used=config["display"],
        model_version=response["model_id"],
        input_data=input_data,
        prompt=prompt[:10000] if prompt else "",
        response=response["text"],
        response_parsed=parsed,
        status=status,
        error_message=error_message,
        latency_ms=latency_ms,
        input_tokens=response["input_tokens"],
        output_tokens=response["output_tokens"],
        cost_usd=cost_usd,
        requested_by=user,
    )

    return {
        "parsed": parsed,
        "raw": response["text"],
        "ai_log_id": ai_log.pk,
        "cost_usd": cost_usd,
        "cache_read_tokens": response["cache_read_tokens"],
        # "local" を頼んで "haiku" が返ることがある。呼び出し側が
        # フォールバックの発生を検知できるようにしておく。
        "model_key": used_model_key,
    }


def get_cost_optimization(site, user=None, model_key="sonnet", prediction=None):
    """コスト最適化提案を取得する。デフォルトSonnet（分析系）。"""
    summary = collect_site_summary(site)
    similar = find_similar_completed_sites(site)

    ml_prediction = None
    if prediction:
        ml_prediction = {
            "predicted_final_cost": float(prediction["predicted_final_cost"]),
            "overrun_probability": prediction["overrun_probability"],
        }

    prompt = build_cost_optimization_prompt(summary, similar, ml_prediction)

    return call_claude_with_log(
        prompt=prompt,
        model_key=model_key,
        max_tokens=2000,
        company=site.company,
        site=site,
        task_type=AILog.TaskType.COST_OPTIMIZATION,
        input_data={
            "site_summary": summary,
            "similar_sites_count": len(similar),
            "has_ml_prediction": prediction is not None,
        },
        user=user,
        system_prompt=SYSTEM_PROMPT,
    )


def get_schedule_suggestion(site, user=None, model_key="sonnet"):
    """工程提案を取得する。デフォルトSonnet（分析系）。"""
    schedule_data = collect_schedule_data(site)
    prompt = build_schedule_suggestion_prompt(schedule_data)

    return call_claude_with_log(
        prompt=prompt,
        model_key=model_key,
        max_tokens=3000,
        company=site.company,
        site=site,
        task_type=AILog.TaskType.SCHEDULE_SUGGEST,
        input_data=schedule_data,
        user=user,
        system_prompt=SYSTEM_PROMPT,
    )


def get_schedule_risk_analysis(site, user=None, model_key="sonnet"):
    """工程リスク分析を取得する。デフォルトSonnet（分析系）。"""
    summary = collect_site_summary(site)
    schedule_data = collect_schedule_data(site)
    prompt = build_schedule_risk_prompt(summary, schedule_data)

    return call_claude_with_log(
        prompt=prompt,
        model_key=model_key,
        max_tokens=2500,
        company=site.company,
        site=site,
        task_type=AILog.TaskType.SCHEDULE_RISK,
        input_data={
            "site_summary": summary,
            "schedule_data": schedule_data,
        },
        user=user,
        system_prompt=SYSTEM_PROMPT,
    )
