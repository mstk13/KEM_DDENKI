"""M2 テスト: 現場・工程・日報の越境テスト + 承認フロー。"""

from decimal import Decimal

import pytest

from apps.core.tenant_context import set_current_company
from apps.masters.models import WorkType
from apps.reports.models import DailyReport
from apps.sites.models import Process, Site
from apps.workers.models import Worker


@pytest.fixture
def work_type_a(company_a):
    return WorkType.unscoped.create(company=company_a, code="E01", name="電気幹線")


@pytest.fixture
def work_type_b(company_b):
    return WorkType.unscoped.create(company=company_b, code="N01", name="軽鉄ボード")


@pytest.fixture
def site_a(company_a, work_type_a):
    return Site.unscoped.create(
        company=company_a,
        code="S001",
        name="A社ビル新築",
        status=Site.Status.IN_PROGRESS,
        contract_amount=5000000,
    )


@pytest.fixture
def site_b(company_b, work_type_b):
    return Site.unscoped.create(
        company=company_b,
        code="S001",
        name="B社内装改修",
        status=Site.Status.IN_PROGRESS,
        contract_amount=3000000,
    )


@pytest.fixture
def worker_a(company_a):
    return Worker.unscoped.create(
        company=company_a, name="田中太郎", hourly_cost=3000,
    )


# ---------------------------------------------------------------------------
# 現場の越境テスト
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSiteIsolation:
    def test_site_isolation(self, company_a, company_b, site_a, site_b):
        set_current_company(company_a)
        assert Site.objects.count() == 1
        assert Site.objects.first().name == "A社ビル新築"

        set_current_company(company_b)
        assert Site.objects.count() == 1
        assert Site.objects.first().name == "B社内装改修"

        set_current_company(None)

    def test_process_isolation(
        self, company_a, company_b, site_a, site_b, work_type_a, work_type_b,
    ):
        Process.unscoped.create(
            company=company_a, site=site_a, work_type=work_type_a, name="幹線敷設",
        )
        Process.unscoped.create(
            company=company_b, site=site_b, work_type=work_type_b, name="ボード施工",
        )

        set_current_company(company_a)
        assert Process.objects.count() == 1
        assert Process.objects.first().name == "幹線敷設"

        set_current_company(company_b)
        assert Process.objects.count() == 1
        assert Process.objects.first().name == "ボード施工"

        set_current_company(None)


# ---------------------------------------------------------------------------
# 日報の越境テスト + 承認フロー
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDailyReportIsolation:
    def test_report_isolation(
        self, company_a, company_b, site_a, site_b, work_type_a, work_type_b, worker_a,
    ):
        worker_b = Worker.unscoped.create(
            company=company_b, name="佐藤花子", hourly_cost=2500,
        )

        DailyReport.unscoped.create(
            company=company_a, site=site_a, worker=worker_a,
            report_date="2026-08-01", work_type=work_type_a,
            work_hours=Decimal("8.00"),
        )
        DailyReport.unscoped.create(
            company=company_b, site=site_b, worker=worker_b,
            report_date="2026-08-01", work_type=work_type_b,
            work_hours=Decimal("7.50"),
        )

        set_current_company(company_a)
        reports = DailyReport.objects.all()
        assert reports.count() == 1
        assert reports.first().worker.name == "田中太郎"

        set_current_company(company_b)
        reports = DailyReport.objects.all()
        assert reports.count() == 1
        assert reports.first().worker.name == "佐藤花子"

        set_current_company(None)

    def test_approval_workflow(self, company_a, site_a, work_type_a, worker_a):
        report = DailyReport.unscoped.create(
            company=company_a, site=site_a, worker=worker_a,
            report_date="2026-08-01", work_type=work_type_a,
            work_hours=Decimal("8.00"),
        )
        assert report.status == DailyReport.Status.DRAFT

        report.status = DailyReport.Status.SUBMITTED
        report.save()
        assert report.status == DailyReport.Status.SUBMITTED

        report.status = DailyReport.Status.APPROVED
        report.save()
        assert report.status == DailyReport.Status.APPROVED
