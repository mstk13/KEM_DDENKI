"""M4 テスト: 材料・受発注の越境テスト + 材料費自動仕訳。"""

from decimal import Decimal

import pytest

from apps.core.tenant_context import set_current_company
from apps.costs.models import CostTransaction
from apps.costs.services import create_material_cost_from_po_item
from apps.masters.models import CostCategory, Supplier, WorkType
from apps.materials.models import Material, PurchaseOrder, PurchaseOrderItem
from apps.sites.models import Site


@pytest.fixture
def cost_categories(db):
    cats = {}
    for code, name, order in [
        ("material", "材料費", 1),
        ("labor", "労務費", 2),
        ("outsourcing", "外注費", 3),
        ("expense", "経費", 4),
    ]:
        cats[code], _ = CostCategory.objects.get_or_create(
            code=code, defaults={"name": name, "display_order": order},
        )
    return cats


@pytest.mark.django_db
class TestMaterialIsolation:
    def test_material_isolation(self, company_a, company_b):
        Material.unscoped.create(company=company_a, code="M01", name="VVFケーブル", unit="m")
        Material.unscoped.create(company=company_b, code="M01", name="石膏ボード", unit="枚")

        set_current_company(company_a)
        assert Material.objects.count() == 1
        assert Material.objects.first().name == "VVFケーブル"

        set_current_company(company_b)
        assert Material.objects.count() == 1
        assert Material.objects.first().name == "石膏ボード"

        set_current_company(None)

    def test_purchase_order_isolation(self, company_a, company_b):
        site_a = Site.unscoped.create(company=company_a, code="S01", name="A現場")
        site_b = Site.unscoped.create(company=company_b, code="S01", name="B現場")
        sup_a = Supplier.unscoped.create(company=company_a, code="SP1", name="A社仕入先")
        sup_b = Supplier.unscoped.create(company=company_b, code="SP1", name="B社仕入先")

        PurchaseOrder.unscoped.create(
            company=company_a, site=site_a, supplier=sup_a, order_date="2026-08-01",
        )
        PurchaseOrder.unscoped.create(
            company=company_b, site=site_b, supplier=sup_b, order_date="2026-08-01",
        )

        set_current_company(company_a)
        assert PurchaseOrder.objects.count() == 1

        set_current_company(company_b)
        assert PurchaseOrder.objects.count() == 1

        set_current_company(None)


@pytest.mark.django_db
class TestMaterialCostJournal:
    def test_material_cost_from_po_item(self, company_a, cost_categories):
        wt = WorkType.unscoped.create(company=company_a, code="E01", name="電気幹線")
        site = Site.unscoped.create(company=company_a, code="S01", name="A現場")
        sup = Supplier.unscoped.create(company=company_a, code="SP1", name="仕入先A")
        mat = Material.unscoped.create(company=company_a, code="M01", name="ケーブル", unit="m")

        po = PurchaseOrder.unscoped.create(
            company=company_a, site=site, supplier=sup,
            order_date="2026-08-01", status=PurchaseOrder.Status.RECEIVED,
        )
        po_item = PurchaseOrderItem.unscoped.create(
            company=company_a, purchase_order=po, material=mat,
            quantity=Decimal("100"), unit_price=Decimal("500"), work_type=wt,
        )

        tx = create_material_cost_from_po_item(po_item)

        assert tx.amount == Decimal("50000")  # 100 × 500
        assert tx.cost_category.code == "material"
        assert tx.source_type == CostTransaction.SourceType.PO_ITEM
        assert tx.source_id == po_item.pk
        assert tx.supplier == sup
