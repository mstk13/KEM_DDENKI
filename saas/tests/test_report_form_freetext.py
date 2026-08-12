"""日報フォーム: 現場・工程・工種の手入力と、作業時間の自動計算。

一覧から選ぶだけでなく手入力もできること、手入力された名前が
その場で登録されること、検証に失敗したときは何も登録されないことを守る。
"""

from decimal import Decimal

import pytest

from apps.masters.models import WorkType
from apps.reports.forms import DailyReportForm
from apps.reports.models import DailyReport
from apps.sites.models import Process, Site
from apps.workers.models import Worker


@pytest.fixture
def work_type(company_a):
    return WorkType.unscoped.create(company=company_a, code="E01", name="電気幹線")


@pytest.fixture
def site(company_a):
    return Site.unscoped.create(
        company=company_a, code="S001", name="A社ビル新築",
        status=Site.Status.IN_PROGRESS, contract_amount=5000000,
    )


@pytest.fixture
def worker(company_a):
    return Worker.unscoped.create(
        company=company_a, name="田中太郎", hourly_cost=3000,
    )


def _post(site_name, worker, work_type_name, **overrides):
    data = {
        "site": site_name,
        "workers": [worker.pk] if worker else [],
        "report_date": "2026-08-01",
        "weather": "",
        "process": "",
        "work_type": work_type_name,
        "work_description": "配線作業",
        "start_time": "",
        "end_time": "",
        "work_hours": "8.00",
        "partner": "",
        "memo": "",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
class TestFreeTextFields:
    def test_existing_names_are_reused(self, company_a, site, worker, work_type):
        """既にある現場・工種の名前を入れたら、新しく作らずそれを使う。"""
        form = DailyReportForm(
            data=_post(site.name, worker, work_type.name), company=company_a,
        )
        assert form.is_valid(), form.errors
        saved, _skipped = form.save_reports(company=company_a, user=None)
        report = saved[0]

        assert report.site_id == site.pk
        assert report.work_type_id == work_type.pk
        assert Site.unscoped.filter(company=company_a).count() == 1
        assert WorkType.unscoped.filter(company=company_a).count() == 1

    def test_new_names_are_created(self, company_a, site, worker, work_type):
        """一覧に無い名前を手入力したら、その現場・工種が登録される。"""
        form = DailyReportForm(
            data=_post("B社倉庫改修", worker, "弱電", process="1F 配線"),
            company=company_a,
        )
        assert form.is_valid(), form.errors
        saved, _skipped = form.save_reports(company=company_a, user=None)
        report = saved[0]

        assert report.site.name == "B社倉庫改修"
        assert report.work_type.name == "弱電"
        assert report.process is not None
        assert report.process.name == "1F 配線"
        assert report.process.site_id == report.site_id

    def test_nothing_created_when_form_invalid(self, company_a, site, worker):
        """他の欄でエラーになったとき、現場や工種を作り残さない。"""
        before_sites = Site.unscoped.filter(company=company_a).count()
        before_types = WorkType.unscoped.filter(company=company_a).count()

        # work_hours も start/end も無いので検証に失敗する
        form = DailyReportForm(
            data=_post("新しい現場", worker, "新しい工種", work_hours=""),
            company=company_a,
        )
        assert not form.is_valid()
        assert Site.unscoped.filter(company=company_a).count() == before_sites
        assert WorkType.unscoped.filter(company=company_a).count() == before_types

    def test_site_is_required(self, company_a, worker, work_type):
        form = DailyReportForm(
            data=_post("", worker, work_type.name), company=company_a,
        )
        assert not form.is_valid()
        assert "site" in form.errors

    def test_weather_accepts_free_text(self, company_a, site, worker, work_type):
        """天候は選択肢に無い言葉も入れられる。"""
        form = DailyReportForm(
            data=_post(site.name, worker, work_type.name, weather="みぞれ"),
            company=company_a,
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data["weather"] == "みぞれ"


@pytest.mark.django_db
class TestWorkHoursCalculation:
    def test_hours_calculated_from_start_and_end(
        self, company_a, site, worker, work_type,
    ):
        """開始・終了時間を入れたら作業時間が自動で入る（8時間超は休憩1時間を引く）。"""
        form = DailyReportForm(
            data=_post(
                site.name, worker, work_type.name,
                start_time="08:00", end_time="18:00", work_hours="",
            ),
            company=company_a,
        )
        assert form.is_valid(), form.errors
        saved, _skipped = form.save_reports(company=company_a, user=None)
        report = saved[0]

        # 10時間 - 休憩1時間 = 9時間。8時間を超えた1時間が残業。
        assert report.work_hours == Decimal("9.00")
        assert report.regular_hours == Decimal("8.00")
        assert report.overtime_hours == Decimal("1.00")

    def test_short_day_has_no_break_deduction(
        self, company_a, site, worker, work_type,
    ):
        form = DailyReportForm(
            data=_post(
                site.name, worker, work_type.name,
                start_time="09:00", end_time="15:00", work_hours="",
            ),
            company=company_a,
        )
        assert form.is_valid(), form.errors
        saved, _skipped = form.save_reports(company=company_a, user=None)
        report = saved[0]

        assert report.work_hours == Decimal("6.00")
        assert report.overtime_hours == Decimal("0.00")


@pytest.mark.django_db
class TestMultipleWorkers:
    def test_one_report_per_worker(self, company_a, site, work_type):
        """作業員を複数選んだら、人数分の日報ができる。"""
        a = Worker.unscoped.create(company=company_a, name="田中", hourly_cost=3000)
        b = Worker.unscoped.create(company=company_a, name="鈴木", hourly_cost=3000)
        c = Worker.unscoped.create(company=company_a, name="佐藤", hourly_cost=3000)

        form = DailyReportForm(
            data=_post(site.name, a, work_type.name, workers=[a.pk, b.pk, c.pk]),
            company=company_a,
        )
        assert form.is_valid(), form.errors
        saved, skipped = form.save_reports(company=company_a, user=None)

        assert len(saved) == 3
        assert skipped == []
        assert {r.worker_id for r in saved} == {a.pk, b.pk, c.pk}
        # 内容は全員同じ
        assert {r.site_id for r in saved} == {site.pk}
        assert {str(r.work_hours) for r in saved} == {"8.00"}

    def test_existing_worker_is_skipped(self, company_a, site, work_type):
        """同じ現場・日付・工種の日報が既にある作業員は飛ばす。"""
        a = Worker.unscoped.create(company=company_a, name="田中", hourly_cost=3000)
        b = Worker.unscoped.create(company=company_a, name="鈴木", hourly_cost=3000)
        DailyReport.unscoped.create(
            company=company_a, site=site, worker=a,
            report_date="2026-08-01", work_type=work_type,
            work_hours=Decimal("8.00"),
        )

        form = DailyReportForm(
            data=_post(site.name, a, work_type.name, workers=[a.pk, b.pk]),
            company=company_a,
        )
        assert form.is_valid(), form.errors
        saved, skipped = form.save_reports(company=company_a, user=None)

        assert [r.worker_id for r in saved] == [b.pk]
        assert [w.pk for w in skipped] == [a.pk]

    def test_worker_is_required(self, company_a, site, work_type):
        form = DailyReportForm(
            data=_post(site.name, None, work_type.name, workers=[]),
            company=company_a,
        )
        assert not form.is_valid()
        assert "workers" in form.errors

    def test_edit_allows_only_one_worker(self, company_a, site, work_type):
        """編集画面では作業員を複数選べない。"""
        a = Worker.unscoped.create(company=company_a, name="田中", hourly_cost=3000)
        b = Worker.unscoped.create(company=company_a, name="鈴木", hourly_cost=3000)
        report = DailyReport.unscoped.create(
            company=company_a, site=site, worker=a,
            report_date="2026-08-01", work_type=work_type,
            work_hours=Decimal("8.00"),
        )

        form = DailyReportForm(
            data=_post(site.name, a, work_type.name, workers=[a.pk, b.pk]),
            instance=report, company=company_a,
        )
        assert not form.is_valid()
        assert "workers" in form.errors


@pytest.mark.django_db
class TestOrdererAutoFill:
    def test_orderer_prefilled_on_edit(self, company_a, site, worker, work_type):
        """編集画面を開いたとき、現場に紐づく発注先が入っている。"""
        from apps.masters.models import Customer

        customer = Customer.unscoped.create(
            company=company_a, code="C001", name="株式会社テスト",
        )
        site.customer = customer
        site.save()

        report = DailyReport.unscoped.create(
            company=company_a, site=site, worker=worker,
            report_date="2026-08-01", work_type=work_type,
            work_hours=Decimal("8.00"),
        )
        form = DailyReportForm(instance=report, company=company_a)

        assert form.initial["site"] == site.name
        assert form.initial["orderer"] == str(customer)
