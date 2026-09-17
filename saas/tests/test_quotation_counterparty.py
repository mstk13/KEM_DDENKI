"""見積の相手先は、向き（kind）を見て出す（ADR-0085）。

`Quotation` は2つの向きを同じモデルで持つ。

| 向き | 相手先の入る列 | supplier |
|---|---|---|
| `RECEIVED`（仕入先から受領） | `supplier` | 入っている |
| `ISSUED`（自社が顧客へ発行） | `customer` | **空** |

そのため画面で `supplier` を直接読むと、**自社発行の見積で相手先が空欄になる**。
実際に見積一覧・見積詳細の見出し・見積詳細の情報表で空欄になっていた。

判断を `counterparty_name` / `counterparty_label` に集め、画面はそれだけを読む。
ここでは「どの画面でも自社発行の相手先が出る」ことを固定して、`supplier` を
直接読む書き方に戻るのを止める。

仕入先比較（`compare_quotations`）も同じ系統の不具合だった。status だけで
絞っていたため、自社発行の見積が「採用」になると仕入先比較に混ざっていた。
"""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.tenant_context import set_current_company
from apps.masters.models import Customer, Supplier
from apps.materials.models import Material, Quotation, QuotationItem
from apps.materials.services import compare_quotations
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
    return Site.unscoped.create(company=company_a, code="S001", name="A社ビル")


@pytest.fixture
def supplier(company_a):
    return Supplier.unscoped.create(company=company_a, code="SUP1", name="中央電材")


@pytest.fixture
def customer(company_a):
    return Customer.unscoped.create(company=company_a, code="C1", name="株式会社甲")


@pytest.fixture
def issued(company_a, site, customer):
    """自社が顧客へ出した見積。supplier は空。"""
    return Quotation.unscoped.create(
        company=company_a, site=site, kind=Quotation.Kind.ISSUED,
        customer=customer, quotation_date=DAY, total_amount=Decimal("80000"),
    )


@pytest.fixture
def received(company_a, site, supplier):
    """仕入先から受領した見積。"""
    return Quotation.unscoped.create(
        company=company_a, site=site, kind=Quotation.Kind.RECEIVED,
        supplier=supplier, quotation_date=DAY, total_amount=Decimal("50000"),
    )


@pytest.mark.django_db
class TestModelKnowsTheDirection:
    def test_自社発行は顧客名と顧客というラベルを返す(self, issued):
        assert issued.counterparty_name == "株式会社甲"
        assert issued.counterparty_label == "顧客"

    def test_受領は仕入先名と仕入先というラベルを返す(self, received):
        assert received.counterparty_name == "中央電材"
        assert received.counterparty_label == "仕入先"

    def test_相手先が未設定でも空文字にはしない(self, company_a, site):
        bare = Quotation.unscoped.create(
            company=company_a, site=site, kind=Quotation.Kind.RECEIVED,
            quotation_date=DAY, total_amount=Decimal("0"),
        )

        assert bare.counterparty_name == "相手先未設定"


@pytest.mark.django_db
class TestEveryScreenShowsTheCounterparty:
    """自社発行の見積の相手先が、どの画面でも空欄にならないこと。"""

    def test_見積一覧(self, logged_in, issued):
        body = logged_in.get(reverse("materials:quotation_list")).content.decode()

        assert "株式会社甲" in body
        # 混在する一覧なので見出しは「相手先」
        assert "<th>相手先</th>" in body

    def test_見積詳細の見出し(self, logged_in, issued):
        body = logged_in.get(
            reverse("materials:quotation_detail", args=[issued.pk])
        ).content.decode()

        assert f"見積-{issued.pk} 株式会社甲" in body

    def test_見積詳細の情報表は向きに合わせた呼び方で出す(self, logged_in, issued):
        body = logged_in.get(
            reverse("materials:quotation_detail", args=[issued.pk])
        ).content.decode()

        assert "顧客" in body
        assert "自社が発行" in body

    def test_受領した見積の詳細は仕入先と呼ぶ(self, logged_in, received):
        body = logged_in.get(
            reverse("materials:quotation_detail", args=[received.pk])
        ).content.decode()

        assert "仕入先" in body
        assert "中央電材" in body

    def test_現場詳細(self, logged_in, site, issued):
        body = logged_in.get(reverse("sites:detail", args=[site.pk])).content.decode()

        assert "株式会社甲" in body


@pytest.mark.django_db
class TestSupplierComparisonOnlyUsesReceivedQuotations:
    def test_自社発行の見積は採用でも仕入先比較に出さない(
        self, company_a, site, supplier, customer,
    ):
        material = Material.unscoped.create(
            company=company_a, code="M1", name="CVケーブル", unit="m",
        )
        # 仕入先から受領した見積（比較に出るべき）
        from_supplier = Quotation.unscoped.create(
            company=company_a, site=site, kind=Quotation.Kind.RECEIVED,
            supplier=supplier, quotation_date=DAY,
            status=Quotation.Status.RECEIVED, total_amount=Decimal("50000"),
        )
        QuotationItem.unscoped.create(
            company=company_a, quotation=from_supplier, material=material,
            material_name="CVケーブル", quantity=Decimal("100"),
            unit_price=Decimal("500"),
        )
        # 自社が顧客へ出した見積。「採用」なので status だけの絞り込みでは通ってしまう
        to_customer = Quotation.unscoped.create(
            company=company_a, site=site, kind=Quotation.Kind.ISSUED,
            customer=customer, quotation_date=DAY,
            status=Quotation.Status.ACCEPTED, total_amount=Decimal("90000"),
        )
        QuotationItem.unscoped.create(
            company=company_a, quotation=to_customer, material=material,
            material_name="CVケーブル", quantity=Decimal("100"),
            unit_price=Decimal("900"),
        )

        results = compare_quotations(material.pk)

        assert [r["quotation"].pk for r in results] == [from_supplier.pk]
        # 仕入先が空の行が混ざらない
        assert all(r["supplier"] is not None for r in results)
