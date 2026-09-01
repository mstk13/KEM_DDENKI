"""現場一覧からの現場削除。

現場は全業務データの起点なので、削除は日報・実行予算・原価まで
カスケードする。ここで固定したいのは3点:

1. 一覧・詳細から削除に入れること（導線が無ければ機能が無いのと同じ）
2. 確認画面が「何が何件消えるか」を多段カスケードまで数えて見せること
3. GET では消えないこと、他テナントの現場は消せないこと
"""

import pytest
from django.urls import reverse

from apps.core.tenant_context import set_current_company
from apps.costs.models import BudgetItem, CostTransaction
from apps.masters.models import CostCategory, WorkType
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.sites.services import collect_site_deletion_impact
from apps.workers.models import Worker


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
def site_b(company_b):
    return Site.unscoped.create(
        company=company_b,
        code="S001",
        name="B社内装改修",
        status=Site.Status.IN_PROGRESS,
        contract_amount=3000000,
    )


@pytest.fixture
def site_a_with_data(company_a, site_a):
    """日報・実行予算・原価が付いた現場。カスケードの検証用。"""
    work_type = WorkType.unscoped.create(
        company=company_a, code="E01", name="電気幹線",
    )
    # CostCategory は全テナント共通のシステム定義（TenantModel ではない）。
    category = CostCategory.objects.create(code="L", name="労務費")
    BudgetItem.unscoped.create(
        company=company_a,
        site=site_a,
        work_type=work_type,
        cost_category=category,
        amount=1000000,
    )
    CostTransaction.unscoped.create(
        company=company_a,
        site=site_a,
        work_type=work_type,
        cost_category=category,
        amount=250000,
        transaction_date="2026-08-01",
        source_type=CostTransaction.SourceType.DAILY_REPORT,
    )
    worker = Worker.unscoped.create(
        company=company_a, name="田中太郎", hourly_cost=3000,
    )
    DailyReport.unscoped.create(
        company=company_a,
        site=site_a,
        worker=worker,
        work_type=work_type,
        report_date="2026-08-01",
        work_hours=8,
    )
    return site_a


@pytest.fixture
def logged_in(client, company_a, user_a):
    set_current_company(company_a)
    client.force_login(user_a)
    yield client
    set_current_company(None)


# ---------------------------------------------------------------------------
# 導線
# ---------------------------------------------------------------------------

class TestDeleteEntryPoints:
    def test_site_list_offers_a_delete_link_for_each_site(self, logged_in, site_a):
        res = logged_in.get(reverse("sites:list"))
        body = res.content.decode("utf-8")

        assert res.status_code == 200
        assert f"{reverse('sites:delete', args=[site_a.pk])}?from=list" in body

    def test_site_detail_offers_a_delete_link(self, logged_in, site_a):
        res = logged_in.get(reverse("sites:detail", args=[site_a.pk]))

        assert reverse("sites:delete", args=[site_a.pk]) in res.content.decode("utf-8")

    def test_cancelling_from_the_list_goes_back_to_the_list(self, logged_in, site_a):
        res = logged_in.get(
            reverse("sites:delete", args=[site_a.pk]), {"from": "list"},
        )

        assert res.context["back_url"] == reverse("sites:list")

    def test_cancelling_from_the_detail_goes_back_to_the_detail(
        self, logged_in, site_a,
    ):
        res = logged_in.get(reverse("sites:delete", args=[site_a.pk]))

        assert res.context["back_url"] == reverse("sites:detail", args=[site_a.pk])


# ---------------------------------------------------------------------------
# 確認画面 — 何が消えるか
# ---------------------------------------------------------------------------

class TestDeletionImpact:
    def test_impact_counts_the_records_that_cascade(self, site_a_with_data):
        labels = {
            str(row["label"]): row["count"]
            for row in collect_site_deletion_impact(site_a_with_data)
        }

        assert labels["実行予算"] == 1
        assert labels["原価データ"] == 1
        assert labels["日報"] == 1

    def test_impact_excludes_the_site_itself(self, site_a_with_data):
        labels = [
            str(row["label"])
            for row in collect_site_deletion_impact(site_a_with_data)
        ]

        assert "現場" not in labels

    def test_a_site_with_no_related_data_has_an_empty_impact(self, site_a):
        assert collect_site_deletion_impact(site_a) == []

    def test_confirmation_page_shows_the_counts(self, logged_in, site_a_with_data):
        res = logged_in.get(reverse("sites:delete", args=[site_a_with_data.pk]))
        body = res.content.decode("utf-8")

        assert res.status_code == 200
        assert "A社ビル新築" in body
        assert "日報" in body
        assert "取り消せません" in body


# ---------------------------------------------------------------------------
# 削除の実行
# ---------------------------------------------------------------------------

class TestDeleteExecution:
    def test_get_does_not_delete_anything(self, logged_in, site_a):
        logged_in.get(reverse("sites:delete", args=[site_a.pk]))

        assert Site.unscoped.filter(pk=site_a.pk).exists()

    def test_post_deletes_the_site_and_its_related_data(
        self, logged_in, site_a_with_data,
    ):
        pk = site_a_with_data.pk
        res = logged_in.post(reverse("sites:delete", args=[pk]))

        assert res.status_code == 302
        assert res["Location"] == reverse("sites:list")
        assert not Site.unscoped.filter(pk=pk).exists()
        assert not DailyReport.unscoped.filter(site_id=pk).exists()
        assert not BudgetItem.unscoped.filter(site_id=pk).exists()
        assert not CostTransaction.unscoped.filter(site_id=pk).exists()

    def test_deleted_site_disappears_from_the_list(self, logged_in, site_a):
        logged_in.post(reverse("sites:delete", args=[site_a.pk]))

        res = logged_in.get(reverse("sites:list"))
        body = res.content.decode("utf-8")

        # 現場名そのものは削除完了メッセージにも出るので、一覧の行（詳細リンク）で見る。
        assert reverse("sites:detail", args=[site_a.pk]) not in body
        assert "現場が登録されていません" in body

    def test_anonymous_user_cannot_delete(self, client, company_a, site_a):
        set_current_company(company_a)
        res = client.post(reverse("sites:delete", args=[site_a.pk]))

        assert res.status_code == 302
        assert Site.unscoped.filter(pk=site_a.pk).exists()
        set_current_company(None)


# ---------------------------------------------------------------------------
# テナント越境
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    def test_cannot_delete_a_site_of_another_company(self, logged_in, site_b):
        res = logged_in.post(reverse("sites:delete", args=[site_b.pk]))

        assert res.status_code == 404
        assert Site.unscoped.filter(pk=site_b.pk).exists()

    def test_cannot_open_the_confirmation_of_another_company(self, logged_in, site_b):
        res = logged_in.get(reverse("sites:delete", args=[site_b.pk]))

        assert res.status_code == 404
