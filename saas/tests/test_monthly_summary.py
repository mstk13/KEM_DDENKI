"""月次サマリ: 作業員一覧と同じ表記・並び順で、氏名の下にその月の承認済の日報一覧を出す。"""

from decimal import Decimal
from urllib.parse import urlencode

import pytest
from django.urls import reverse
from django.utils.html import escape

from apps.masters.models import WorkType
from apps.reports.models import DailyReport
from apps.reports.services import get_monthly_summary
from apps.sites.models import Site
from apps.workers.models import Worker

APPROVED = DailyReport.Status.APPROVED
SUBMITTED = DailyReport.Status.SUBMITTED
DRAFT = DailyReport.Status.DRAFT


@pytest.fixture
def site_a(company_a):
    return Site.unscoped.create(
        company=company_a, code="S001", name="A社ビル新築",
        status=Site.Status.IN_PROGRESS, contract_amount=5000000,
    )


@pytest.fixture
def work_type_a(company_a):
    return WorkType.unscoped.create(company=company_a, code="E01", name="電気幹線")


def _worker(company, code, name, **extra):
    return Worker.unscoped.create(
        company=company, employee_code=code, name=name, hourly_cost=3000, **extra,
    )


def _report(
    company, site, worker, work_type, day, *,
    status, hours="8.00", regular=None, overtime=None,
):
    extra = {}
    if regular is not None:
        extra["regular_hours"] = Decimal(regular)
    if overtime is not None:
        extra["overtime_hours"] = Decimal(overtime)
    return DailyReport.unscoped.create(
        company=company, site=site, worker=worker, work_type=work_type,
        report_date=day, work_hours=Decimal(hours), status=status, **extra,
    )


@pytest.mark.django_db
class TestGetMonthlySummary:
    def test_作業員一覧と同じ社員番号順に並ぶ(self, company_a, site_a, work_type_a):
        """Y→S→E→T→P→A→G の順、同じ接頭辞は番号順。名前順ではない。"""
        a1 = _worker(company_a, "A1", "あ")
        e10 = _worker(company_a, "E10", "い")
        e2 = _worker(company_a, "E2", "う")
        y1 = _worker(company_a, "Y1", "え")
        for w in (a1, e10, e2, y1):
            _report(company_a, site_a, w, work_type_a, "2026-09-01", status=APPROVED)

        rows = get_monthly_summary(company_a, 2026, 9)

        assert [r["worker"].employee_code for r in rows] == ["Y1", "E2", "E10", "A1"]

    def test_承認済の日報だけを集計し一覧にも承認済だけが並ぶ(
        self, company_a, site_a, work_type_a,
    ):
        w = _worker(company_a, "E1", "電工太郎")
        args = (company_a, site_a, w, work_type_a)
        approved1 = _report(
            *args, "2026-09-02", status=APPROVED, hours="8.00", regular="8.00", overtime="0.00",
        )
        approved2 = _report(
            *args, "2026-09-03", status=APPROVED, hours="10.00", regular="8.00", overtime="2.00",
        )
        # 下書き・提出済は集計にも一覧にも入らない
        _report(*args, "2026-09-01", status=DRAFT)
        _report(*args, "2026-09-04", status=SUBMITTED)
        # 別の月は入らない
        _report(*args, "2026-08-31", status=APPROVED)

        (row,) = get_monthly_summary(company_a, 2026, 9)

        assert row["work_days"] == 2
        assert row["total_hours"] == Decimal("18.00")
        assert row["total_regular"] == Decimal("16.00")
        assert row["total_overtime"] == Decimal("2.00")
        assert row["report_count"] == 2
        assert row["reports"] == [approved1, approved2]

    def test_承認前の日報しかない作業員は行に出ない(self, company_a, site_a, work_type_a):
        w = _worker(company_a, "E1", "電工太郎")
        _report(company_a, site_a, w, work_type_a, "2026-09-01", status=SUBMITTED)
        _report(company_a, site_a, w, work_type_a, "2026-09-02", status=DRAFT)

        assert get_monthly_summary(company_a, 2026, 9) == []

    def test_他社の日報は入らない(self, company_a, company_b, site_a, work_type_a):
        w_a = _worker(company_a, "E1", "電工太郎")
        _report(company_a, site_a, w_a, work_type_a, "2026-09-01", status=APPROVED)
        site_b = Site.unscoped.create(
            company=company_b, code="S001", name="B社",
            status=Site.Status.IN_PROGRESS, contract_amount=1,
        )
        wt_b = WorkType.unscoped.create(company=company_b, code="E01", name="電気")
        w_b = _worker(company_b, "E1", "他社の人")
        _report(company_b, site_b, w_b, wt_b, "2026-09-01", status=APPROVED)

        rows = get_monthly_summary(company_a, 2026, 9)

        assert [r["worker"] for r in rows] == [w_a]


