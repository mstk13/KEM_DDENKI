"""プロンプトビルダー。

収集データからClaude API用のプロンプトを構築する。
構造化入力 → 構造化出力（JSON）を徹底する。
"""

import json


def build_cost_optimization_prompt(site_summary, similar_sites, prediction=None):
    """コスト最適化提案用プロンプトを構築する。

    Args:
        site_summary: collect_site_summary() の出力。
        similar_sites: find_similar_completed_sites() の出力。
        prediction: ML予測結果（あれば）。
            {"predicted_final_cost": float, "overrun_probability": float}

    Returns:
        str: Claude APIに送るプロンプト。
    """
    site = site_summary["site"]
    features = site_summary["cost_features"]

    # 予算vs実績テーブル
    budget_lines = []
    for cat in site_summary["budget_vs_actual"]:
        pct = f"{cat['consumption_pct']}%" if cat["consumption_pct"] else "N/A"
        budget_lines.append(
            f"  - {cat['name']}: 予算 {cat['budget']:,.0f}円 / "
            f"実績 {cat['actual']:,.0f}円 ({pct})"
        )
    budget_table = "\n".join(budget_lines) if budget_lines else "  データなし"

    # 類似現場サマリ
    similar_lines = []
    for ss in similar_sites[:3]:
        similar_lines.append(
            f"  - {ss['site_name']}: 受注 {ss['contract_amount']:,.0f}円 / "
            f"最終消化率 {ss['final_consumption_pct']}% / "
            f"粗利 {ss['gross_profit']:,.0f}円"
        )
    similar_table = "\n".join(similar_lines) if similar_lines else "  類似データなし"

    # ML予測
    prediction_section = ""
    if prediction:
        prediction_section = f"""
## ML予測結果
- 最終原価予測: {prediction['predicted_final_cost']:,.0f}円
- 予算超過確率: {prediction['overrun_probability']:.1%}
"""

    prompt = f"""あなたは電気工事の原価管理の専門家です。
以下の現場データを分析し、コスト最適化の提案をJSON形式で出力してください。

## 現場情報
- 現場名: {site['name']}
- 得意先: {site['customer'] or '未設定'}
- 受注金額: {site['contract_amount']:,.0f}円
- 工期: {site['start_date']} 〜 {site['end_date']}
- 進捗: 工期{features['elapsed_ratio']:.0%}経過 / 予算{features['consumption_ratio']:.0%}消化

## 予算vs実績（原価区分別）
{budget_table}

## 消化ペース
- 全期間平均: {features['daily_burn']:,.0f}円/日
- 直近7日平均: {features['recent_daily_burn']:,.0f}円/日
- 加速度: {features['burn_acceleration']:.2f}（1.0以上なら加速中）

## 労務データ
- 総作業時間: {features['total_work_hours']:,.1f}時間
- 残業比率: {features['overtime_ratio']:.1%}
- 作業員数: {features['worker_count']}人

## 工程
- 全{features['process_count']}工程 / 遅延率: {features['delay_ratio']:.0%}
{prediction_section}
## 類似現場の実績（完工済）
{similar_table}

## 出力形式（このJSON構造に厳密に従ってください）
```json
{{
  "risk_level": "high または medium または low",
  "current_analysis": "現状の分析（3文以内）",
  "predicted_issues": [
    "予想される問題点1",
    "予想される問題点2"
  ],
  "recommendations": [
    {{
      "action": "具体的なアクション",
      "category": "labor または material または outsourcing または schedule",
      "expected_saving_pct": 5,
      "priority": "high または medium または low",
      "reason": "この提案の根拠"
    }}
  ],
  "monthly_budget_suggestion": {{
    "description": "今後の月別予算配分の提案",
    "remaining_months": [
      {{"month": "2026-09", "suggested_budget": 500000}}
    ]
  }}
}}
```"""

    return prompt


