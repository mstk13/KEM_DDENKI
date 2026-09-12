"""日報一覧を月で絞り込む（ADR-0047）。

- ?month=YYYY-MM でその月の日報だけ出す
- 指定なし・読めない値は全期間（従来どおり）
- 状態の絞り込みと組み合わせられる
- 前月・翌月のリンク先と件数表示
"""

import datetime

import pytest
from django.urls import reverse

from apps.masters.models import WorkType
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import Worker


@pytest.fixture
def reports(company_a):
    site = Site.unscoped.create(company=company_a, code="S001", name="A社ビル")
    work_type = WorkType.unscoped.create(company=company_a, code="E01", name="電気")
    worker = Worker.unscoped.create(
        company=company_a, employee_code="E001", name="電工太郎", hourly_cost=3000,
    )

    def make(day, status=DailyReport.Status.DRAFT, wt=work_type):
        return DailyReport.unscoped.create(
            company=company_a, site=site, worker=worker, work_type=wt,
            report_date=day, work_hours=8, status=status,
        )

    # 同じ現場・作業員・日付・工種は一意なので、同じ日に2件目は工種を変える
    other_wt = WorkType.unscoped.create(company=company_a, code="E02", name="弱電")
    return {
        "aug31": make(datetime.date(2026, 8, 31)),
        "sep01": make(datetime.date(2026, 9, 1)),
        "sep30": make(datetime.date(2026, 9, 30), status=DailyReport.Status.SUBMITTED),
        "sep30b": make(datetime.date(2026, 9, 30), wt=other_wt),
        "oct01": make(datetime.date(2026, 10, 1)),
    }


def _pks(res):
    return {r.pk for r in res.context["reports"]}


@pytest.mark.django_db
class TestReportListMonth:
    def test_指定した月の日報だけ出る_月の境目を含む(self, client, user_a, reports):
        client.force_login(user_a)
        res = client.get(reverse("reports:list") + "?month=2026-09")
        assert res.status_code == 200
        assert _pks(res) == {
            reports["sep01"].pk, reports["sep30"].pk, reports["sep30b"].pk,
        }

    def test_指定なしは全期間(self, client, user_a, reports):
        client.force_login(user_a)
        res = client.get(reverse("reports:list"))
        assert _pks(res) == {r.pk for r in reports.values()}
        assert res.context["selected_month"] == ""

    @pytest.mark.parametrize("value", ["abc", "2026-13", "2026", "-"])
    def test_読めない値はエラーにせず全期間(self, client, user_a, reports, value):
        client.force_login(user_a)
        res = client.get(reverse("reports:list") + f"?month={value}")
        assert res.status_code == 200
        assert len(res.context["reports"]) == len(reports)

    def test_状態と組み合わせられる(self, client, user_a, reports):
        client.force_login(user_a)
        res = client.get(reverse("reports:list") + "?month=2026-09&status=submitted")
        assert _pks(res) == {reports["sep30"].pk}

    def test_前月翌月は年をまたぐ(self, client, user_a, reports):
        client.force_login(user_a)
        res = client.get(reverse("reports:list") + "?month=2026-01")
        assert res.context["prev_query"] == "month=2025-12"
        assert res.context["next_query"] == "month=2026-02"

    def test_画面に月の欄と件数が出る(self, client, user_a, reports):
        client.force_login(user_a)
        body = client.get(reverse("reports:list") + "?month=2026-09").content.decode()
        assert 'name="month"' in body
        assert 'value="2026-09"' in body
        assert "2026年9月の日報: 3件" in body
        assert "?month=2026-08" in body and "?month=2026-10" in body
