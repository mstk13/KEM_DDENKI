"""日報一覧を現場・作業員で絞り込む（ADR-0050）。

- ?site= / ?worker= で絞る。月・状態と組み合わせられる
- 読めない値は絞らない。他社の現場・作業員を指定しても他社の日報は出ない
- 選択肢は自社の日報に出てくる現場・作業員だけ（作業員は社員番号順）
- 前月・翌月・今月・すべての月・PDF のリンクは現場・作業員を引き継ぐ
- 一覧の PDF も同じ絞り込みで、ファイル名に現場名・作業員名が入る
"""

import datetime
from io import BytesIO

import pdfplumber
import pytest
from django.urls import reverse

from apps.masters.models import WorkType
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import Worker


@pytest.fixture
def data(company_a, company_b):
    wt = WorkType.unscoped.create(company=company_a, code="E01", name="電気")
    site_a = Site.unscoped.create(company=company_a, code="S001", name="A社ビル")
    site_b = Site.unscoped.create(company=company_a, code="S002", name="B倉庫")
    Site.unscoped.create(company=company_a, code="S003", name="日報の無い現場")
    taro = Worker.unscoped.create(
        company=company_a, employee_code="E002", name="電工太郎", hourly_cost=3000,
    )
    jiro = Worker.unscoped.create(
        company=company_a, employee_code="E001", name="電工次郎", hourly_cost=3000,
    )
    Worker.unscoped.create(
        company=company_a, employee_code="E003", name="日報の無い人", hourly_cost=3000,
    )

    def make(site, worker, day, **kw):
        return DailyReport.unscoped.create(
            company=company_a, site=site, worker=worker, work_type=wt,
            report_date=day, work_hours=8, **kw,
        )

    other_wt = WorkType.unscoped.create(company=company_b, code="E01", name="電気")
    other_site = Site.unscoped.create(company=company_b, code="S001", name="他社現場")
    other_worker = Worker.unscoped.create(
        company=company_b, employee_code="E001", name="他社の人", hourly_cost=3000,
    )
    other = DailyReport.unscoped.create(
        company=company_b, site=other_site, worker=other_worker, work_type=other_wt,
        report_date=datetime.date(2026, 9, 5), work_hours=8,
    )
    return {
        "site_a": site_a, "site_b": site_b, "taro": taro, "jiro": jiro,
        "a_taro_sep": make(site_a, taro, datetime.date(2026, 9, 1)),
        "a_jiro_sep": make(site_a, jiro, datetime.date(2026, 9, 2),
                           status=DailyReport.Status.SUBMITTED),
        "b_taro_sep": make(site_b, taro, datetime.date(2026, 9, 3)),
        "a_taro_oct": make(site_a, taro, datetime.date(2026, 10, 1)),
        "other_site": other_site, "other_worker": other_worker, "other": other,
    }


def _pks(res):
    return {r.pk for r in res.context["reports"]}


def _get(client, **params):
    from urllib.parse import urlencode

    return client.get(reverse("reports:list") + "?" + urlencode(params))


@pytest.mark.django_db
class TestFilter:
    def test_現場で絞る(self, client, user_a, data):
        client.force_login(user_a)
        res = _get(client, site=data["site_a"].pk)
        assert _pks(res) == {
            data["a_taro_sep"].pk, data["a_jiro_sep"].pk, data["a_taro_oct"].pk,
        }

    def test_作業員で絞る(self, client, user_a, data):
        client.force_login(user_a)
        res = _get(client, worker=data["taro"].pk)
        assert _pks(res) == {
            data["a_taro_sep"].pk, data["b_taro_sep"].pk, data["a_taro_oct"].pk,
        }

    def test_現場と作業員と月と状態を組み合わせる(self, client, user_a, data):
        client.force_login(user_a)
        res = _get(client, site=data["site_a"].pk, worker=data["taro"].pk, month="2026-09")
        assert _pks(res) == {data["a_taro_sep"].pk}
        res = _get(client, site=data["site_a"].pk, status="submitted")
        assert _pks(res) == {data["a_jiro_sep"].pk}

    @pytest.mark.parametrize("value", ["abc", "", "-1", "0"])
    def test_読めない値は絞らない(self, client, user_a, data, value):
        client.force_login(user_a)
        res = _get(client, site=value, worker=value)
        assert res.status_code == 200
        assert len(res.context["reports"]) == 4

    def test_他社の現場や作業員を指定しても他社の日報は出ない(self, client, user_a, data):
        client.force_login(user_a)
        assert _pks(_get(client, site=data["other_site"].pk)) == set()
        assert _pks(_get(client, worker=data["other_worker"].pk)) == set()


