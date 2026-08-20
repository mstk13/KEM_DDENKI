"""現場詳細への見積もり/実経費の統合と、顧客名の自由入力。

固定したいのは3点:

1. 原価は誰でも見てよい情報ではない。現場詳細に統合しても costs モジュールと
   同じ権限判定を通ること（統合によって全社員に金額が漏れないこと）
2. 顧客欄に未登録の会社名を打てば顧客マスタにも登録されること
3. ただし表記ゆれで重複マスタを作らないこと（取り込み側と同じ正規化で寄せる）
"""

import pytest
from django.urls import reverse

from apps.core.tenant_context import set_current_company
from apps.masters.models import Customer
from apps.sites.models import Site
from apps.sites.services import resolve_or_create_customer


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
def cost_user(company_a, django_user_model):
    """社員番号が G で始まるユーザー。原価の read 権限を持つ。"""
    return django_user_model.objects.create_user(
        username="g_user",
        password="testpass123",
        company=company_a,
        employee_no="G001",
    )


@pytest.fixture
def plain_client(client, company_a, user_a):
    set_current_company(company_a)
    client.force_login(user_a)
    yield client
    set_current_company(None)


@pytest.fixture
def cost_client(client, company_a, cost_user):
    set_current_company(company_a)
    client.force_login(cost_user)
    yield client
    set_current_company(None)


# ---------------------------------------------------------------------------
# 見積もり/実経費の統合と権限
# ---------------------------------------------------------------------------

class TestCostSectionOnSiteDetail:
    def test_permitted_user_sees_the_cost_section(self, cost_client, site_a):
        res = cost_client.get(reverse("sites:detail", args=[site_a.pk]))
        body = res.content.decode("utf-8")

        # サイドバーにも「現場見積もり/実経費」の項目があるため、
        # セクション見出しそのもので判定する。
        assert res.status_code == 200
        assert "<h2>見積もり/実経費</h2>" in body
        assert "消化率" in body

    def test_plain_user_does_not_see_the_cost_section(self, plain_client, site_a):
        res = plain_client.get(reverse("sites:detail", args=[site_a.pk]))
        body = res.content.decode("utf-8")

        assert res.status_code == 200
        assert "<h2>見積もり/実経費</h2>" not in body
        assert "消化率" not in body

    def test_plain_user_does_not_see_the_existing_cost_summary(
        self, plain_client, site_a,
    ):
        """統合前から出ていた原価サマリ（原価合計・粗利）も権限で閉じる。"""
        res = plain_client.get(reverse("sites:detail", args=[site_a.pk]))
        body = res.content.decode("utf-8")

        assert "原価サマリ" not in body
        assert "粗利" not in body

    def test_money_is_not_in_the_context_for_a_plain_user(self, plain_client, site_a):
        """テンプレートで隠すだけでなく、コンテキストにも載せない。"""
        res = plain_client.get(reverse("sites:detail", args=[site_a.pk]))

        assert res.context["can_view_costs"] is False
        assert res.context["cost_summary"] is None
        assert "total_cost" not in res.context
        assert "gross_profit" not in res.context

    def test_the_site_page_still_works_without_cost_access(self, plain_client, site_a):
        """権限が無くても現場詳細そのものは開ける（原価だけが落ちる）。"""
        res = plain_client.get(reverse("sites:detail", args=[site_a.pk]))

        assert res.status_code == 200
        assert "A社ビル新築" in res.content.decode("utf-8")


# ---------------------------------------------------------------------------
# 顧客名の自由入力
# ---------------------------------------------------------------------------

