"""Claude API によるコスト最適化・工程提案サービス。

ML予測の数値結果を踏まえて、LLMが分析・提案を行う。
全呼び出しは AILog に記録し、フィードバック収集の対象となる。
"""

import json
import logging
import time
from decimal import Decimal

from django.conf import settings

from apps.ai.models import AILog
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
# モデルIDは日付サフィックスを付けないエイリアスを使う。
# claude-sonnet-4-6-20250725 は存在せず 404 になっていた。
MODEL_CONFIG = {
    "haiku": {
        "model_id": "claude-haiku-4-5",
        "input_price": 1.00,
        "output_price": 5.00,
        "display": AILog.ModelType.CLAUDE_HAIKU,
    },
    "sonnet": {
        "model_id": "claude-sonnet-5",
        "input_price": 3.00,
        "output_price": 15.00,
        "display": AILog.ModelType.CLAUDE_SONNET,
    },
}


def _calculate_cost(input_tokens, output_tokens, model_key):
    """API費用を計算する。"""
    config = MODEL_CONFIG.get(model_key, MODEL_CONFIG["haiku"])
    cost = (
        input_tokens * config["input_price"] / 1_000_000
        + output_tokens * config["output_price"] / 1_000_000
    )
    return Decimal(str(round(cost, 6)))


def _parse_json_response(text):
    """LLMレスポンスからJSON部分を抽出してパースする。"""
    # ```json ... ``` ブロックを探す
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


def _call_claude(prompt, model_key="haiku", max_tokens=2000, company=None):
    """Claude APIを呼び出す。月間予算チェック付き。

    Args:
        prompt: プロンプト文字列
        model_key: "haiku" or "sonnet"
        max_tokens: 最大出力トークン数
        company: テナント（予算チェック用、省略時はチェックなし）

    Returns:
        dict: {"text": str, "input_tokens": int, "output_tokens": int, "model_id": str}

    Raises:
        ValueError: 予算超過時
    """
    if not HAS_ANTHROPIC:
        raise ImportError("anthropic がインストールされていません。")

    # 月間予算チェック
    if company:
        from apps.ai.services.cost_monitor import check_budget_and_notify

        if not check_budget_and_notify(company):
            budget_jpy = getattr(settings, "AI_MONTHLY_BUDGET_JPY", 9900)
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

    message = client.messages.create(
        model=config["model_id"],
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )

    return {
        "text": message.content[0].text,
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
        "model_id": config["model_id"],
    }


def get_cost_optimization(site, user=None, model_key="haiku", prediction=None):
    """コスト最適化提案を取得する。

    Args:
        site: 対象の Site インスタンス
        user: 実行ユーザー（AILog 記録用）
        model_key: "haiku" or "sonnet"
        prediction: ML予測結果（あれば ml_predictor.predict() の戻り値）

    Returns:
        dict: {"parsed": パース済みJSON, "raw": 生テキスト, "ai_log_id": int}
    """
    start_time = time.time()

    summary = collect_site_summary(site)
    similar = find_similar_completed_sites(site)

    # ML予測結果があればプロンプトに含める
    ml_prediction = None
    if prediction:
        ml_prediction = {
            "predicted_final_cost": float(prediction["predicted_final_cost"]),
            "overrun_probability": prediction["overrun_probability"],
        }

    prompt = build_cost_optimization_prompt(summary, similar, ml_prediction)

    config = MODEL_CONFIG.get(model_key, MODEL_CONFIG["haiku"])
    response = _call_claude(prompt, model_key=model_key, company=site.company)
    latency_ms = int((time.time() - start_time) * 1000)

    # レスポンスをパース
    parsed = None
    status = AILog.Status.SUCCESS
    error_message = ""
    try:
        parsed = _parse_json_response(response["text"])
    except (json.JSONDecodeError, ValueError) as e:
        status = AILog.Status.ERROR
        error_message = f"JSON パース失敗: {e}"
        logger.warning("コスト最適化レスポンスのパースに失敗: %s", e)

    cost_usd = _calculate_cost(
        response["input_tokens"], response["output_tokens"], model_key
    )

    # AILog に記録
    ai_log = AILog.unscoped.create(
        company=site.company,
        site=site,
        task_type=AILog.TaskType.COST_OPTIMIZATION,
        model_used=config["display"],
        model_version=response["model_id"],
        input_data={
            "site_summary": summary,
            "similar_sites_count": len(similar),
            "has_ml_prediction": prediction is not None,
        },
        prompt=prompt,
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
    }


def get_schedule_suggestion(site, user=None, model_key="haiku"):
    """工程提案を取得する。

    Args:
        site: 対象の Site インスタンス
        user: 実行ユーザー
        model_key: "haiku" or "sonnet"

    Returns:
        dict: {"parsed": パース済みJSON, "raw": 生テキスト, "ai_log_id": int}
    """
    start_time = time.time()

    schedule_data = collect_schedule_data(site)
    prompt = build_schedule_suggestion_prompt(schedule_data)

    config = MODEL_CONFIG.get(model_key, MODEL_CONFIG["haiku"])
    response = _call_claude(prompt, model_key=model_key, max_tokens=3000, company=site.company)
    latency_ms = int((time.time() - start_time) * 1000)

    parsed = None
    status = AILog.Status.SUCCESS
    error_message = ""
    try:
        parsed = _parse_json_response(response["text"])
    except (json.JSONDecodeError, ValueError) as e:
        status = AILog.Status.ERROR
        error_message = f"JSON パース失敗: {e}"
        logger.warning("工程提案レスポンスのパースに失敗: %s", e)

    cost_usd = _calculate_cost(
        response["input_tokens"], response["output_tokens"], model_key
    )

    ai_log = AILog.unscoped.create(
        company=site.company,
        site=site,
        task_type=AILog.TaskType.SCHEDULE_SUGGEST,
        model_used=config["display"],
        model_version=response["model_id"],
        input_data=schedule_data,
        prompt=prompt,
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
    }


def get_schedule_risk_analysis(site, user=None, model_key="haiku"):
    """工程リスク分析を取得する。

    Args:
        site: 対象の Site インスタンス
        user: 実行ユーザー
        model_key: "haiku" or "sonnet"

    Returns:
        dict: {"parsed": パース済みJSON, "raw": 生テキスト, "ai_log_id": int}
    """
    start_time = time.time()

    summary = collect_site_summary(site)
    schedule_data = collect_schedule_data(site)
    prompt = build_schedule_risk_prompt(summary, schedule_data)

    config = MODEL_CONFIG.get(model_key, MODEL_CONFIG["haiku"])
    response = _call_claude(prompt, model_key=model_key, max_tokens=2500, company=site.company)
    latency_ms = int((time.time() - start_time) * 1000)

    parsed = None
    status = AILog.Status.SUCCESS
    error_message = ""
    try:
        parsed = _parse_json_response(response["text"])
    except (json.JSONDecodeError, ValueError) as e:
        status = AILog.Status.ERROR
        error_message = f"JSON パース失敗: {e}"
        logger.warning("工程リスク分析レスポンスのパースに失敗: %s", e)

    cost_usd = _calculate_cost(
        response["input_tokens"], response["output_tokens"], model_key
    )

    ai_log = AILog.unscoped.create(
        company=site.company,
        site=site,
        task_type=AILog.TaskType.SCHEDULE_RISK,
        model_used=config["display"],
        model_version=response["model_id"],
        input_data={
            "site_summary": summary,
            "schedule_data": schedule_data,
        },
        prompt=prompt,
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
    }
