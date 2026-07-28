"""AI 見積もりエンジン — 過去の実績データを基に Claude API で最適コストを提案。

使い方:
    from shared.ai_estimator import estimate_project_cost

    result = estimate_project_cost(
        description="〇〇基地 電気設備改修工事",
        category="電気工事",
        region="東京都",
    )
    print(result["summary"])
    print(result["breakdown"])
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dbconn import get_conn  # noqa: E402

import psycopg2.extras


def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _get_historical_projects(category: str | None = None, region: str | None = None,
                              limit: int = 50) -> list[dict]:
    """AI見積もり用ビューから過去の類似案件データを取得。"""
    sql = "SELECT * FROM ai.project_cost_summary WHERE estimate_amount IS NOT NULL"
    params: list = []
    if category:
        sql += " AND category = %s"
        params.append(category)
    if region:
        sql += " AND region = %s"
        params.append(region)
    sql += " ORDER BY created_at DESC LIMIT %s"
    params.append(limit)

    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def _get_item_cost_data(limit: int = 100) -> list[dict]:
    """品目別コスト分析ビューからデータを取得。"""
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM ai.item_cost_analysis ORDER BY item_name LIMIT %s", (limit,))
            return [dict(r) for r in cur.fetchall()]


def _get_unit_prices() -> list[dict]:
    """入札用単価マスタを取得。"""
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT category, item_name, unit, unit_price FROM bid.unit_prices ORDER BY category, item_name")
            return [dict(r) for r in cur.fetchall()]


def _serialize_for_prompt(data: list[dict]) -> str:
    """データを JSON に安全に変換する（date/Decimal 等を文字列化）。"""
    def _default(obj):
        return str(obj)
    return json.dumps(data, ensure_ascii=False, indent=2, default=_default)


def estimate_project_cost(
    description: str,
    category: str | None = None,
    region: str | None = None,
    budget: int | None = None,
    items: list[dict] | None = None,
) -> dict:
    """Claude API を使って過去実績に基づく最適見積もりを生成する。

    Args:
        description: 案件の説明（工事名・内容）
        category: 工事種別
        region: エリア
        budget: 予定価格（分かっていれば）
        items: 見積もり明細（あれば）— [{"name": "VVFケーブル", "qty": 100, "unit": "m"}, ...]

    Returns:
        dict with keys:
            summary: 見積もり概要テキスト
            total_estimate: 推奨見積もり金額
            breakdown: 内訳リスト
            confidence: 推定の信頼度 ("high"/"medium"/"low")
            reasoning: 推定根拠の説明
            raw_response: Claude の生レスポンス
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "summary": "ANTHROPIC_API_KEY が設定されていません。.env に設定してください。",
            "total_estimate": None,
            "breakdown": [],
            "confidence": "none",
            "reasoning": "API キー未設定",
            "raw_response": None,
        }

    # 過去データ収集
    historical = _get_historical_projects(category, region, limit=30)
    item_costs = _get_item_cost_data(limit=50)
    unit_prices = _get_unit_prices()

    # データの統計サマリー
    stats = {}
    if historical:
        estimates = [h["estimate_amount"] for h in historical if h.get("estimate_amount")]
        actuals = [h["actual_cost"] for h in historical if h.get("actual_cost")]
        if estimates:
            stats["見積金額"] = {
                "件数": len(estimates),
                "平均": int(sum(estimates) / len(estimates)),
                "最小": min(estimates),
                "最大": max(estimates),
            }
        if actuals:
            stats["実際原価"] = {
                "件数": len(actuals),
                "平均": int(sum(actuals) / len(actuals)),
                "最小": min(actuals),
                "最大": max(actuals),
            }
        rates = [h["profit_rate"] for h in historical if h.get("profit_rate") is not None]
        if rates:
            stats["原価率"] = {
                "平均": round(sum(rates) / len(rates), 1),
                "最小": round(min(rates), 1),
                "最大": round(max(rates), 1),
            }
        man_hours = [float(h["total_man_hours"]) for h in historical if h.get("total_man_hours") and float(h["total_man_hours"]) > 0]
        if man_hours:
            stats["人工時間(h)"] = {
                "平均": round(sum(man_hours) / len(man_hours), 1),
                "最小": round(min(man_hours), 1),
                "最大": round(max(man_hours), 1),
            }

    # プロンプト構築
    system_prompt = """あなたは電気工事会社「株式会社ケンモチ電機」のコスト見積もりAIアシスタントです。
過去の入札・施工実績データと材料単価データに基づいて、新規案件の最適な見積もり金額を提案してください。

以下の観点で分析してください：
1. 過去の類似案件の見積金額・実績原価・利益率
2. 材料費の最適調達先と単価
3. 想定される人工数（作業日報の実績から）
4. 競合他社の落札価格（データがあれば）
5. 適切な利益率の設定

回答は必ず以下のJSON形式で返してください：
{
  "total_estimate": 見積もり推奨金額(整数),
  "breakdown": [
    {"category": "材料費", "amount": 金額, "detail": "説明"},
    {"category": "人件費", "amount": 金額, "detail": "説明"},
    {"category": "諸経費", "amount": 金額, "detail": "説明"},
    {"category": "利益", "amount": 金額, "detail": "説明"}
  ],
  "confidence": "high" or "medium" or "low",
  "reasoning": "推定根拠の説明（日本語200文字以内）",
  "recommendations": ["改善提案1", "改善提案2"]
}"""

    user_prompt_parts = [f"## 新規案件\n{description}"]
    if category:
        user_prompt_parts.append(f"工事種別: {category}")
    if region:
        user_prompt_parts.append(f"エリア: {region}")
    if budget:
        user_prompt_parts.append(f"予定価格: {budget:,} 円")
    if items:
        user_prompt_parts.append(f"\n## 見積もり明細\n{_serialize_for_prompt(items)}")

    if stats:
        user_prompt_parts.append(f"\n## 過去実績の統計\n{_serialize_for_prompt(stats)}")

    if historical:
        # 最近5件の詳細を送る
        recent = []
        for h in historical[:5]:
            recent.append({
                "案件名": h["title"],
                "種別": h["category"],
                "エリア": h["region"],
                "見積金額": h.get("estimate_amount"),
                "実際原価": h.get("actual_cost"),
                "原価率": h.get("profit_rate"),
                "人工時間": float(h["total_man_hours"]) if h.get("total_man_hours") else None,
                "材料費": float(h["material_cost"]) if h.get("material_cost") else None,
                "最安競合額": h.get("lowest_competitor_amount"),
            })
        user_prompt_parts.append(f"\n## 直近の類似案件実績\n{_serialize_for_prompt(recent)}")

    if item_costs:
        top_items = item_costs[:20]
        user_prompt_parts.append(f"\n## 品目別コストデータ（上位20品目）\n{_serialize_for_prompt(top_items)}")

    if unit_prices:
        user_prompt_parts.append(f"\n## 単価マスタ\n{_serialize_for_prompt(unit_prices[:30])}")

    user_prompt = "\n".join(user_prompt_parts)
    user_prompt += "\n\n上記データを基に、この案件の最適な見積もり金額をJSON形式で提案してください。"

    # Claude API 呼び出し
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=os.getenv("AI_ESTIMATE_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw_text = response.content[0].text

        # JSONを抽出
        json_str = raw_text
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]

        result = json.loads(json_str.strip())
        result["raw_response"] = raw_text
        result["summary"] = (
            f"推奨見積金額: ¥{result['total_estimate']:,}\n"
            f"信頼度: {result['confidence']}\n"
            f"{result.get('reasoning', '')}"
        )
        return result

    except json.JSONDecodeError:
        return {
            "summary": "AI の応答を解析できませんでした。",
            "total_estimate": None,
            "breakdown": [],
            "confidence": "low",
            "reasoning": raw_text if 'raw_text' in dir() else "応答なし",
            "raw_response": raw_text if 'raw_text' in dir() else None,
        }
    except Exception as e:
        return {
            "summary": f"AI 見積もりエラー: {e}",
            "total_estimate": None,
            "breakdown": [],
            "confidence": "none",
            "reasoning": str(e),
            "raw_response": None,
        }


def estimate_for_bid_project(project_id: int) -> dict:
    """入札案件IDから見積もりを行う。bid.projects のデータを取得して estimate_project_cost に渡す。"""
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM bid.projects WHERE id = %s", (project_id,))
            project = cur.fetchone()
            if not project:
                return {"summary": "案件が見つかりません。", "total_estimate": None,
                        "breakdown": [], "confidence": "none", "reasoning": ""}

            # 見積もり明細があれば取得
            items = None
            cur.execute("""
                SELECT el.*, im.name AS item_name, im.spec, im.unit
                FROM material.estimate_line el
                JOIN material.estimate_header eh ON eh.id = el.header_id
                JOIN material.item_master im ON im.id = el.item_id
                WHERE eh.project_id = %s
                ORDER BY eh.version DESC, el.sort_order
            """, (project_id,))
            rows = cur.fetchall()
            if rows:
                items = [{"name": r["item_name"], "spec": r["spec"], "unit": r["unit"],
                          "qty": r["quantity"], "unit_price": r["unit_price"]} for r in rows]

    return estimate_project_cost(
        description=project["title"],
        category=project.get("category"),
        region=project.get("region"),
        budget=project.get("budget"),
        items=items,
    )
