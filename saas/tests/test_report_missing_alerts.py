"""日報を書いていない人に知らせる（ADR-0080）。

- 出社予定が入っているのに日報が無い日を拾う
- 本人に通知し、同じ日について二重に送らない
- 日報の画面に赤字で「〇月〇日の日報を書いていません」と出す
"""

import datetime

import pytest
from django.urls import reverse

from apps.attendance.models import AttendPlan
from apps.masters.models import WorkType
from apps.notifications.models import Notification
from apps.reports.missing_alerts import (
    check_daily_report_missing_alerts,
    missing_days_for_worker,
    missing_reports,
)
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import Worker

TODAY = datetime.date(2026, 9, 17)
YESTERDAY = TODAY - datetime.timedelta(days=1)


@pytest.fixture
def setup(company_a, user_a):
    site = Site.unscoped.create(company=company_a, code="S001", name="A現場")
    work_type = WorkType.unscoped.create(company=company_a, code="W01", name="電気工事")
    worker = Worker.unscoped.create(company=company_a, name="電工太郎", user=user_a)
    return site, work_type, worker


def _plan(company, worker, day, kind="site"):
    return AttendPlan.unscoped.create(
        company=company, worker=worker, plan_date=day, kind=kind,
    )


def _report(company, user, site, work_type, worker, day):
    return DailyReport.unscoped.create(
        company=company, created_by=user, site=site, work_type=work_type,
        worker=worker, report_date=day, work_hours=8,
    )


@pytest.mark.django_db
class TestFind:
    def test_予定があって日報が無い日を拾う(self, company_a, setup):
        _site, _wt, worker = setup
        _plan(company_a, worker, YESTERDAY)

        found = missing_reports(company_a, today=TODAY)

        assert found == [(worker, YESTERDAY)]

    def test_日報があれば拾わない(self, company_a, user_a, setup):
        site, work_type, worker = setup
        _plan(company_a, worker, YESTERDAY)
        _report(company_a, user_a, site, work_type, worker, YESTERDAY)

        assert missing_reports(company_a, today=TODAY) == []

    def test_休みの予定は対象にしない(self, company_a, setup):
        _site, _wt, worker = setup
        _plan(company_a, worker, YESTERDAY, kind="off")

        assert missing_reports(company_a, today=TODAY) == []

    def test_今日は対象にしない(self, company_a, setup):
        _site, _wt, worker = setup
        _plan(company_a, worker, TODAY)

        assert missing_reports(company_a, today=TODAY) == []

    def test_予定が無い日は対象にしない(self, company_a, setup):
        assert missing_reports(company_a, today=TODAY) == []


@pytest.mark.django_db
class TestNotify:
    def test_本人に通知が届く(self, company_a, user_a, setup):
        _site, _wt, worker = setup
        _plan(company_a, worker, YESTERDAY)

        sent = check_daily_report_missing_alerts(company_a, today=TODAY)

        assert sent >= 1
        notification = Notification.unscoped.filter(recipient=user_a).first()
        assert "日報が未提出" in notification.title
        assert notification.module == Notification.Module.REPORTS

    def test_二度目は送らない(self, company_a, user_a, setup):
        _site, _wt, worker = setup
        _plan(company_a, worker, YESTERDAY)

        check_daily_report_missing_alerts(company_a, today=TODAY)
        check_daily_report_missing_alerts(company_a, today=TODAY)

        assert Notification.unscoped.filter(recipient=user_a).count() == 1

    def test_ログインできない作業員でも落ちない(self, company_a, setup):
        _site, _wt, _worker = setup
        other = Worker.unscoped.create(company=company_a, name="応援太郎")
        _plan(company_a, other, YESTERDAY)

        assert check_daily_report_missing_alerts(company_a, today=TODAY) == 0


@pytest.mark.django_db
class TestScreen:
    def test_日報の画面に赤字で出る(self, client, company_a, user_a, setup):
        from django.utils import timezone

        _site, _wt, worker = setup
        # 画面は今日を見て出すので、実際の前日で予定を作る
        _plan(company_a, worker, timezone.localdate() - datetime.timedelta(days=1))
        client.force_login(user_a)

        html = client.get(reverse("reports:list")).content.decode()

        assert "の日報を書いていません" in html
        assert "report-missing" in html

    def test_抜けが無ければ何も出さない(self, client, company_a, user_a, setup):
        client.force_login(user_a)

        html = client.get(reverse("reports:list")).content.decode()

        assert "の日報を書いていません" not in html

    def test_自分の抜けだけを出す(self, company_a, setup):
        _site, _wt, worker = setup
        other = Worker.unscoped.create(company=company_a, name="応援太郎")
        _plan(company_a, other, YESTERDAY)

        assert missing_days_for_worker(worker, today=TODAY) == []
        assert missing_days_for_worker(other, today=TODAY) == [YESTERDAY]


@pytest.mark.django_db
class TestStartDate:
    """9/14 より前の日は催促しない（ADR-0080 改訂）。"""

    def test_始まりの日より前は調べない(self, company_a, setup):
        from apps.workers.models import Worker as W  # noqa: F401

        _site, _wt, worker = setup
        # 9/13（始まりの日の前日）と 9/15 に予定を入れる
        _plan(company_a, worker, datetime.date(2026, 9, 13))
        _plan(company_a, worker, datetime.date(2026, 9, 15))

        found = missing_reports(company_a, today=datetime.date(2026, 9, 20))

        assert found == [(worker, datetime.date(2026, 9, 15))]

    def test_始まりの日そのものは調べる(self, company_a, setup):
        _site, _wt, worker = setup
        _plan(company_a, worker, datetime.date(2026, 9, 14))

        found = missing_reports(company_a, today=datetime.date(2026, 9, 20))

        assert found == [(worker, datetime.date(2026, 9, 14))]

    def test_設定で始まりの日を変えられる(self, company_a, setup, settings):
        _site, _wt, worker = setup
        settings.DAILY_REPORT_CHECK_START = datetime.date(2026, 9, 16)
        _plan(company_a, worker, datetime.date(2026, 9, 15))

        assert missing_reports(company_a, today=datetime.date(2026, 9, 20)) == []

    def test_画面の赤字も同じ範囲になる(self, company_a, setup):
        _site, _wt, worker = setup
        _plan(company_a, worker, datetime.date(2026, 9, 13))

        assert missing_days_for_worker(worker, today=datetime.date(2026, 9, 20)) == []
