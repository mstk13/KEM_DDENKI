"""日報一覧を日付（1 日）で絞り込む（ADR-0060）。

- ?date=YYYY-MM-DD でその日の日報だけ。月と両方あれば日付を優先する
- 読めない日付は絞らない
- 前日・翌日は月をまたいで動き、現場・作業員・状態を引き継ぐ
- 見出しは「2026年9月14日（月）」。今月・今日・すべての月・日付を外すのリンク
- 一覧の PDF も同じ日付で、ファイル名に日付が入る
"""

import datetime
from io import BytesIO
from urllib.parse import urlencode

import pdfplumber
import pytest
from django.urls import reverse
from django.utils import timezone

from apps.masters.models import WorkType
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import Worker


@pytest.fixture
def data(company_a):
    wt = WorkType.unscoped.create(company=company_a, code="E01", name="電気")
    site = Site.unscoped.create(company=company_a, code="S001", name="A社ビル")
    worker = Worker.unscoped.create(
        company=company_a, employee_code="E001", name="電工太郎", hourly_cost=3000,
    )

    def make(day, **kw):
        return DailyReport.unscoped.create(
            company=company_a, site=site, worker=worker, work_type=wt,
            report_date=day, work_hours=8, **kw,
        )

    return {
        "site": site, "worker": worker,
        "sep13": make(datetime.date(2026, 9, 13)),
        "sep14": make(datetime.date(2026, 9, 14)),
        "sep30": make(datetime.date(2026, 9, 30), status=DailyReport.Status.SUBMITTED),
        "oct01": make(datetime.date(2026, 10, 1)),
    }


def _get(client, **params):
    return client.get(reverse("reports:list") + "?" + urlencode(params))


def _pks(res):
    return {r.pk for r in res.context["reports"]}


@pytest.mark.django_db
class TestDateFilter:
    def test_その日の日報だけ出る(self, client, user_a, data):
        client.force_login(user_a)
        res = _get(client, date="2026-09-14")
        assert _pks(res) == {data["sep14"].pk}
        assert "2026年9月14日（月）の日報: 1件" in res.content.decode()

    def test_月と日付の両方なら日付を優先する(self, client, user_a, data):
        client.force_login(user_a)
        res = _get(client, month="2026-10", date="2026-09-14")
        assert _pks(res) == {data["sep14"].pk}
        assert res.context["selected_month"] == ""
        assert res.context["selected_date"] == "2026-09-14"

    @pytest.mark.parametrize("value", ["abc", "2026-02-30", "2026-9"])
    def test_読めない日付は絞らない(self, client, user_a, data, value):
        client.force_login(user_a)
        res = _get(client, date=value)
        assert res.status_code == 200
        assert len(res.context["reports"]) == 4

    def test_状態や現場と組み合わせられる(self, client, user_a, data):
        client.force_login(user_a)
        res = _get(client, date="2026-09-30", status="submitted", site=data["site"].pk)
        assert _pks(res) == {data["sep30"].pk}
        assert not _pks(_get(client, date="2026-09-30", status="draft"))


@pytest.mark.django_db
class TestDateLinks:
    def test_前日翌日は月をまたぎ他の絞り込みを引き継ぐ(self, client, user_a, data):
        client.force_login(user_a)
        worker = data["worker"].pk
        ctx = _get(client, date="2026-09-30", worker=worker).context
        assert ctx["next_day_query"] == f"date=2026-10-01&worker={worker}"
        assert ctx["prev_day_query"] == f"date=2026-09-29&worker={worker}"
        body = _get(client, date="2026-10-01").content.decode()
        assert "?date=2026-09-30" in body and "?date=2026-10-02" in body

    def test_今月は日付を外し_今日は月を外す(self, client, user_a, data):
        client.force_login(user_a)
        today = timezone.localdate()
        ctx = _get(client, date="2026-09-14", status="draft").context
        assert ctx["this_month_query"] == f"month={today:%Y-%m}&status=draft"
        assert ctx["clear_date_query"] == "status=draft"
        ctx = _get(client, month="2026-09").context
        assert ctx["today_query"] == f"date={today.isoformat()}"
        assert ctx["all_months_query"] == ""

    def test_画面に日付の欄と切り替えのリンクが出る(self, client, user_a, data):
        client.force_login(user_a)
        # 実行する日に左右されないよう、今日ではない日（昨日）で見る
        yesterday = (timezone.localdate() - datetime.timedelta(days=1)).isoformat()
        body = _get(client, date=yesterday).content.decode()
        assert 'name="date"' in body and f'value="{yesterday}"' in body
        assert "前日" in body and "翌日" in body and "日付を外す" in body
        assert ">今日</a>" in body
        # 今日を見ているときは「今日」のリンクを出さない
        today_body = _get(client, date=timezone.localdate().isoformat()).content.decode()
        assert ">今日</a>" not in today_body
        # 月を選んだら日付を空にする（逆も）
        assert "if (month.value) day.value = ''" in body

    def test_現場作業員を外すは期間を残す(self, client, user_a, data):
        client.force_login(user_a)
        ctx = _get(client, date="2026-09-14", site=data["site"].pk, status="draft").context
        assert ctx["clear_site_worker_query"] == "date=2026-09-14"


@pytest.mark.django_db
class TestDateListPdf:
    def test_一覧のPDFも日付で絞りファイル名に日付が入る(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:list_pdf") + "?date=2026-09-14")
        assert res.status_code == 200
        with pdfplumber.open(BytesIO(res.content)) as pdf:
            texts = ["".join((p.extract_text() or "").split()) for p in pdf.pages]
        assert len(texts) == 1
        assert "令和8年9月14日" in texts[0]
        assert "_2026-09-14.pdf" in res["Content-Disposition"]

    def test_0件なら日付を付けたまま一覧に戻す(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:list_pdf") + "?date=2026-09-01")
        assert res.status_code == 302
        assert res.url == reverse("reports:list") + "?date=2026-09-01"