class TestResolveOrCreateCustomer:
    def test_unregistered_name_creates_a_customer(self, company_a):
        customer = resolve_or_create_customer(company_a, "株式会社サンプル建設")

        assert customer.pk is not None
        assert customer.name == "株式会社サンプル建設"
        assert customer.company == company_a

    def test_existing_customer_is_reused(self, company_a):
        first = resolve_or_create_customer(company_a, "株式会社サンプル建設")
        second = resolve_or_create_customer(company_a, "株式会社サンプル建設")

        assert first.pk == second.pk
        assert Customer.unscoped.filter(company=company_a).count() == 1

    def test_notation_differences_do_not_create_a_duplicate(self, company_a):
        """「株式会社ABC」と「(株)ABC」は同じ顧客に寄せる。"""
        first = resolve_or_create_customer(company_a, "株式会社ABC")
        second = resolve_or_create_customer(company_a, "(株)ABC")

        assert first.pk == second.pk
        assert Customer.unscoped.filter(company=company_a).count() == 1

    def test_blank_name_returns_none(self, company_a):
        assert resolve_or_create_customer(company_a, "") is None
        assert resolve_or_create_customer(company_a, "   ") is None
        assert Customer.unscoped.filter(company=company_a).count() == 0

    def test_generated_codes_do_not_collide(self, company_a):
        names = ["A建設", "B工業", "C電機"]
        codes = {resolve_or_create_customer(company_a, n).code for n in names}

        assert len(codes) == 3


class TestCustomerFieldOnSiteForm:
    def _post_edit(self, client, site, customer_name):
        return client.post(reverse("sites:edit", args=[site.pk]), {
            "code": site.code,
            "name": site.name,
            "status": site.status,
            "contract_amount": site.contract_amount,
            "customer_name": customer_name,
            "payment_terms": "",
            "estimate_valid_until": "",
            "start_date": "",
            "end_date": "",
            "address": "",
            "note": "",
            "extracted_details": "",
        })

    def test_typing_a_new_company_name_sets_it_on_the_site(
        self, cost_client, company_a, site_a,
    ):
        res = self._post_edit(cost_client, site_a, "株式会社サンプル建設")
        site_a.refresh_from_db()

        assert res.status_code == 302
        assert site_a.customer is not None
        assert site_a.customer.name == "株式会社サンプル建設"

    def test_typing_a_new_company_name_registers_it_in_the_master(
        self, cost_client, company_a, site_a,
    ):
        self._post_edit(cost_client, site_a, "株式会社サンプル建設")

        assert Customer.unscoped.filter(
            company=company_a, name="株式会社サンプル建設",
        ).exists()

    def test_changing_the_name_later_moves_the_site_to_another_customer(
        self, cost_client, company_a, site_a,
    ):
        self._post_edit(cost_client, site_a, "旧商事")
        self._post_edit(cost_client, site_a, "新商事")
        site_a.refresh_from_db()

        assert site_a.customer.name == "新商事"
        # 元の顧客はマスタに残る（他の現場が参照している可能性があるため消さない）
        assert Customer.unscoped.filter(company=company_a, name="旧商事").exists()

    def test_clearing_the_field_unsets_the_customer(
        self, cost_client, company_a, site_a,
    ):
        self._post_edit(cost_client, site_a, "株式会社サンプル建設")
        self._post_edit(cost_client, site_a, "")
        site_a.refresh_from_db()

        assert site_a.customer is None

    def test_edit_form_prefills_the_current_customer_name(
        self, cost_client, company_a, site_a,
    ):
        self._post_edit(cost_client, site_a, "株式会社サンプル建設")

        res = cost_client.get(reverse("sites:edit", args=[site_a.pk]))

        assert "株式会社サンプル建設" in res.content.decode("utf-8")


# ---------------------------------------------------------------------------
# 用語
# ---------------------------------------------------------------------------

class TestTerminology:
    def test_site_list_says_kokyaku_not_tokuisaki(self, plain_client, site_a):
        body = plain_client.get(reverse("sites:list")).content.decode("utf-8")

        assert "顧客" in body
        assert "得意先" not in body

    def test_site_detail_says_kokyaku_not_tokuisaki(self, plain_client, site_a):
        body = plain_client.get(
            reverse("sites:detail", args=[site_a.pk])
        ).content.decode("utf-8")

        assert "顧客" in body
        assert "得意先" not in body

    def test_site_edit_form_says_kokyaku_not_tokuisaki(self, plain_client, site_a):
        body = plain_client.get(
            reverse("sites:edit", args=[site_a.pk])
        ).content.decode("utf-8")

        assert "顧客" in body
        assert "得意先" not in body

    def test_customer_model_verbose_name_is_kokyaku(self):
        assert str(Customer._meta.verbose_name) == "顧客"
