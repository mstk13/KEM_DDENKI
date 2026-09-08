"""日報の削除: 本人と管理者だけが削除できる。承認済は削除不可。テナント越境不可。"""

from decimal import Decimal

import pytest

from apps.masters.models import WorkType
from apps.permissions.models import Role, UserRole
from apps.permissions.services import can_delete_report, setup_default_roles
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import Worker


@pytest.fixture
def work_type_a(company_a):
    return WorkType.unscoped.create(company=company_a, code="E01", name="電気幹線")


@pytest.fixture
def site_a(company_a):
    return Site.unscoped.create(
        company=company_a, code="S001", name="A社ビル新築",
        status=Site.Status.IN_PROGRESS, contract_amount=5000000,
    )


@pytest.fixture
def worker_a(company_a, user_a):
    """user_a 本人の Worker。"""
    return Worker.unscoped.create(
        company=company_a, employee_code="E001", name="電工太郎",
        hourly_cost=3000, user=user_a,
    )


@pytest.fixture
def worker_a2(company_a, user2):
    """同じ会社の別の人（user2）の Worker。"""
    return Worker.unscoped.create(
        company=company_a, employee_code="E002", name="電工次郎",
        hourly_cost=3000, user=user2,
    )


def _make_report(company, site, worker, work_type, *, created_by=None, status=None):
    return DailyReport.unscoped.create(
        company=company, site=site, worker=worker, work_type=work_type,
        report_date="2026-09-01", work_hours=Decimal("8.00"),
        created_by=created_by,
        status=status or DailyReport.Status.DRAFT,
    )


def _grant(company, user, code):
    setup_default_roles(company)
    role = Role.unscoped.get(company=company, code=code)
    UserRole.unscoped.create(company=company, user=user, role=role)


# ---------------------------------------------------------------------------
# 判定ロジック
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCanDeleteReport:
    def test_creator_can_delete(self, company_a, user_a, site_a, worker_a2, work_type_a):
        """入力者本人は、作業員が別人（代理入力）でも削除できる。"""
        report = _make_report(company_a, site_a, worker_a2, work_type_a, created_by=user_a)
        assert can_delete_report(user_a, report) is True

    def test_worker_can_delete_own(self, company_a, user_a, user2, site_a, worker_a, work_type_a):
        """自分が作業員の日報は、他人が代理入力したものでも削除できる。"""
        report = _make_report(company_a, site_a, worker_a, work_type_a, created_by=user2)
        assert can_delete_report(user_a, report) is True

    def test_other_person_cannot_delete(
        self, company_a, user_a, user2, site_a, worker_a2, work_type_a,
    ):
        report = _make_report(company_a, site_a, worker_a2, work_type_a, created_by=user2)
        assert can_delete_report(user_a, report) is False

    def test_president_can_delete_others(
        self, company_a, user_a, user2, site_a, worker_a2, work_type_a,
    ):
        _grant(company_a, user_a, "president")
        report = _make_report(company_a, site_a, worker_a2, work_type_a, created_by=user2)
        assert can_delete_report(user_a, report) is True

    def test_developer_can_delete_others(
        self, company_a, user_a, user2, site_a, worker_a2, work_type_a,
    ):
        """IT（developer ロール）は承認と同様に削除もできる。"""
        _grant(company_a, user_a, "developer")
        report = _make_report(company_a, site_a, worker_a2, work_type_a, created_by=user2)
        assert can_delete_report(user_a, report) is True

    def test_site_manager_cannot_delete_others(
        self, company_a, user_a, user2, site_a, worker_a2, work_type_a,
    ):
        """現場担当者（reports は write まで）は他人の日報を消せない。"""
        _grant(company_a, user_a, "site_manager")
        report = _make_report(company_a, site_a, worker_a2, work_type_a, created_by=user2)
        assert can_delete_report(user_a, report) is False

    def test_approved_cannot_be_deleted_even_by_president(
        self, company_a, user_a, site_a, worker_a, work_type_a,
    ):
        _grant(company_a, user_a, "president")
        report = _make_report(
            company_a, site_a, worker_a, work_type_a,
            created_by=user_a, status=DailyReport.Status.APPROVED,
        )
        assert can_delete_report(user_a, report) is False