def build_schedule_suggestion_prompt(schedule_data):
    """工程提案用プロンプトを構築する。

    Args:
        schedule_data: collect_schedule_data() の出力。

    Returns:
        str: Claude APIに送るプロンプト。
    """
    site = schedule_data["site"]

    # 工種一覧
    work_types = "、".join(site["work_types"]) if site["work_types"] else "未設定"

    # 既存テンプレート
    template_lines = []
    for tmpl in schedule_data["templates"]:
        items = ", ".join(
            f"{item['name']}(+{item['offset_days_start']}〜+{item['offset_days_end']}日)"
            for item in tmpl["items"]
        )
        template_lines.append(f"  - {tmpl['template_name']}: {items}")
    template_section = (
        "\n".join(template_lines) if template_lines else "  テンプレートなし"
    )

    # 類似現場の工程実績
    similar_lines = []
    for sp in schedule_data["similar_site_processes"]:
        similar_lines.append(f"  ### {sp['site_name']}（{sp['duration_days']}日間）")
        for proc in sp["processes"]:
            planned = f"{proc['planned_start']}〜{proc['planned_end']}"
            actual = ""
            if proc["actual_start"] and proc["actual_end"]:
                actual = f" → 実績: {proc['actual_start']}〜{proc['actual_end']}"
            elif proc["actual_start"]:
                actual = f" → 実績開始: {proc['actual_start']}"
            status_label = proc["status"]
            similar_lines.append(
                f"    - {proc['name']}({proc['work_type__name']}): "
                f"計画 {planned}{actual} [{status_label}]"
            )
    similar_section = (
        "\n".join(similar_lines)
        if similar_lines
        else "  類似現場データなし"
    )

    # 工期日数計算
    duration_info = ""
    if site["start_date"] and site["end_date"]:
        from datetime import date

        start = date.fromisoformat(site["start_date"])
        end = date.fromisoformat(site["end_date"])
        duration_info = f"（{(end - start).days}日間）"

    prompt = f"""あなたは電気工事の工程管理の専門家です。
以下の現場情報をもとに最適な工程計画を提案してください。

## 新規現場
- 現場名: {site['name']}
- 工種: {work_types}
- 受注金額: {site['contract_amount']:,.0f}円
- 工期: {site['start_date']} 〜 {site['end_date']}{duration_info}

## 既存テンプレート
{template_section}

## 類似現場の工程実績（計画→実績の乖離に注目）
{similar_section}

## 出力形式（このJSON構造に厳密に従ってください）
```json
{{
  "recommended_template": "最も適したテンプレート名（なければnull）",
  "phases": [
    {{
      "name": "工程名",
      "work_type": "対応する工種名",
      "start_offset_days": 0,
      "end_offset_days": 14,
      "estimated_progress_rate": "進捗の目安（例: 序盤は遅め）",
      "risk_note": "この工程で注意すべきポイント"
    }}
  ],
  "milestones": [
    {{
      "name": "マイルストーン名",
      "offset_days": 30,
      "importance": "high または medium または low"
    }}
  ],
  "warnings": [
    "過去の類似現場から得られた注意点"
  ],
  "resource_suggestion": {{
    "peak_workers": 5,
    "peak_period": "工程名 の期間",
    "note": "人員配置の提案"
  }}
}}
```"""

    return prompt


def build_schedule_risk_prompt(site_summary, schedule_data):
    """工程リスク分析用プロンプトを構築する。

    進行中の現場の工程遅延リスクを分析する。

    Args:
        site_summary: collect_site_summary() の出力。
        schedule_data: collect_schedule_data() の出力。

    Returns:
        str: Claude APIに送るプロンプト。
    """
    site = site_summary["site"]

    # 現在の工程状況
    process_lines = []
    for proc in site_summary["processes"]:
        planned = f"{proc['planned_start']}〜{proc['planned_end']}"
        actual_start = proc.get("actual_start", "")
        actual_end = proc.get("actual_end", "")
        actual = ""
        if actual_start and actual_end:
            actual = f" → 実績: {actual_start}〜{actual_end}"
        elif actual_start:
            actual = f" → 実績開始: {actual_start}（進行中）"
        process_lines.append(
            f"  - {proc['name']}: 計画 {planned}{actual} [{proc['status']}]"
        )
    process_section = (
        "\n".join(process_lines)
        if process_lines
        else "  工程データなし"
    )

    features = site_summary["cost_features"]

    prompt = f"""あなたは電気工事の工程管理の専門家です。
以下の現場の工程遅延リスクを分析してください。

## 現場情報
- 現場名: {site['name']}
- 受注金額: {site['contract_amount']:,.0f}円
- 工期: {site['start_date']} 〜 {site['end_date']}
- 工期進捗: {features['elapsed_ratio']:.0%}
- 予算消化率: {features['consumption_ratio']:.0%}
- 残業比率: {features['overtime_ratio']:.1%}

## 現在の工程状況
{process_section}

## 月別コスト推移
{json.dumps(site_summary['monthly_trend'], ensure_ascii=False, indent=2)}

## 出力形式（このJSON構造に厳密に従ってください）
```json
{{
  "overall_risk": "high または medium または low",
  "risk_factors": [
    {{
      "factor": "リスク要因",
      "severity": "high または medium または low",
      "affected_processes": ["影響を受ける工程名"],
      "evidence": "このリスクを判断した根拠"
    }}
  ],
  "delay_forecast": {{
    "likely_delay_days": 0,
    "confidence": "high または medium または low",
    "most_critical_process": "最もリスクの高い工程名"
  }},
  "mitigation_actions": [
    {{
      "action": "対策アクション",
      "target_process": "対象工程",
      "priority": "high または medium または low"
    }}
  ]
}}
```"""

    return prompt
