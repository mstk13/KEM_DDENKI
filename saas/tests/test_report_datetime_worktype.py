"""日報フォーム: 開始・終了に日付を持てること（日またぎ）と、工程の選択式＋手入力。

- 開始日・終了日を入れると、日をまたぐ作業時間が正しく計算される
- 日付が空なら従来どおり日報の日付の作業として扱う（終了が開始以前なら翌日扱い）
- 工程は標準の6つ（見積り・現調・施工・試験・追加工事・納入）を先頭に、会社で使われて
  いる工程を続けて選べる。「その他」で入力した工程はその現場に登録され、次回から候補に出る
"""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.masters.models import WorkType
from apps.reports.forms import (
    PROCESS_OTHER,
    STANDARD_PROCESS_NAMES,
    DailyReportForm,
    OfficeDailyReportForm,
)
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
        company=company_a, employee_code="E001", name="田中太郎",
        name_kana="タナカタロウ", hourly_cost=3000,
    )


def _post(site_name, worker, work_type_name, **overrides):
    data = {
        "site": site_name,
        "workers": [worker.pk] if worker else [],
        "report_date": "2026-09-01",
        "weather": "",
        "process": "",
        "work_type": work_type_name,
        "process_other": "",
        "work_description": "配線作業",
        "start_date": "",
        "start_time": "",
        "end_date": "",
        "end_time": "",
        "work_hours": "",
        "partner": "",
        "memo": "",
    }
    data.update(overrides)
    return data


def _save(company, data):
    form = DailyReportForm(data=data, company=company)
    assert form.is_valid(), form.errors
    saved, _skipped = form.save_reports(company=company, user=None)
    return saved[0]


@pytest.mark.django_db
class TestCrossDayPeriod:
    def test_日をまたぐ作業時間を計算する(self, company_a, site, worker, work_type):
        report = _save(company_a, _post(
            site.name, worker, work_type.name,
            start_date="2026-09-01", start_time="22:00",
            end_date="2026-09-02", end_time="06:00",
        ))

        assert report.start_date == datetime.date(2026, 9, 1)
        assert report.end_date == datetime.date(2026, 9, 2)
        assert report.work_hours == Decimal("8.00")
        assert report.regular_hours == Decimal("8.00")
        assert report.overtime_hours == Decimal("0.00")

    def test_翌日の昼まで続く長時間作業(self, company_a, site, worker, work_type):
        """20:00〜翌12:00 = 16h、休憩1hを引いて15h。8hを超えた7hが残業。"""
        report = _save(company_a, _post(
            site.name, worker, work_type.name,
            start_date="2026-09-01", start_time="20:00",
            end_date="2026-09-02", end_time="12:00",
        ))

        assert report.work_hours == Decimal("15.00")
        assert report.regular_hours == Decimal("8.00")
        assert report.overtime_hours == Decimal("7.00")

    def test_日付が空なら従来どおり翌日扱い(self, company_a, site, worker, work_type):
        report = _save(company_a, _post(
            site.name, worker, work_type.name, start_time="22:00", end_time="06:00",
        ))

        assert report.start_date is None
        assert report.end_date is None
        assert report.work_hours == Decimal("8.00")

    def test_同じ日で終了が開始以前なら終了日を翌日にする(
        self, company_a, site, worker, work_type,
    ):
        report = _save(company_a, _post(
            site.name, worker, work_type.name,
            start_date="2026-09-01", start_time="22:00",
            end_date="2026-09-01", end_time="06:00",
        ))

        assert report.end_date == datetime.date(2026, 9, 2)
        assert report.work_hours == Decimal("8.00")

    def test_終了日が開始日より前はエラー(self, company_a, site, worker, work_type):
        form = DailyReportForm(data=_post(
            site.name, worker, work_type.name,
            start_date="2026-09-02", start_time="08:00",
            end_date="2026-09-01", end_time="17:00",
        ), company=company_a)

        assert not form.is_valid()
        assert "end_date" in form.errors

    def test_開始日が空なら日報の日付を開始日とみなす(
        self, company_a, site, worker, work_type,
    ):
        """終了日だけ翌日にした場合も、日報の日付からの時間になる。"""
        report = _save(company_a, _post(
            site.name, worker, work_type.name,
            report_date="2026-09-01", start_time="22:00",
            end_date="2026-09-02", end_time="06:00",
        ))

        assert report.work_hours == Decimal("8.00")

    def test_複数人でも開始日と終了日が各日報に入る(self, company_a, site, work_type):
        w1 = Worker.unscoped.create(
            company=company_a, employee_code="E001", name="一郎", hourly_cost=3000,
        )
        w2 = Worker.unscoped.create(
            company=company_a, employee_code="E002", name="二郎", hourly_cost=3000,
        )
        form = DailyReportForm(data=_post(
            site.name, w1, work_type.name, workers=[w1.pk, w2.pk],
            start_date="2026-09-01", start_time="22:00",
            end_date="2026-09-02", end_time="06:00",
        ), company=company_a)
        assert form.is_valid(), form.errors
        saved, _ = form.save_reports(company=company_a, user=None)

        assert len(saved) == 2
        assert {r.end_date for r in saved} == {datetime.date(2026, 9, 2)}


