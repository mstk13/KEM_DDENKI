"""データ収集サービス。

PostgreSQLから原価・工程・日報データを収集し、
ML学習やLLMプロンプト構築に使える構造化データを返す。
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Avg, Count, F, Q, Sum
from django.db.models.functions import TruncMonth

from apps.costs.models import BudgetItem, CostTransaction
from apps.reports.models import DailyReport
from apps.schedules.models import Phase, PhaseTemplate, PhaseTemplateItem
from apps.sites.models import Process, Site


def _decimal_to_float(value):
    """Decimal → float 変換（JSON化用）。"""
    if isinstance(value, Decimal):
        return float(value)
    return value


def collect_site_cost_features(site):
    """現場のコスト予測用特徴量を収集する。

    LightGBM等のML予測モデルへの入力として使う。

    Returns:
        dict: 特徴量の辞書。キーは特徴量名、値は数値。
    """
    today = date.today()

    # 予算集計
    budget_qs = BudgetItem.unscoped.filter(site=site)
    budget_total = budget_qs.aggregate(t=Sum("amount"))["t"] or Decimal("0")
    budget_count = budget_qs.count()

    # 実績集計
    cost_qs = CostTransaction.unscoped.filter(site=site)
    cost_total = cost_qs.aggregate(t=Sum("amount"))["t"] or Decimal("0")
    cost_count = cost_qs.count()

    # 工期情報
    duration_days = 0
    elapsed_days = 0
    elapsed_ratio = 0.0
    if site.start_date and site.end_date:
        duration_days = (site.end_date - site.start_date).days
        elapsed_days = min((today - site.start_date).days, duration_days)
        elapsed_ratio = elapsed_days / duration_days if duration_days > 0 else 0.0

    # 消化率
    consumption_ratio = (
        float(cost_total / budget_total) if budget_total > 0 else 0.0
    )

    # 消化ペース（日あたり消化額）
    daily_burn = (
        float(cost_total / elapsed_days) if elapsed_days > 0 else 0.0
    )

    # 直近7日の消化額
    recent_cost = cost_qs.filter(
        transaction_date__gte=today - timedelta(days=7),
    ).aggregate(t=Sum("amount"))["t"] or Decimal("0")
    recent_daily_burn = float(recent_cost) / 7

    # 原価区分別の実績比率
    category_breakdown = (
        cost_qs.values("cost_category__code")
        .annotate(total=Sum("amount"))
    )
    category_ratios = {}
    for row in category_breakdown:
        code = row["cost_category__code"]
        ratio = float(row["total"] / cost_total) if cost_total > 0 else 0.0
        category_ratios[f"ratio_{code}"] = ratio

    # 日報データ（労務関連）
    report_qs = DailyReport.unscoped.filter(site=site, status="approved")
    report_agg = report_qs.aggregate(
        total_hours=Sum("work_hours"),
        total_overtime=Sum("overtime_hours"),
        worker_count=Count("worker", distinct=True),
        report_count=Count("id"),
    )

    overtime_ratio = 0.0
    total_hours = report_agg["total_hours"] or Decimal("0")
    total_overtime = report_agg["total_overtime"] or Decimal("0")
    if total_hours > 0:
        overtime_ratio = float(total_overtime / total_hours)

    # 工程遅延
    processes = Process.unscoped.filter(site=site)
    process_count = processes.count()
    delayed_count = processes.filter(status=Process.Status.DELAYED).count()
    delay_ratio = delayed_count / process_count if process_count > 0 else 0.0

    features = {
        # 基本情報
        "contract_amount": _decimal_to_float(site.contract_amount),
        "duration_days": duration_days,
        "elapsed_days": elapsed_days,
        "elapsed_ratio": elapsed_ratio,
        # 予算
        "budget_total": _decimal_to_float(budget_total),
        "budget_item_count": budget_count,
        # 実績
        "cost_total": _decimal_to_float(cost_total),
        "cost_transaction_count": cost_count,
        "consumption_ratio": consumption_ratio,
        # 消化ペース
        "daily_burn": daily_burn,
        "recent_daily_burn": recent_daily_burn,
        "burn_acceleration": (
            recent_daily_burn / daily_burn if daily_burn > 0 else 1.0
        ),
        # 労務
        "total_work_hours": _decimal_to_float(total_hours),
        "overtime_ratio": overtime_ratio,
        "worker_count": report_agg["worker_count"] or 0,
        "report_count": report_agg["report_count"] or 0,
        # 工程
        "process_count": process_count,
        "delay_ratio": delay_ratio,
        # 原価区分比率
        **category_ratios,
    }

    return features


def collect_site_summary(site):
    """現場の概要データを収集する。LLMプロンプト構築用。

    ML向けの数値特徴量ではなく、人間/LLMが読める形式。

    Returns:
        dict: 現場情報・予算実績・工程・日報の概要。
    """
    features = collect_site_cost_features(site)

    # 予算vs実績（区分別）
    budget_by_cat = (
        BudgetItem.unscoped.filter(site=site)
        .values("cost_category__name", "cost_category__code")
        .annotate(total=Sum("amount"))
    )
    actual_by_cat = (
        CostTransaction.unscoped.filter(site=site)
        .values("cost_category__name", "cost_category__code")
        .annotate(total=Sum("amount"))
    )
    budget_map = {r["cost_category__code"]: r for r in budget_by_cat}
    actual_map = {r["cost_category__code"]: r for r in actual_by_cat}

    categories = []
    for code in sorted(set(budget_map) | set(actual_map)):
        b = budget_map.get(code, {})
        a = actual_map.get(code, {})
        budget_amt = b.get("total", 0) or 0
        actual_amt = a.get("total", 0) or 0
        categories.append({
            "name": b.get("cost_category__name")
            or a.get("cost_category__name", code),
            "budget": _decimal_to_float(budget_amt),
            "actual": _decimal_to_float(actual_amt),
            "consumption_pct": (
                round(float(actual_amt / budget_amt * 100), 1)
                if budget_amt
                else None
            ),
        })

    # 月別消化トレンド（直近6ヶ月）
    six_months_ago = date.today() - timedelta(days=180)
    monthly_trend = list(
        CostTransaction.unscoped.filter(
            site=site,
            transaction_date__gte=six_months_ago,
        )
        .annotate(month=TruncMonth("transaction_date"))
        .values("month")
        .annotate(total=Sum("amount"))
        .order_by("month")
    )
    trend = [
        {
            "month": row["month"].strftime("%Y-%m"),
            "amount": _decimal_to_float(row["total"]),
        }
        for row in monthly_trend
    ]

    # 工程一覧
    processes = list(
        Process.unscoped.filter(site=site)
        .values(
            "name",
            "work_type__name",
            "planned_start",
            "planned_end",
            "actual_start",
            "actual_end",
            "status",
        )
        .order_by("display_order")
    )
    for p in processes:
        for key in ("planned_start", "planned_end", "actual_start", "actual_end"):
            if p[key]:
                p[key] = p[key].isoformat()

    return {
        "site": {
            "name": site.name,
            "code": site.code,
            "status": site.get_status_display(),
            "contract_amount": _decimal_to_float(site.contract_amount),
            "start_date": site.start_date.isoformat() if site.start_date else None,
            "end_date": site.end_date.isoformat() if site.end_date else None,
            "customer": str(site.customer) if site.customer else None,
        },
        "cost_features": features,
        "budget_vs_actual": categories,
        "monthly_trend": trend,
        "processes": processes,
    }


def find_similar_completed_sites(site, limit=5):
    """類似の完工済み現場を検索する。

    受注金額の規模と工種の一致度で類似度を判定する。

    Returns:
        list[dict]: 類似現場のサマリ一覧。
    """
    completed_sites = Site.unscoped.filter(
        company=site.company,
        status__in=[Site.Status.COMPLETED, Site.Status.BILLED],
    ).exclude(pk=site.pk)

    if not completed_sites.exists():
        return []

    # 工種の一致でフィルタ
    site_work_types = set(site.work_types.values_list("pk", flat=True))
    if site_work_types:
        completed_sites = completed_sites.filter(
            work_types__pk__in=site_work_types,
        ).distinct()

    # 受注金額で近い順にソート
    contract = site.contract_amount or 0
    results = []
    for s in completed_sites:
        budget_total = (
            BudgetItem.unscoped.filter(site=s)
            .aggregate(t=Sum("amount"))["t"]
            or 0
        )
        cost_total = (
            CostTransaction.unscoped.filter(site=s)
            .aggregate(t=Sum("amount"))["t"]
            or 0
        )
        duration = (
            (s.end_date - s.start_date).days
            if s.start_date and s.end_date
            else 0
        )

        # 類似度スコア（受注金額の差が小さいほど高い）
        amount_diff = abs(float(s.contract_amount or 0) - float(contract))
        score = 1 / (1 + amount_diff / max(float(contract), 1))

        results.append({
            "site_name": s.name,
            "contract_amount": _decimal_to_float(s.contract_amount),
            "budget_total": _decimal_to_float(budget_total),
            "cost_total": _decimal_to_float(cost_total),
            "final_consumption_pct": (
                round(float(cost_total / budget_total * 100), 1)
                if budget_total
                else None
            ),
            "gross_profit": _decimal_to_float(
                s.contract_amount - cost_total
            ),
            "duration_days": duration,
            "similarity_score": round(score, 3),
        })

    results.sort(key=lambda x: x["similarity_score"], reverse=True)
    return results[:limit]


def collect_schedule_data(site):
    """工程提案用のデータを収集する。

    Returns:
        dict: 現場の工程データ + テンプレート一覧。
    """
    # 現場の工程フェーズ
    phases = list(
        Phase.unscoped.filter(site=site)
        .values("name", "start_date", "end_date", "progress", "color", "memo")
        .order_by("sort_order")
    )
    for p in phases:
        for key in ("start_date", "end_date"):
            if p[key]:
                p[key] = p[key].isoformat()

    # 工程テンプレート一覧
    templates = []
    for tmpl in PhaseTemplate.unscoped.filter(company=site.company):
        items = list(
            PhaseTemplateItem.unscoped.filter(template=tmpl)
            .values("name", "offset_days_start", "offset_days_end", "sort_order")
            .order_by("sort_order")
        )
        templates.append({
            "template_name": tmpl.name,
            "description": tmpl.description,
            "items": items,
        })

    # 類似現場の実績工程（計画vs実績の乖離パターン）
    similar_sites = find_similar_completed_sites(site, limit=3)
    similar_processes = []
    for ss in similar_sites:
        s = Site.unscoped.filter(
            company=site.company, name=ss["site_name"],
        ).first()
        if not s:
            continue
        procs = list(
            Process.unscoped.filter(site=s)
            .values(
                "name", "work_type__name",
                "planned_start", "planned_end",
                "actual_start", "actual_end",
                "status",
            )
            .order_by("display_order")
        )
        for p in procs:
            for key in ("planned_start", "planned_end", "actual_start", "actual_end"):
                if p[key]:
                    p[key] = p[key].isoformat()
        similar_processes.append({
            "site_name": ss["site_name"],
            "duration_days": ss["duration_days"],
            "processes": procs,
        })

    work_type_names = list(
        site.work_types.values_list("name", flat=True)
    )

    return {
        "site": {
            "name": site.name,
            "work_types": work_type_names,
            "contract_amount": _decimal_to_float(site.contract_amount),
            "start_date": site.start_date.isoformat() if site.start_date else None,
            "end_date": site.end_date.isoformat() if site.end_date else None,
        },
        "current_phases": phases,
        "templates": templates,
        "similar_site_processes": similar_processes,
    }