@pytest.mark.django_db
class TestChoicesAndLinks:
    def test_選択肢は日報に出てくる現場と作業員だけ(self, client, user_a, data):
        client.force_login(user_a)
        res = _get(client)
        assert [s.name for s in res.context["site_choices"]] == ["A社ビル", "B倉庫"]
        # 作業員一覧と同じ社員番号順（E001 次郎 → E002 太郎）
        assert [w.name for w in res.context["worker_choices"]] == ["電工次郎", "電工太郎"]

    def test_選んだ現場と作業員が選択された状態で出る(self, client, user_a, data):
        client.force_login(user_a)
        body = _get(client, site=data["site_b"].pk, worker=data["taro"].pk).content.decode()
        assert f'value="{data["site_b"].pk}" selected' in body
        assert f'value="{data["taro"].pk}" selected' in body

    def test_月送りと今月とPDFのリンクが現場と作業員を引き継ぐ(self, client, user_a, data):
        client.force_login(user_a)
        site, worker = data["site_a"].pk, data["taro"].pk
        res = _get(client, month="2026-09", site=site, worker=worker, status="draft")
        ctx = res.context
        assert ctx["prev_query"] == f"month=2026-08&status=draft&site={site}&worker={worker}"
        assert ctx["next_query"] == f"month=2026-10&status=draft&site={site}&worker={worker}"
        assert ctx["all_months_query"] == f"status=draft&site={site}&worker={worker}"
        assert ctx["this_month_query"].startswith("month=")
        assert f"site={site}&worker={worker}" in ctx["this_month_query"]
        assert ctx["list_pdf_query"] == f"month=2026-09&status=draft&site={site}&worker={worker}"
        body = res.content.decode()
        assert f"?month=2026-08&amp;status=draft&amp;site={site}&amp;worker={worker}" in body

    def test_件数の見出しに現場と作業員が入る(self, client, user_a, data):
        client.force_login(user_a)
        body = _get(
            client, month="2026-09", site=data["site_a"].pk, worker=data["taro"].pk,
        ).content.decode()
        assert "2026年9月・A社ビル・電工太郎の日報: 1件" in body


@pytest.mark.django_db
class TestListPdf:
    def test_PDFも現場と作業員で絞られファイル名に入る(self, client, user_a, data):
        client.force_login(user_a)
        url = reverse("reports:list_pdf") + f"?month=2026-09&site={data['site_a'].pk}"
        res = client.get(url)
        assert res.status_code == 200
        with pdfplumber.open(BytesIO(res.content)) as pdf:
            texts = [p.extract_text() or "" for p in pdf.pages]
        assert len(texts) == 2
        assert all("A社ビル" in t for t in texts)
        # 「日報_2026-09_A社ビル.pdf」を URL エンコードしたもの
        assert "_2026-09_A%E7%A4%BE%E3%83%93%E3%83%AB.pdf" in res["Content-Disposition"]

    def test_0件のときは現場と作業員を付けたまま一覧に戻す(self, client, user_a, data):
        client.force_login(user_a)
        site, worker = data["site_b"].pk, data["jiro"].pk
        res = client.get(reverse("reports:list_pdf") + f"?site={site}&worker={worker}")
        assert res.status_code == 302
        assert res.url == reverse("reports:list") + f"?site={site}&worker={worker}"
