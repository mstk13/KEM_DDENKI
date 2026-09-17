"""同じ日に同じ人の日報が二重に入るのを止める（ADR-0076）。

- 同じ日・同じ人（同姓同名を含む）の日報があれば、保存せず画面に出す
- 「このまま登録する」で送り直したときだけ保存する
"""

import datetime

import pytest
from django.urls import reverse

from apps.masters.models import WorkType
from apps.reports.duplicates import find_duplicate_reports
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import Worker

DAY = datetime.date(2026, 9, 10)


@pytest.fixture
def setup(company_a, user_a):
    site_a = Site.unscoped.create(company=company_a, code="S001", name="A現場")
    site_b = Site.unscoped.create(company=company_a, code="S002", name="B現場")
    work_type = WorkType.unscoped.create(company=company_a, code="W01", name="電気工事")
    worker = Worker.unscoped.create(company=company_a, name="電工太郎", user=user_a)
    return site_a, site_b, work_type, worker


def _report(company, user, site, work_type, worker, day=DAY):
    return DailyReport.unscoped.create(
        company=company, created_by=user, site=site, work_type=work_type,
        worker=worker, report_date=day, work_hours=8,
    )


def _post(client, site, work_type, worker, extra=None):
    data = {
        "report_date": DAY.isoformat(),
        "site": site.name,
        "work_type": work_type.name,
        "workers": [str(worker.pk)],
        "work_description": "配線",
        "work_hours": "8",
        "action": "draft",
    }
    data.update(extra or {})
    return client.post(reverse("reports:create"), data)


@pytest.mark.django_db
class TestFind:
    def test_同じ日の日報を見つける(self, company_a, user_a, setup):
        site_a, site_b, work_type, worker = setup
        _report(company_a, user_a, site_a, work_type, worker)

        found = find_duplicate_reports(company_a, [worker], DAY)

        assert len(found) == 1
        assert found[0]["worker"] == worker
        assert len(found[0]["reports"]) == 1

    def test_別の日なら重複ではない(self, company_a, user_a, setup):
        site_a, _b, work_type, worker = setup
        _report(company_a, user_a, site_a, work_type, worker)

        assert find_duplicate_reports(
            company_a, [worker], DAY + datetime.timedelta(days=1),
        ) == []

    def test_同姓同名の別登録も重複とみなす(self, company_a, user_a, setup):
        site_a, _b, work_type, worker = setup
        same_name = Worker.unscoped.create(company=company_a, name="電工太郎")
        _report(company_a, user_a, site_a, work_type, worker)

        found = find_duplicate_reports(company_a, [same_name], DAY)

        assert len(found) == 1

    def test_編集中の日報は自分を数えない(self, company_a, user_a, setup):
        site_a, _b, work_type, worker = setup
        report = _report(company_a, user_a, site_a, work_type, worker)

        assert find_duplicate_reports(
            company_a, [worker], DAY, exclude_pk=report.pk,
        ) == []


@pytest.mark.django_db
class TestCreateScreen:
    def test_重複があれば保存せずに知らせる(self, client, company_a, user_a, setup):
        site_a, site_b, work_type, worker = setup
        _report(company_a, user_a, site_a, work_type, worker)
        client.force_login(user_a)

        res = _post(client, site_b, work_type, worker)

        assert res.status_code == 200
        html = res.content.decode()
        assert "重複があります" in html
        assert "A現場" in html
        assert "このまま登録する" in html
        assert DailyReport.unscoped.filter(site=site_b).count() == 0

    def test_このまま登録すると保存する(self, client, company_a, user_a, setup):
        site_a, site_b, work_type, worker = setup
        _report(company_a, user_a, site_a, work_type, worker)
        client.force_login(user_a)

        res = _post(client, site_b, work_type, worker, {"confirm_duplicate": "1"})

        assert res.status_code == 302
        assert DailyReport.unscoped.filter(site=site_b).count() == 1

    def test_重複が無ければそのまま保存する(self, client, company_a, user_a, setup):
        _a, site_b, work_type, worker = setup
        client.force_login(user_a)

        res = _post(client, site_b, work_type, worker)

        assert res.status_code == 302
        assert DailyReport.unscoped.filter(site=site_b).count() == 1
