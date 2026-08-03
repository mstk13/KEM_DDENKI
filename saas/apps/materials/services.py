"""材料管理のビジネスロジック。

見積比較、納品検収、在庫更新、消化率集計を担う。
将来の DRF API 移行時にもそのまま使える。
"""

from django.db.models import Sum
from django.utils import timezone

from apps.costs.services import create_material_cost_from_po_item
from apps.materials.models import (
    Delivery,
    Inventory,
    PurchaseOrder,
    Quotation,
    QuotationItem,
)


def compare_quotations(material_id, site_id=None):
    """同一材料の複数仕入先の見積を比較する。

    Returns:
        [{
            "supplier": Supplier,
            "unit_price": Decimal,
            "quantity": Decimal,
            "amount": Decimal,
            "quotation": Quotation,
        }, ...]
        ※ unit_price 昇順でソート
    """
    qs = QuotationItem.unscoped.filter(
        material_id=material_id,
        quotation__status__in=["received", "accepted"],
    ).select_related("quotation", "quotation__supplier")

    if site_id:
        qs = qs.filter(quotation__site_id=site_id)

    results = []
    for item in qs:
        results.append({
            "supplier": item.quotation.supplier,
            "unit_price": item.unit_price,
            "quantity": item.quantity,
            "amount": item.amount,
            "quotation": item.quotation,
        })

    return sorted(results, key=lambda x: x["unit_price"])


def inspect_delivery(delivery, inspected_by):
    """納品を検収する。在庫更新と原価計上を行う。"""
    delivery.inspected = True
    delivery.inspected_by = inspected_by
    delivery.inspected_at = timezone.now()
    delivery.save()

    # 在庫を更新
    for item in delivery.items.all():
        inv, _ = Inventory.unscoped.get_or_create(
            company=delivery.company,
            material=item.material,
            site=delivery.purchase_order.site,
            defaults={"quantity": 0},
        )
        inv.quantity += item.delivered_qty
        inv.save()

    # 発注書の原価計上（まだ計上されていない明細のみ）
    po = delivery.purchase_order
    for po_item in po.items.all():
        create_material_cost_from_po_item(po_item)

    # 発注ステータス更新
    _update_po_status(po)


def _update_po_status(po):
    """納品状況から発注ステータスを更新する。"""
    total_ordered = po.items.aggregate(t=Sum("quantity"))["t"] or 0
    total_delivered = sum(
        d.items.aggregate(t=Sum("delivered_qty"))["t"] or 0
        for d in po.deliveries.all()
    )

    if total_delivered >= total_ordered:
        po.status = PurchaseOrder.Status.RECEIVED
    elif total_delivered > 0:
        po.status = PurchaseOrder.Status.PARTIALLY_RECEIVED
    po.save(update_fields=["status"])


def get_site_material_consumption(site):
    """現場の材料消化率を取得する。

    Returns:
        [{
            "material": Material,
            "budget_qty": Decimal,
            "used_qty": Decimal,
            "pct": int,
        }, ...]
    """
    from apps.reports.models import DailyReportMaterial

    # 発注数量 = 予算として扱う
    ordered = (
        site.purchase_orders
        .filter(status__in=["ordered", "partially_received", "received"])
        .values("items__material__name", "items__material_id")
        .annotate(total=Sum("items__quantity"))
    )
    ordered_map = {r["items__material_id"]: r for r in ordered}

    # 使用数量 = 日報から集計
    used = (
        DailyReportMaterial.unscoped
        .filter(daily_report__site=site, material__isnull=False)
        .values("material__name", "material_id")
        .annotate(total=Sum("quantity_used"))
    )
    used_map = {r["material_id"]: r for r in used}

    all_ids = set(ordered_map.keys()) | set(used_map.keys())
    results = []
    for mid in all_ids:
        o = ordered_map.get(mid, {})
        u = used_map.get(mid, {})
        budget_qty = o.get("total", 0) or 0
        used_qty = u.get("total", 0) or 0
        pct = int((used_qty / budget_qty * 100)) if budget_qty else 0
        name = o.get("items__material__name") or u.get("material__name", "")
        results.append({
            "material_name": name,
            "budget_qty": budget_qty,
            "used_qty": used_qty,
            "pct": pct,
        })

    return sorted(results, key=lambda x: -x["pct"])
