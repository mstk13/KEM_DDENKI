"""事務の日報（社員番号 G / S / A / P）。

1日ぶんの勤務時間を1回入力し、その日に携わった現場ごとに作業内容を書く。
保存すると現場1件につき日報1件ができ、勤務時間は最初の現場にだけ入る。
"""

from decimal import Decimal

import pytest

from apps.reports.forms import (
    OFFICE_WORK_TYPE_NAME,
    OfficeDailyReportForm,
    is_office_reporter,
)
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import Worker


@pytest.fixture
def office_worker(company_a, user_a):
    return Worker.unscoped.create(
        company=company_a, employee_code="G001", name="開発太郎",
        hourly_cost=3000, user=user_a,
    )


@pytest.fixture
def site_a(company_a):
    return Site.unscoped.create(
        company=company_a, code="S001", name="A社ビル新築",
    )


def _post(**overrides):
    data = {
        "report_date": "2026-08-01",
        "start_time": "09:00",
        "end_time": "18:00",
        "work_hours": "",
        "memo": "",
        "site_001": "A社ビル新築",
        "work_description_001": "見積書作成",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
class TestOfficeReporterDetection:
    @pytest.mark.parametrize("code", ["G001", "S001", "A001", "P001"])
    def test_office_prefixes(self, company_a, user_a, code):
        Worker.unscoped.create(
            company=company_a, employee_code=code, name="担当",
            hourly_cost=0, user=user_a,
        )
        user_a.refresh_from_db()
        assert is_office_reporter(user_a) is True

    @pytest.mark.parametrize("code", ["E001", "T001", "Y001", "W001", ""])
    def test_field_prefixes(self, company_a, user_a, code):
        Worker.unscoped.create(
            company=company_a, employee_code=code, name="担当",
            hourly_cost=0, user=user_a,
        )
        user_a.refresh_from_db()
        assert is_office_reporter(user_a) is False

    def test_user_without_worker(self, user_a):
        assert is_office_reporter(user_a) is False


@pytest.mark.django_db
class TestOfficeDailyReportForm:
    def test_one_report_per_site(self, company_a, office_worker, site_a):
        """現場を複数書いたら、その数だけ日報ができる。"""
        form = OfficeDailyReportForm(
            data=_post(site_002="B社倉庫", work_description_002="発注処理"),
            company=company_a, worker=office_worker,
        )
        assert form.is_valid(), form.errors
        saved, skipped = form.save_reports(user=None)

        assert len(saved) == 2
        assert skipped == []
        assert [r.site.name for r in saved] == ["A社ビル新築", "B社倉庫"]
        assert [r.work_description for r in saved] == ["見積書作成", "発注処理"]
        # 全件が同じ作業員・同じ日付
        assert {r.worker_id for r in saved} == {office_worker.pk}
        assert {str(r.report_date) for r in saved} == {"2026-08-01"}

    def test_hours_only_on_first_site(self, company_a, office_worker, site_a):
        """勤務時間は最初の現場にだけ入る（勤怠の二重計上を防ぐ）。"""
        form = OfficeDailyReportForm(
            data=_post(site_002="B社倉庫", work_description_002="発注処理"),
            company=company_a, worker=office_worker,
        )
        assert form.is_valid(), form.errors
        saved, _ = form.save_reports(user=None)

        # 9:00-18:00 = 9時間 → 休憩1時間を引いて8時間
        assert saved[0].work_hours == Decimal("8.00")
        assert saved[1].work_hours == Decimal("0.00")
        assert saved[1].start_time is None

    def test_new_site_is_created(self, company_a, office_worker):
        """一覧に無い現場名は、その場で登録される。"""
        form = OfficeDailyReportForm(
            data=_post(site_001="はじめての現場"),
            company=company_a, worker=office_worker,
        )
        assert form.is_valid(), form.errors
        saved, _ = form.save_reports(user=None)
        assert saved[0].site.name == "はじめての現場"

    def test_work_type_is_office(self, company_a, office_worker, site_a):
        form = OfficeDailyReportForm(
            data=_post(), company=company_a, worker=office_worker,
        )
        assert form.is_valid(), form.errors
        saved, _ = form.save_reports(user=None)
        assert saved[0].work_type.name == OFFICE_WORK_TYPE_NAME

    def test_site_is_required(self, company_a, office_worker):
        form = OfficeDailyReportForm(
            data=_post(site_001=""), company=company_a, worker=office_worker,
        )
        assert not form.is_valid()

    def test_duplicated_site_is_rejected(self, company_a, office_worker):
        """同じ現場を2回書くと保存できないので、入力時点で止める。"""
        form = OfficeDailyReportForm(
            data=_post(site_002="A社ビル新築", work_description_002="別作業"),
            company=company_a, worker=office_worker,
        )
        assert not form.is_valid()

    def test_hours_required_without_times(self, company_a, office_worker):
        form = OfficeDailyReportForm(
            data=_post(start_time="", end_time="", work_hours=""),
            company=company_a, worker=office_worker,
        )
        assert not form.is_valid()
        assert "work_hours" in form.errors

    def test_worker_required(self, company_a):
        form = OfficeDailyReportForm(
            data=_post(), company=company_a, worker=None,
        )
        assert not form.is_valid()

    def test_existing_report_is_skipped(self, company_a, office_worker, site_a):
        """同じ現場・日付の日報が既にあれば、その現場だけ飛ばす。"""
        from apps.reports.forms import resolve_work_type

        DailyReport.unscoped.create(
            company=company_a, site=site_a, worker=office_worker,
            report_date="2026-08-01",
            work_type=resolve_work_type(company_a, OFFICE_WORK_TYPE_NAME),
            work_hours=Decimal("8.00"),
        )

        form = OfficeDailyReportForm(
            data=_post(site_002="B社倉庫", work_description_002="発注処理"),
            company=company_a, worker=office_worker,
        )
        assert form.is_valid(), form.errors
        saved, skipped = form.save_reports(user=None)

        assert [r.site.name for r in saved] == ["B社倉庫"]
        assert skipped == ["A社ビル新築"]


@pytest.mark.django_db
class TestOfficeFormRouting:
    def test_office_user_gets_office_form(self, client, company_a, user_a):
        Worker.unscoped.create(
            company=company_a, employee_code="G001", name="開発太郎",
            hourly_cost=0, user=user_a,
        )
        client.force_login(user_a)
        response = client.get("/reports/new/")
        assert response.status_code == 200
        assert "reports/office_form.html" in [t.name for t in response.templates]

    def test_field_user_gets_normal_form(self, client, company_a, user_a):
        Worker.unscoped.create(
            company=company_a, employee_code="E001", name="電工太郎",
            hourly_cost=0, user=user_a,
        )
        client.force_login(user_a)
        response = client.get("/reports/new/")
        assert response.status_code == 200
        assert "reports/form.html" in [t.name for t in response.templates]
