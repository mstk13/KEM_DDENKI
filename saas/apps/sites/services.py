"""現場管理のビジネスロジック。

現場の集計・ステータス管理を担う。
将来の DRF API 移行時にもそのまま使える。
"""

from django.db.models import Avg, Sum

from apps.costs.models import BudgetItem, CostTransaction


def get_site_summary(site):
    """現場のサマリ情報を取得する。"""
    total_cost = (
        CostTransaction.unscoped.filter(site=site)
        .aggregate(t=Sum("amount"))["t"]
        or 0
    )
    budget_total = (
        BudgetItem.unscoped.filter(site=site)
        .aggregate(t=Sum("amount"))["t"]
        or 0
    )
    gross_profit = site.contract_amount - total_cost
    margin_rate = (
        round(float(gross_profit / site.contract_amount * 100), 1)
        if site.contract_amount
        else None
    )
    phase_progress = (
        site.phases.aggregate(avg=Avg("progress"))["avg"] or 0
    )

    return {
        "total_cost": total_cost,
        "budget_total": budget_total,
        "gross_profit": gross_profit,
        "margin_rate": margin_rate,
        "phase_progress": int(phase_progress),
        "worker_count": site.assignments.values("worker").distinct().count(),
        "report_count": site.daily_reports.count(),
    }