@pytest.mark.django_db
class TestMonthlySummaryPage:
    def test_社員番号と氏名が出て承認済の日報だけ日報の画面へのリンクが並ぶ(
        self, client, user_a, company_a, site_a, work_type_a,
    ):
        w = _worker(company_a, "E1", "電工太郎")
        r1 = _report(company_a, site_a, w, work_type_a, "2026-09-01", status=APPROVED)
        r2 = _report(company_a, site_a, w, work_type_a, "2026-09-02", status=DRAFT)
        client.force_login(user_a)

        res = client.get(reverse("reports:monthly_summary"), {"year": 2026, "month": 9})

        assert res.status_code == 200
        html = res.content.decode()
        assert "<td>E1</td>" in html
        assert "電工太郎" in html
        assert f'data-worker-toggle="{w.pk}"' in html
        assert reverse("reports:edit", args=[r1.pk]) in html
        assert reverse("reports:edit", args=[r2.pk]) not in html
        # 日報のリンクには「この月・この作業員を開いた状態」に戻る next が付く
        back = f"/reports/monthly/?year=2026&month=9#worker-{w.pk}"
        link = reverse("reports:edit", args=[r1.pk]) + "?" + urlencode({"next": back})
        assert escape(link) in html

    def test_日報の保存と戻るで月次サマリの同じ作業員に戻る(
        self, client, user_a, company_a, site_a, work_type_a,
    ):
        w = _worker(company_a, "E1", "電工太郎")
        r1 = _report(company_a, site_a, w, work_type_a, "2026-09-01", status=APPROVED)
        client.force_login(user_a)
        back = f"/reports/monthly/?year=2026&month=9#worker-{w.pk}"
        edit_url = reverse("reports:edit", args=[r1.pk])

        res = client.get(edit_url, {"next": back})

        assert res.status_code == 200
        html = res.content.decode()
        # 属性値なので & は &amp; になる
        assert f'<input type="hidden" name="next" value="{escape(back)}">' in html
        assert f'href="{escape(back)}" class="btn btn-outline">戻る</a>' in html

        res = client.post(edit_url, {
            "site": site_a.name, "workers": [w.pk], "report_date": "2026-09-01",
            "weather": "", "process": "", "process_other": "",
            "work_type": work_type_a.name, "work_description": "",
            "start_date": "", "start_time": "", "end_date": "", "end_time": "",
            "work_hours": "8.00", "partner": "", "memo": "",
            "next": back,
        })

        assert res.status_code == 302
        assert res["Location"] == back

    def test_他サイトへの_nextは無視して一覧に戻る(
        self, client, user_a, company_a, site_a, work_type_a,
    ):
        w = _worker(company_a, "E1", "電工太郎")
        r1 = _report(company_a, site_a, w, work_type_a, "2026-09-01", status=APPROVED)
        client.force_login(user_a)

        res = client.get(reverse("reports:edit", args=[r1.pk]), {"next": "https://evil.example/"})

        assert res.status_code == 200
        html = res.content.decode()
        assert 'name="next"' not in html
        assert "キャンセル" in html

    def test_承認済の日報が無い月は空表示(self, client, user_a, company_a, site_a, work_type_a):
        w = _worker(company_a, "E1", "電工太郎")
        _report(company_a, site_a, w, work_type_a, "2026-09-01", status=SUBMITTED)
        client.force_login(user_a)

        res = client.get(reverse("reports:monthly_summary"), {"year": 2026, "month": 9})

        assert res.status_code == 200
        html = res.content.decode()
        assert "承認済の日報がありません" in html
        assert "電工太郎" not in html
