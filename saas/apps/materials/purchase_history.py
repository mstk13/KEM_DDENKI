"""材料別の取引履歴（ADR-0034）。

発注明細（PurchaseOrderItem）を土台に材料ごとにまとめ、検収が済んだ分は
調達実績（ProcurementRecord）から納品日と実リードタイムを足す。
「この材料をいつ・どこから・いくらで買ったか」を材料・仕入先・現場・期間で引く。
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import F, Q

from apps.materials.models import ProcurementRecord, PurchaseOrder, PurchaseOrderItem
from apps.materials.services import normalize_material_name

# 1回の検索で読む発注明細の上限。超えた分は読まずに truncated で知らせる。
TRANSACTION_LIMIT = 500

# 過去の取引に含めない発注の状態。
# - 下書き: まだ発注していない。数量も単価も確定前なので相場に混ぜられない
# - 取消: 取引が成立していない。残すと最安・最高単価が実在しない値でぶれる
EXCLUDED_STATUSES = (PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.CANCELLED)

UNNAMED_MATERIAL = "（材料名なし）"


@dataclass
class PurchaseTransaction:
    """発注明細1行ぶんの取引。納品日・リードタイムは調達実績があるときだけ入る。"""

    item_id: int
    purchase_order_id: int
    order_date: date
    supplier_id: int
    supplier_name: str
    site_id: int
    site_name: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    amount: Decimal
    status: str
    status_label: str
    delivered_date: date | None = None
    lead_days: int | None = None


@dataclass
class MaterialHistory:
    """材料1つぶんの取引（発注日の新しい順）と集計。

    material_id が None のものは材料マスタに無い自由入力の明細で、
    表記ゆれを潰した名前（normalize_material_name）でまとめている。
    """

    material_id: int | None
    code: str
    name: str
    transactions: list[PurchaseTransaction] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.transactions)

    @property
    def last_order_date(self) -> date:
        return self.transactions[0].order_date

    @property
    def latest_unit_price(self) -> Decimal:
        """最終発注日（last_order_date）の単価。"""
        return self.transactions[0].unit_price

    @property
    def min_unit_price(self) -> Decimal:
        return min(t.unit_price for t in self.transactions)

    @property
    def max_unit_price(self) -> Decimal:
        return max(t.unit_price for t in self.transactions)

    @property
    def supplier_count(self) -> int:
        return len({t.supplier_id for t in self.transactions})

    @property
    def total_quantities(self) -> list[tuple[str, Decimal]]:
        """単位ごとの合計数量。単位の違う数量は足せないので分けて返す。"""
        totals: dict[str, Decimal] = {}
        for t in self.transactions:
            totals[t.unit] = totals.get(t.unit, Decimal("0")) + t.quantity
        return list(totals.items())


@dataclass
class PurchaseHistory:
    """検索結果。materials は最終発注日の新しい順。"""

    materials: list[MaterialHistory]
    transaction_count: int
    truncated: bool
    limit: int


def search_purchase_history(
    company,
    *,
    q: str = "",
    supplier_id: int | None = None,
    site_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int | None = None,
) -> PurchaseHistory:
    """発注明細を材料ごとにまとめて返す。

    q は空白区切りの全語を含むものに絞る（材料名・材料コード、マスタ未登録の
    明細は自由入力の材料名）。期間は発注日で見る。集計は読み込んだ明細
    （最大 limit 件）の範囲で行う。
    """
    limit = TRANSACTION_LIMIT if limit is None else limit

    # unscoped: シェルやテストなどテナントコンテキストの無い呼び出しでも
    # 他社の明細が混ざらないよう、company を明示して絞る。
    items = (
        PurchaseOrderItem.unscoped.filter(company=company)
        .exclude(purchase_order__status__in=EXCLUDED_STATUSES)
        .select_related("purchase_order__supplier", "purchase_order__site", "material")
    )
    for term in (q or "").split():
        items = items.filter(
            Q(material__name__icontains=term)
            | Q(material__code__icontains=term)
            | Q(material__isnull=True, material_name__icontains=term)
        )
    if supplier_id is not None:
        items = items.filter(purchase_order__supplier_id=supplier_id)
    if site_id is not None:
        items = items.filter(purchase_order__site_id=site_id)
    if date_from is not None:
        items = items.filter(purchase_order__order_date__gte=date_from)
    if date_to is not None:
        items = items.filter(purchase_order__order_date__lte=date_to)

    rows = list(
        items.order_by("-purchase_order__order_date", "-purchase_order_id", "pk")[: limit + 1]
    )
    truncated = len(rows) > limit
    rows = rows[:limit]

    procurement = _procurement_by_order_and_material(company, rows)
    groups: dict[tuple, MaterialHistory] = {}
    for item in rows:
        po = item.purchase_order
        if item.material_id:
            key = ("material", item.material_id)
        else:
            key = ("text", normalize_material_name(item.material_name))
        group = groups.get(key)
        if group is None:
            group = _new_group(item)
            groups[key] = group

        record = procurement.get((po.pk, item.material_id)) if item.material_id else None
        unit = item.unit or (item.material.unit if item.material else "")
        group.transactions.append(PurchaseTransaction(
            item_id=item.pk,
            purchase_order_id=po.pk,
            order_date=po.order_date,
            supplier_id=po.supplier_id,
            supplier_name=po.supplier.name,
            site_id=po.site_id,
            site_name=po.site.name,
            quantity=item.quantity,
            unit=unit,
            unit_price=item.unit_price,
            amount=item.quantity * item.unit_price,
            status=po.status,
            status_label=po.get_status_display(),
            delivered_date=record.delivered_date if record else None,
            lead_days=record.actual_lead_days if record else None,
        ))

    return PurchaseHistory(
        materials=list(groups.values()),
        transaction_count=len(rows),
        truncated=truncated,
        limit=limit,
    )


def _new_group(item) -> MaterialHistory:
    if item.material_id:
        return MaterialHistory(
            material_id=item.material_id, code=item.material.code, name=item.material.name,
        )
    return MaterialHistory(
        material_id=None, code="", name=item.material_name.strip() or UNNAMED_MATERIAL,
    )


def _procurement_by_order_and_material(company, rows) -> dict[tuple[int, int], ProcurementRecord]:
    """(発注書ID, 材料ID) → 調達実績。1クエリで読んで Python で引き当てる。

    調達実績は検収時に材料マスタのある明細だけ作られるので、自由入力の明細は対象外。
    同じ組に複数あれば納品日の新しいもの（納品日なしより納品日ありを優先）を採る。
    """
    po_ids = {item.purchase_order_id for item in rows if item.material_id}
    if not po_ids:
        return {}
    # unscoped: 呼び出し元と同じく company を明示して絞る。
    records = ProcurementRecord.unscoped.filter(
        company=company, purchase_order_id__in=po_ids,
    ).order_by(F("delivered_date").asc(nulls_first=True), "pk")
    return {(r.purchase_order_id, r.material_id): r for r in records}


def copy_item_to_order(source, purchase_order, *, created_by=None) -> PurchaseOrderItem:
    """過去の発注明細を、新しい発注書の明細としてコピーする。

    取引履歴の「同じ材料で発注」から使う。材料・材料名・数量・単位・単価・税率・工種を
    そのまま写し、発注書の合計を数え直す。数量や単価は作成後の発注書で直してもらう前提。
    別の会社の明細を渡されたら ValueError（呼び出し側で自社の明細に絞っておくこと）。
    """
    if source.company_id != purchase_order.company_id:
        raise ValueError("別の会社の発注明細はコピーできません")

    # unscoped: company を発注書から明示して作る。
    item = PurchaseOrderItem.unscoped.create(
        company=purchase_order.company,
        purchase_order=purchase_order,
        material=source.material,
        material_name=source.material_name,
        quantity=source.quantity,
        unit=source.unit,
        unit_price=source.unit_price,
        tax_rate=source.tax_rate,
        work_type=source.work_type,
        created_by=created_by,
    )
    purchase_order.recalculate_total()
    return item