# ---------------------------------------------------------------------------
# 画面
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReportDeleteView:
    def test_get_shows_confirm_page(
        self, client, company_a, user_a, site_a, worker_a, work_type_a,
    ):
        report = _make_report(company_a, site_a, worker_a, work_type_a, created_by=user_a)
        client.force_login(user_a)
        response = client.get(f"/reports/{report.pk}/delete/")
        assert response.status_code == 200
        assert "reports/delete_confirm.html" in [t.name for t in response.templates]
        assert DailyReport.unscoped.filter(pk=report.pk).exists()

    def test_post_deletes_own_report(
        self, client, company_a, user_a, site_a, worker_a, work_type_a,
    ):
        report = _make_report(company_a, site_a, worker_a, work_type_a, created_by=user_a)
        client.force_login(user_a)
        response = client.post(f"/reports/{report.pk}/delete/")
        assert response.status_code == 302
        assert response.url == "/reports/"
        assert not DailyReport.unscoped.filter(pk=report.pk).exists()

    def test_post_by_other_person_is_forbidden(
        self, client, company_a, user_a, user2, site_a, worker_a2, work_type_a,
    ):
        report = _make_report(company_a, site_a, worker_a2, work_type_a, created_by=user2)
        client.force_login(user_a)
        response = client.post(f"/reports/{report.pk}/delete/")
        assert response.status_code == 403
        assert DailyReport.unscoped.filter(pk=report.pk).exists()

    def test_post_by_president_deletes_others(
        self, client, company_a, user_a, user2, site_a, worker_a2, work_type_a,
    ):
        _grant(company_a, user_a, "president")
        report = _make_report(company_a, site_a, worker_a2, work_type_a, created_by=user2)
        client.force_login(user_a)
        response = client.post(f"/reports/{report.pk}/delete/")
        assert response.status_code == 302
        assert not DailyReport.unscoped.filter(pk=report.pk).exists()

    def test_approved_is_forbidden(
        self, client, company_a, user_a, site_a, worker_a, work_type_a,
    ):
        _grant(company_a, user_a, "president")
        report = _make_report(
            company_a, site_a, worker_a, work_type_a,
            created_by=user_a, status=DailyReport.Status.APPROVED,
        )
        client.force_login(user_a)
        response = client.post(f"/reports/{report.pk}/delete/")
        assert response.status_code == 403
        assert DailyReport.unscoped.filter(pk=report.pk).exists()

    def test_cross_tenant_is_404(
        self, client, company_a, user_b, site_a, worker_a, work_type_a,
    ):
        """他社の日報は存在自体が見えない（403 ではなく 404）。"""
        report = _make_report(company_a, site_a, worker_a, work_type_a)
        client.force_login(user_b)
        response = client.post(f"/reports/{report.pk}/delete/")
        assert response.status_code == 404
        assert DailyReport.unscoped.filter(pk=report.pk).exists()

    def test_list_shows_delete_only_for_deletable(
        self, client, company_a, user_a, user2, site_a, worker_a, worker_a2, work_type_a,
    ):
        own = _make_report(company_a, site_a, worker_a, work_type_a, created_by=user_a)
        other = _make_report(company_a, site_a, worker_a2, work_type_a, created_by=user2)
        client.force_login(user_a)
        response = client.get("/reports/")
        html = response.content.decode()
        assert f"/reports/{own.pk}/delete/" in html
        assert f"/reports/{other.pk}/delete/" not in html

    def test_edit_page_shows_delete_button(
        self, client, company_a, user_a, site_a, worker_a, work_type_a,
    ):
        report = _make_report(company_a, site_a, worker_a, work_type_a, created_by=user_a)
        client.force_login(user_a)
        response = client.get(f"/reports/{report.pk}/edit/")
        assert response.status_code == 200
        assert f"/reports/{report.pk}/delete/" in response.content.decode()
