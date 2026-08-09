"""原価管理のビジネスロジック。

日報承認時の労務費生成、発注検収時の材料費生成、
予算消化率の集計、アラートチェックを担う。
将来の DRF API 移行時にもそのまま使える。
"""

from django.db.models import Sum

from apps.costs.models import BudgetItem, CostTransaction
from apps.masters.models import CostCategory


def create_labor_cost_from_report(daily_report):
    """日報承認時に労務費の CostTransaction を生成する。

    金額 = work_hours × Worker.hourly_cost
    """
    labor = CostCategory.objects.get(code="labor")
    amount = daily_report.work_hours * daily_report.worker.hourly_cost
    return CostTransaction.unscoped.create(
        company=daily_report.company,
        site=daily_report.site,
        work_type=daily_report.work_type,
        cost_category=labor,
        amount=amount,
        transaction_date=daily_report.report_date,
        source_type=CostTransaction.SourceType.DAILY_REPORT,
        source_id=daily_report.pk,
        manhours=daily_report.work_hours,
    )


def create_material_cost_from_po_item(po_item):
    """発注明細の検収時に材料費の CostTransaction を生成する。

    金額 = quantity × unit_price
    """
    material_cat = CostCategory.objects.get(code="material")
    amount = po_item.quantity * po_item.unit_price
    return CostTransaction.unscoped.create(
        company=po_item.purchase_order.company,
        site=po_item.purchase_order.site,
        work_type=po_item.work_type,
        cost_category=material_cat,
        amount=amount,
        transaction_date=po_item.purchase_order.order_date,
        source_type=CostTransaction.SourceType.PO_ITEM,
        source_id=po_item.pk,
        supplier=po_item.purchase_order.supplier,
    )


def create_reversal(original_tx, reason=""):
    """逆仕訳を生成する。原価データの訂正に使用。"""
    return CostTransaction.unscoped.create(
        company=original_tx.company,
        site=original_tx.site,
        work_type=original_tx.work_type,
        cost_category=original_tx.cost_category,
        amount=-original_tx.amount,
        transaction_date=original_tx.transaction_date,
        source_type=CostTransaction.SourceType.REVERSAL,
        source_id=original_tx.pk,
        supplier=original_tx.supplier,
        manhours=(
            -original_tx.manhours
            if original_tx.manhours
            else None
        ),
    )


def get_site_cost_summary(site):
    """現場の予算vs実績サマリを取得する。

    Returns:
        {
            "budget_total": 予算合計,
            "cost_total": 実績合計,
            "consumption_pct": 消化率(%),
            "gross_profit": 粗利,
            "margin_rate": 粗利率(%),
            "by_category": [
                {"category": "材料費", "budget": X, "actual": Y, "pct": Z},
                ...
            ],
        }
    """
    budget_total = (
        BudgetItem.unscoped.filter(site=site)
        .aggregate(t=Sum("amount"))["t"]
        or 0
    )
    cost_total = (
        CostTransaction.unscoped.filter(site=site)
        .aggregate(t=Sum("amount"))["t"]
        or 0
    )

    consumption_pct = int(cost_total / budget_total * 100) if budget_total else 0
    gross_profit = site.contract_amount - cost_total
    margin_rate = (
        round(float(gross_profit / site.contract_amount * 100), 1)
        if site.contract_amount
        else None
    )

    # 区分別集計
    by_category = []
    budget_by_cat = (
        BudgetItem.unscoped.filter(site=site)
        .values("cost_category__name", "cost_category__code")
        .annotate(total=Sum("amount"))
    )
    budget_map = {r["cost_category__code"]: r for r in budget_by_cat}

    actual_by_cat = (
        CostTransaction.unscoped.filter(site=site)
        .values("cost_category__name", "cost_category__code")
        .annotate(total=Sum("amount"))
    )
    actual_map = {r["cost_category__code"]: r for r in actual_by_cat}

    all_codes = set(budget_map.keys()) | set(actual_map.keys())
    for code in sorted(all_codes):
        b = budget_map.get(code, {})
        a = actual_map.get(code, {})
        budget_amt = b.get("total", 0) or 0
        actual_amt = a.get("total", 0) or 0
        pct = int(actual_amt / budget_amt * 100) if budget_amt else 0
        cat_name = b.get("cost_category__name") or a.get("cost_category__name", code)
        by_category.append({
            "code": code,
            "category": cat_name,
            "budget": budget_amt,
            "actual": actual_amt,
            "pct": pct,
        })

    return {
        "budget_total": budget_total,
        "cost_total": cost_total,
        "consumption_pct": consumption_pct,
        "gross_profit": gross_profit,
        "margin_rate": margin_rate,
        "by_category": by_category,
    }


def get_monthly_cost_trend(site, months=6):
    """現場の月別費用推移データを取得する（Chart.js用）。

    Returns:
        {
            "labels": ["2026-03", "2026-04", ...],
            "datasets": [
                {"label": "材料費", "data": [100, 200, ...]},
                {"label": "労務費", "data": [300, 400, ...]},
                ...
            ],
        }
    """
    from datetime import date, timedelta

    from django.db.models.functions import TruncMonth

    # 直近N ヶ月
    today = date.today()
    start_date = today.replace(day=1) - timedelta(days=30 * (months - 1))

    txs = (
        CostTransaction.unscoped.filter(
            site=site,
            transaction_date__gte=start_date,
        )
        .annotate(month=TruncMonth("transaction_date"))
        .values("month", "cost_category__name")
        .annotate(total=Sum("amount"))
        .order_by("month")
    )

    # ラベルとデータセットの組み立て
    labels_set = set()
    categories = {}
    for tx in txs:
        label = tx["month"].strftime("%Y-%m")
        labels_set.add(label)
        cat = tx["cost_category__name"]
        if cat not in categories:
            categories[cat] = {}
        categories[cat][label] = float(tx["total"])

    labels = sorted(labels_set)
    datasets = []
    for cat_name, monthly_data in categories.items():
        datasets.append({
            "label": cat_name,
            "data": [monthly_data.get(month, 0) for month in labels],
        })

    return {"labels": labels, "datasets": datasets}
