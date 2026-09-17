"""現場詳細の「材料の受発注」の項目を、材料・発注の一覧と揃える。

同じ発注書を、現場詳細から見たときと発注一覧（materials:po_list）から見たときで
出ている項目が違っていた。現場詳細側には**発注者**が無く、金額の書式も違っていた。
同じものを2か所で見て別物に見えるのを止めるため、現場詳細側を発注一覧に合わせる。

揃えないものは2つある。どちらも「混在表だから」と「現場詳細のほうが正しいから」:

1. **区分**と**日付** — 現場詳細は発注と見積を1つの表に混ぜている。発注一覧は
   「発注日」、見積一覧は「見積日」だが、1列に両方を出すため「日付」のままにする
2. **仕入先** — 見積行は `counterparty_name` を使う。自社発行の見積は `supplier` が
   空で相手先は `customer` 側に入るため、`supplier` をそのまま出すと空欄になる
   （発注一覧・見積一覧に揃えるとかえって出なくなる）

**現場**の列は出さない。現場詳細では全行がその現場のため。
"""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.tenant_context import set_current_company
from apps.masters.models import Customer, Supplier
from apps.materials.models import PurchaseOrder, Quotation
from apps.sites.models import Site

DAY = datetime.date(2026, 9, 17)


@pytest.fixture
def logged_in(client, company_a, user_a):
    set_current_company(company_a)
    client.force_login(user_a)
    yield client
    set_current_company(None)


@pytest.fixture
def site(company_a):
    return Site.unscoped.create(company=company_a, code="S001", name="A社ビル新築")


@pytest.fixture
def supplier(company_a):
    return Supplier.unscoped.create(company=company_a, code="SUP1", name="中央電材")


def _body(client, site):
    return client.get(reverse("sites:detail", args=[site.pk])).content.decode()


@pytest.mark.django_db
class TestColumnsMatchThePurchaseOrderList:
    def test_発注者の列が出る(self, logged_in, company_a, user_a, site, supplier):
        PurchaseOrder.unscoped.create(
            company=company_a, site=site, supplier=supplier, order_date=DAY,
            ordered_by=user_a, total_amount=Decimal("120000"),
        )

        body = _body(logged_in, site)

        assert "<th>発注者</th>" in body
        assert str(user_a) in body

    def test_発注者が未設定なら発注一覧と同じダッシュを出す(
        self, logged_in, company_a, site, supplier,
    ):
        PurchaseOrder.unscoped.create(
            company=company_a, site=site, supplier=supplier, order_date=DAY,
            total_amount=Decimal("120000"),
        )

        assert "—" in _body(logged_in, site)

    def test_金額は発注一覧と同じ書式で出す(self, logged_in, company_a, site, supplier):
        PurchaseOrder.unscoped.create(
            company=company_a, site=site, supplier=supplier, order_date=DAY,
            total_amount=Decimal("120000"),
        )

        body = _body(logged_in, site)

        assert "合計金額" in body
        assert "¥120000" in body
        # 旧書式（「120000 円」・見出し「金額」）は残さない
        assert "120000 円" not in body

    def test_状態はバッジで出す(self, logged_in, company_a, site, supplier):
        po = PurchaseOrder.unscoped.create(
            company=company_a, site=site, supplier=supplier, order_date=DAY,
            total_amount=Decimal("120000"),
        )

        body = _body(logged_in, site)

        assert f'<span class="badge badge-gray">{po.get_status_display()}</span>' in body


@pytest.mark.django_db
class TestQuotationRowsKeepWhatIsCorrectHere:
    def test_自社発行の見積は顧客名を相手先に出す(self, logged_in, company_a, site):
        customer = Customer.unscoped.create(company=company_a, code="C1", name="株式会社甲")
        Quotation.unscoped.create(
            company=company_a, site=site, kind=Quotation.Kind.ISSUED,
            customer=customer, quotation_date=DAY, total_amount=Decimal("80000"),
        )

        body = _body(logged_in, site)

        # supplier をそのまま出す作りに揃えると、ここが空欄になる
        assert "株式会社甲" in body

    def test_仕入先から受領した見積は仕入先名を出す(
        self, logged_in, company_a, site, supplier,
    ):
        Quotation.unscoped.create(
            company=company_a, site=site, kind=Quotation.Kind.RECEIVED,
            supplier=supplier, quotation_date=DAY, total_amount=Decimal("80000"),
        )

        assert "中央電材" in _body(logged_in, site)


@pytest.mark.django_db
class TestCombinedTableKeepsItsOwnColumns:
    def test_区分の列は残す(self, logged_in, company_a, site, supplier):
        PurchaseOrder.unscoped.create(
            company=company_a, site=site, supplier=supplier, order_date=DAY,
            total_amount=Decimal("120000"),
        )

        body = _body(logged_in, site)

        assert "<th>区分</th>" in body
        assert '<span class="badge badge-blue">発注</span>' in body

    def test_現場の列は出さない(self, logged_in, company_a, site, supplier):
        PurchaseOrder.unscoped.create(
            company=company_a, site=site, supplier=supplier, order_date=DAY,
            total_amount=Decimal("120000"),
        )

        body = _body(logged_in, site)
        table = body[body.index("材料の受発注"):]

        assert "<th>現場</th>" not in table[: table.index("</thead>")]
