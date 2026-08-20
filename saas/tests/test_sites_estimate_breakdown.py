"""現場詳細から見積の内訳明細を見る。

見積（Quotation）と見積明細（QuotationItem）は元から現場に紐づいていたが、
現場詳細からは**明細へ辿れなかった**（見積行の操作列が空だった）。
ここで固定するのは3点:

1. 現場詳細に見積の明細行そのものが出ること
2. 自社発行の見積で相手先が空欄にならないこと（supplier ではなく customer 側）
3. 実行予算の内訳は原価扱いなので、権限が無ければ出ないこと
"""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.tenant_context import set_current_company
from apps.costs.models import BudgetItem
from apps.masters.models import CostCategory, Customer, WorkType
from apps.materials.models import Quotation, QuotationItem
from apps.sites.models import Site


@pytest.fixture
def site_a(company_a):
    return Site.unscoped.create(
        company=company_a,
        code="S001",
        name="A社ビル新築",
        status=Site.Status.IN_PROGRESS,
        contract_amount=5000000,
    )


@pytest.fixture
def customer_a(company_a):
    return Customer.unscoped.create(
        company=company_a, code="C001", name="株式会社サンプル建設",
    )


@pytest.fixture
def issued_quotation(company_a, site_a, customer_a):
    """見積ファイルの取り込みで作られる形（自社発行・明細つき）。"""
    quotation = Quotation.unscoped.create(
        company=company_a,
        kind=Quotation.Kind.ISSUED,
        site=site_a,
        customer=customer_a,
        quotation_number="Q-2026-0142",
        source_filename="estimate.csv",
        quotation_date=datetime.date(2026, 8, 12),
        total_amount=340000,
        status=Quotation.Status.RECEIVED,
    )
    QuotationItem.unscoped.create(
        company=company_a,
        quotation=quotation,
        material_name="電線管",
        spec="E19 溶融亜鉛メッキ",
        unit="m",
        quantity=Decimal("120"),
        unit_price=Decimal("2000"),
        amount=240000,
        remarks="別途足場",
        sort_order=0,
    )
    QuotationItem.unscoped.create(
        company=company_a,
        quotation=quotation,
        material_name="盤据付",
        # 一式計上。数量・単価が読めない行。
        amount=100000,
        sort_order=1,
    )
    return quotation


@pytest.fixture
def budget_rows(company_a, site_a):
    work_type = WorkType.unscoped.create(
        company=company_a, code="E01", name="電気幹線",
    )
    category = CostCategory.objects.create(code="material", name="材料費")
    BudgetItem.unscoped.create(
        company=company_a,
        site=site_a,
        work_type=work_type,
        cost_category=category,
        name="電線管一式",
        unit="m",
        quantity=Decimal("120"),
        unit_price=Decimal("1500"),
        amount=180000,
    )
    return site_a


@pytest.fixture
def plain_client(client, company_a, user_a):
    set_current_company(company_a)
    client.force_login(user_a)
    yield client
    set_current_company(None)


@pytest.fixture
def cost_client(client, company_a, django_user_model):
    user = django_user_model.objects.create_user(
        username="g_user",
        password="testpass123",
        company=company_a,
        employee_no="G001",
    )
    set_current_company(company_a)
    client.force_login(user)
    yield client
    set_current_company(None)


# ---------------------------------------------------------------------------
# 見積内訳
# ---------------------------------------------------------------------------

class TestQuotationBreakdownOnSiteDetail:
    def test_site_detail_has_a_breakdown_section(self, plain_client, site_a):
        body = plain_client.get(
            reverse("sites:detail", args=[site_a.pk])
        ).content.decode("utf-8")

        assert "見積内訳" in body

    def test_line_items_are_shown_inline(
        self, plain_client, site_a, issued_quotation,
    ):
        """見積詳細へ移らなくても、現場詳細で明細そのものが読める。"""
        body = plain_client.get(
            reverse("sites:detail", args=[site_a.pk])
        ).content.decode("utf-8")

        assert "電線管" in body
        assert "E19 溶融亜鉛メッキ" in body
        assert "別途足場" in body
        assert "盤据付" in body

    def test_quotation_number_and_source_file_are_shown(
        self, plain_client, site_a, issued_quotation,
    ):
        body = plain_client.get(
            reverse("sites:detail", args=[site_a.pk])
        ).content.decode("utf-8")

        assert "Q-2026-0142" in body
        assert "estimate.csv" in body

    def test_issued_quotation_shows_the_customer_as_counterparty(
        self, plain_client, site_a, issued_quotation,
    ):
        """自社発行の見積は supplier が空。顧客側を相手先として出す。"""
        body = plain_client.get(
            reverse("sites:detail", args=[site_a.pk])
        ).content.decode("utf-8")

        assert "株式会社サンプル建設" in body

    def test_there_is_a_link_to_the_quotation_detail(
        self, plain_client, site_a, issued_quotation,
    ):
        body = plain_client.get(
            reverse("sites:detail", args=[site_a.pk])
        ).content.decode("utf-8")

        assert reverse(
            "materials:quotation_detail", args=[issued_quotation.pk]
        ) in body

    def test_empty_state_when_the_site_has_no_quotation(self, plain_client, site_a):
        body = plain_client.get(
            reverse("sites:detail", args=[site_a.pk])
        ).content.decode("utf-8")

        assert "紐づく見積はまだありません" in body

    def test_another_companys_quotation_is_not_listed(
        self, plain_client, site_a, company_b,
    ):
        other_site = Site.unscoped.create(
            company=company_b, code="S001", name="B社現場", contract_amount=0,
        )
        Quotation.unscoped.create(
            company=company_b,
            kind=Quotation.Kind.ISSUED,
            site=other_site,
            quotation_number="B-SHOULD-NOT-APPEAR",
            quotation_date=datetime.date(2026, 8, 12),
            total_amount=1,
        )

        body = plain_client.get(
            reverse("sites:detail", args=[site_a.pk])
        ).content.decode("utf-8")

        assert "B-SHOULD-NOT-APPEAR" not in body


# ---------------------------------------------------------------------------
# 実行予算の内訳（原価扱い）
# ---------------------------------------------------------------------------

class TestBudgetBreakdown:
    def test_permitted_user_sees_the_budget_rows(self, cost_client, budget_rows):
        body = cost_client.get(
            reverse("sites:detail", args=[budget_rows.pk])
        ).content.decode("utf-8")

        assert "実行予算の内訳" in body
        assert "電線管一式" in body

    def test_plain_user_does_not_see_the_budget_rows(self, plain_client, budget_rows):
        body = plain_client.get(
            reverse("sites:detail", args=[budget_rows.pk])
        ).content.decode("utf-8")

        assert "実行予算の内訳" not in body
        assert "電線管一式" not in body

    def test_budget_rows_are_not_in_the_context_without_permission(
        self, plain_client, budget_rows,
    ):
        res = plain_client.get(reverse("sites:detail", args=[budget_rows.pk]))

        assert res.context["budget_items"] is None