@pytest.fixture
def office_worker(company_a, user_a):
    return Worker.unscoped.create(
        company=company_a, employee_code="G001", name="開発太郎",
        hourly_cost=3000, user=user_a,
    )


def _office_post(**overrides):
    data = {
        "report_date": "2026-09-01",
        "start_date": "",
        "start_time": "",
        "end_date": "",
        "end_time": "",
        "work_hours": "",
        "memo": "",
        "site_001": "A社ビル新築",
        "work_description_001": "見積書作成",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
class TestOfficeCrossDayPeriod:
    """事務の日報（社員番号 G / S / A / P）も開始日・終了日を持てる。"""

    def test_日をまたぐ勤務時間を計算する(self, company_a, office_worker, site):
        form = OfficeDailyReportForm(data=_office_post(
            start_date="2026-09-01", start_time="22:00",
            end_date="2026-09-02", end_time="06:00",
        ), company=company_a, worker=office_worker)
        assert form.is_valid(), form.errors
        saved, _ = form.save_reports(user=None)

        assert saved[0].start_date == datetime.date(2026, 9, 1)
        assert saved[0].end_date == datetime.date(2026, 9, 2)
        assert saved[0].work_hours == Decimal("8.00")

    def test_同じ日で終了が開始以前なら終了日を翌日にする(
        self, company_a, office_worker, site,
    ):
        form = OfficeDailyReportForm(data=_office_post(
            start_date="2026-09-01", start_time="22:00",
            end_date="2026-09-01", end_time="06:00",
        ), company=company_a, worker=office_worker)
        assert form.is_valid(), form.errors
        saved, _ = form.save_reports(user=None)

        assert saved[0].end_date == datetime.date(2026, 9, 2)
        assert saved[0].work_hours == Decimal("8.00")

    def test_終了日が開始日より前はエラー(self, company_a, office_worker, site):
        form = OfficeDailyReportForm(data=_office_post(
            start_date="2026-09-02", start_time="08:00",
            end_date="2026-09-01", end_time="17:00",
        ), company=company_a, worker=office_worker)

        assert not form.is_valid()
        assert "end_date" in form.errors

    def test_日付は最初の現場にだけ入る(self, company_a, office_worker, site):
        form = OfficeDailyReportForm(data=_office_post(
            start_date="2026-09-01", start_time="22:00",
            end_date="2026-09-02", end_time="06:00",
            site_002="B社倉庫", work_description_002="図面確認",
        ), company=company_a, worker=office_worker)
        assert form.is_valid(), form.errors
        saved, _ = form.save_reports(user=None)

        assert len(saved) == 2
        assert saved[0].end_date == datetime.date(2026, 9, 2)
        assert saved[1].start_date is None
        assert saved[1].end_date is None

    def test_事務の画面にも開始日終了日の欄が出る(self, client, office_worker, user_a):
        user_a.refresh_from_db()
        client.force_login(user_a)

        res = client.get(reverse("reports:create"))

        assert res.status_code == 200
        html = res.content.decode()
        assert "携わった現場" in html
        assert 'name="start_date"' in html
        assert 'name="end_date"' in html


@pytest.mark.django_db
class TestProcessChoices:
    def _choice_values(self, form):
        return [value for value, _label in form.fields["process"].widget.choices]

    def test_標準の工程が先頭に順番どおり並ぶ(self, company_a, site, work_type):
        Process.unscoped.create(company=company_a, site=site, work_type=work_type, name="配線")

        values = self._choice_values(DailyReportForm(company=company_a))

        assert values[0] == ""
        assert tuple(values[1:7]) == STANDARD_PROCESS_NAMES
        # 会社で使われている工程はその後ろ、最後に「その他」
        assert values[7:] == ["配線", PROCESS_OTHER]

    def test_標準の工程は事前には登録しない(self, company_a):
        DailyReportForm(company=company_a)

        assert not Process.unscoped.filter(company=company_a).exists()

    def test_標準の工程を選ぶとその現場の工程として登録される(
        self, company_a, site, worker, work_type,
    ):
        report = _save(company_a, _post(
            site.name, worker, work_type.name, process="施工", work_hours="8.00",
        ))

        assert report.process.name == "施工"
        assert report.process.site_id == site.pk

    def test_その他で入力した工程が登録され次回の候補に出る(
        self, company_a, site, worker, work_type,
    ):
        report = _save(company_a, _post(
            site.name, worker, work_type.name,
            process=PROCESS_OTHER, process_other="保守点検", work_hours="8.00",
        ))

        assert report.process.name == "保守点検"
        assert report.process.site_id == site.pk
        values = self._choice_values(DailyReportForm(company=company_a))
        assert values.index("保守点検") > values.index("納入")
        assert values[-1] == PROCESS_OTHER

    def test_その他を選んで空のままはエラー(self, company_a, site, worker, work_type):
        form = DailyReportForm(data=_post(
            site.name, worker, work_type.name, process=PROCESS_OTHER, work_hours="8.00",
        ), company=company_a)

        assert not form.is_valid()
        assert "process_other" in form.errors
        assert not Process.unscoped.filter(company=company_a).exists()

    def test_工程は空でもよい(self, company_a, site, worker, work_type):
        report = _save(company_a, _post(site.name, worker, work_type.name, work_hours="8.00"))

        assert report.process is None

    def test_編集中の日報の工程が選ばれた状態で開く(
        self, company_a, site, worker, work_type,
    ):
        process = Process.unscoped.create(
            company=company_a, site=site, work_type=work_type, name="配線",
        )
        report = DailyReport.unscoped.create(
            company=company_a, site=site, worker=worker, work_type=work_type,
            process=process, report_date="2026-09-01", work_hours=Decimal("8.00"),
        )

        form = DailyReportForm(instance=report, company=company_a)

        assert form.initial["process"] == "配線"
        assert "配線" in self._choice_values(form)

    def test_工種は手入力のまま(self, company_a, site, worker):
        """工種は一覧に無い名前を直接送っても登録される（従来どおり）。"""
        report = _save(company_a, _post(site.name, worker, "弱電", work_hours="8.00"))

        assert report.work_type.name == "弱電"


@pytest.mark.django_db
class TestReportFormPage:
    def test_画面に工程の選択肢と開始日終了日の欄が出る(self, client, user_a, company_a):
        client.force_login(user_a)

        res = client.get(reverse("reports:create"))

        assert res.status_code == 200
        html = res.content.decode()
        assert '<select name="process"' in html
        for name in STANDARD_PROCESS_NAMES:
            assert f'<option value="{name}">{name}</option>' in html
        assert 'name="process_other"' in html
        # 工種は手入力（datalist）のまま
        assert 'name="work_type"' in html
        assert 'list="worktype-list"' in html
        assert 'name="start_date"' in html
        assert 'name="end_date"' in html
