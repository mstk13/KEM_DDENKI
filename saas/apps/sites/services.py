"""現場管理のビジネスロジック。

現場の集計・ステータス管理を担う。
将来の DRF API 移行時にもそのまま使える。
"""

from django.db.models import Avg, Sum

from apps.costs.models import BudgetItem, CostTransaction
from apps.masters.models import Customer
from apps.sites.importer import normalize_company_name


def find_customer_by_name(company, raw_name):
    """見積書の宛名から得意先マスタを引き当てる。見つからなければ None。

    「株式会社ABC」「(株)ABC」「㈱ ABC」を同じものとして扱う。
    自動作成はしない — 表記ゆれで重複マスタが増えるほうが後で困るため、
    未登録なら確認画面で人に選んでもらう。
    """
    if not raw_name:
        return None

    key = normalize_company_name(raw_name)
    if not key:
        return None

    # unscoped: テナントコンテキスト未設定の取り込み経路からも使うため、
    # company を明示して絞る。
    for customer in Customer.unscoped.filter(company=company, is_active=True):
        if normalize_company_name(customer.name) == key:
            return customer
    return None


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
