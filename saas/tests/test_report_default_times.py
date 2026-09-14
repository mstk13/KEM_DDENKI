"""日報を書くときの開始・終了の初期値（ADR-0055）。

- 新しく書く画面では、開始 08:30・終了 17:30 が最初から入っている
- 勤怠設定に所定の始業・終業が保存されていればその時刻。読めない値なら 08:30・17:30
- 編集画面は保存済みの値のまま（空の日報に初期値を入れない）
- 初期値のまま保存すると 08:30〜17:30・作業時間 8 時間で保存される
"""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.attendance.models import AttendSettings
from apps.masters.models import WorkType
from apps.reports.models import DailyReport
from apps.reports.standard_times import standard_work_times
from apps.sites.models import Site
from apps.workers.models import Worker


@pytest.fixture
def me(company_a, user_a):
    return Worker.unscoped.create(
        company=company_a, employee_code="E001", name="電工太郎", hourly_cost=3000, user=user_a,
    )


def _input_value(body, name):
    """<input ... name="start_time" ... value="08:30"> の value を取り出す。"""
    import re

    for tag in re.findall(r"<input[^>]*>", body):
        if f'name="{name}"' in tag:
            m = re.search(r'value="([^"]*)"', tag)
            return m.group(1) if m else ""
    raise AssertionError(f"input {name} not found")


@pytest.mark.django_db
class TestStandardWorkTimes:
    def test_保存が無ければ0830と1730(self, company_a):
        assert standard_work_times(company_a) == (datetime.time(8, 30), datetime.time(17, 30))

    def test_勤怠設定に保存があればその時刻(self, company_a):
        AttendSettings.unscoped.create(company=company_a, key="standard_start", value="09:00")
        AttendSettings.unscoped.create(company=company_a, key="standard_end", value="18:15")
        assert standard_work_times(company_a) == (datetime.time(9, 0), datetime.time(18, 15))
        # 会社の ID でも同じ
        assert standard_work_times(company_a.pk) == (datetime.time(9, 0), datetime.time(18, 15))

    def test_読めない値や他社の設定は使わない(self, company_a, company_b):
        AttendSettings.unscoped.create(company=company_a, key="standard_start", value="abc")
        AttendSettings.unscoped.create(company=company_b, key="standard_end", value="20:00")
        assert standard_work_times(company_a) == (datetime.time(8, 30), datetime.time(17, 30))


@pytest.mark.django_db
class TestCreateFormDefaults:
    def test_新しく書く画面は0830と1730が入っている(self, client, user_a, me):
        client.force_login(user_a)
        body = client.get(reverse("reports:create")).content.decode()
        assert _input_value(body, "start_time") == "08:30"
        assert _input_value(body, "end_time") == "17:30"

    def test_勤怠設定の所定時刻が入る(self, client, user_a, me, company_a):
        AttendSettings.unscoped.create(company=company_a, key="standard_start", value="08:00")
        AttendSettings.unscoped.create(company=company_a, key="standard_end", value="17:00")
        client.force_login(user_a)
        body = client.get(reverse("reports:create")).content.decode()
        assert _input_value(body, "start_time") == "08:00"
        assert _input_value(body, "end_time") == "17:00"

    def test_画面を開いたときに作業時間も計算する(self, client, user_a, me):
        client.force_login(user_a)
        body = client.get(reverse("reports:create")).content.decode()
        assert "start.value && end.value && !hours.value) calcHours();" in body

    def test_初期値のまま保存すると0830から1730で8時間(self, client, user_a, me, company_a):
        client.force_login(user_a)
        res = client.post(reverse("reports:create"), {
            "site": "A社ビル", "workers": [me.pk], "report_date": "2026-09-14",
            "weather": "", "process": "", "work_type": "電気", "work_description": "配線",
            "start_date": "", "start_time": "08:30", "end_date": "", "end_time": "17:30",
            "work_hours": "", "partner": "", "memo": "", "action": "draft",
        })
        assert res.status_code == 302
        report = DailyReport.unscoped.get(worker=me)
        assert report.start_time == datetime.time(8, 30)
        assert report.end_time == datetime.time(17, 30)
        assert report.work_hours == Decimal("8.00")


@pytest.mark.django_db
class TestEditKeepsSavedValues:
    def _report(self, company, worker, **kw):
        site = Site.unscoped.create(company=company, code="S001", name="A社ビル")
        wt = WorkType.unscoped.create(company=company, code="E01", name="電気")
        values = dict(
            company=company, site=site, worker=worker, work_type=wt,
            report_date=datetime.date(2026, 9, 14), work_hours=Decimal("8.00"),
        )
        values.update(kw)
        return DailyReport.unscoped.create(**values)

    def test_保存済みの時刻を出す(self, client, user_a, me, company_a):
        report = self._report(company_a, me, start_time=datetime.time(7, 0),
                              end_time=datetime.time(16, 0))
        client.force_login(user_a)
        body = client.get(reverse("reports:edit", args=[report.pk])).content.decode()
        assert _input_value(body, "start_time") == "07:00"
        assert _input_value(body, "end_time") == "16:00"

    def test_時刻が空の日報に初期値を入れない(self, client, user_a, me, company_a):
        report = self._report(company_a, me)
        client.force_login(user_a)
        body = client.get(reverse("reports:edit", args=[report.pk])).content.decode()
        assert _input_value(body, "start_time") == ""
        assert _input_value(body, "end_time") == ""
