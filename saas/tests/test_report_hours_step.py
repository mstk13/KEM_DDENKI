"""日報の作業時間は 0.01 単位で入れられる。

0.25 刻みの入力欄だと、0.41 のような時間や、開始・終了から自動計算した 7.58 を
ブラウザが受け付けず登録できなかった。
"""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.masters.models import WorkType
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import Worker

DAY = "2026-09-16"


@pytest.fixture
def data(company_a):
    return {
        "site": Site.unscoped.create(
            company=company_a, code="S001", name="A社ビル",
            status=Site.Status.IN_PROGRESS, contract_amount=1000000,
        ),
        "work_type": WorkType.unscoped.create(company=company_a, code="E01", name="電気"),
        "worker": Worker.unscoped.create(
            company=company_a, employee_code="E001", name="電工太郎", hourly_cost=3000,
        ),
    }


def _post(client, data, **extra):
    payload = {
        "site": data["site"].name,
        "workers": [data["worker"].pk],
        "report_date": DAY,
        "weather": "", "process": "", "process_other": "",
        "work_type": data["work_type"].name,
        "work_description": "配線",
        "start_date": "", "start_time": "", "end_date": "", "end_time": "",
        "work_hours": "0.41",
        "partner": "", "memo": "",
    }
    payload.update(extra)
    return client.post(reverse("reports:create"), payload)


@pytest.mark.django_db
class TestHoursStep:
    def test_入力欄は001刻み(self, client, user_a, data):
        client.force_login(user_a)

        html = client.get(reverse("reports:create")).content.decode()

        assert 'step="0.25"' not in html
        assert html.count('step="0.01"') >= 2  # 自分の欄と、作業員ごとの欄

    def test_中途半端な作業時間で登録できる(self, client, user_a, data):
        client.force_login(user_a)

        res = _post(client, data)

        assert res.status_code == 302
        report = DailyReport.unscoped.get(company=user_a.company)
        assert report.work_hours == Decimal("0.41")

    def test_作業員ごとの時間も中途半端な値で登録できる(self, client, user_a, data):
        client.force_login(user_a)

        res = _post(client, data, **{f"work_hours_{data['worker'].pk}": "7.58"})

        assert res.status_code == 302
        report = DailyReport.unscoped.get(company=user_a.company)
        assert report.work_hours == Decimal("7.58")

    def test_開始終了から自動計算した端数も保存できる(self, company_a, data):
        report = DailyReport.unscoped.create(
            company=company_a, site=data["site"], worker=data["worker"],
            work_type=data["work_type"], report_date=datetime.date(2026, 9, 16),
            work_hours=Decimal("0"),
            start_time=datetime.time(8, 30), end_time=datetime.time(17, 5),
        )

        report.refresh_from_db()

        assert report.work_hours == Decimal("7.58")
        assert report.regular_hours == Decimal("7.58")
        assert report.overtime_hours == Decimal("0.00")
