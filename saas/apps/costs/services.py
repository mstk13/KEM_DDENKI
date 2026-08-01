"""原価の自動仕訳サービス。

日報承認時の労務費生成、発注検収時の材料費生成を担う。
"""


from apps.costs.models import CostTransaction
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
