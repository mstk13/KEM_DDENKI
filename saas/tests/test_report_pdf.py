"""日報の PDF 出力（ADR-0049）。

- 1 件の PDF: 中身（作業員・現場・作業内容など）が載る、日本語ファイル名、他社は 404
- 一覧の PDF: 絞り込み（月・状態）どおりの件数が 1 件 1 ページで入る、古い順
- 0 件・上限超えは PDF を作らず一覧に戻す
- 一覧と編集画面に PDF ボタンが出る
"""

import datetime
from io import BytesIO

import pdfplumber
import pytest
from django.urls import reverse

from apps.masters.models import Customer, WorkType
from apps.reports import views as report_views
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import Worker


@pytest.fixture
def data(company_a):
    customer = Customer.unscoped.create(company=company_a, code="C001", name="山陽建設株式会社")
    site = Site.unscoped.create(
        company=company_a, code="S001", name="A社ビル新築", customer=customer,
    )
    work_type = WorkType.unscoped.create(company=company_a, code="E01", name="電気幹線")
    other_type = WorkType.unscoped.create(company=company_a, code="E02", name="弱電")
    worker = Worker.unscoped.create(
        company=company_a, employee_code="E001", name="電工太郎", hourly_cost=3000,
    )

    def make(day, wt=work_type, **kw):
        values = dict(
            company=company_a, site=site, worker=worker, work_type=wt, report_date=day,
            start_time=datetime.time(8, 0), end_time=datetime.time(18, 0), work_hours=0,
            work_description="幹線ケーブル敷設\n分電盤結線", memo="雨のため午後は屋内",
        )
        values.update(kw)
        return DailyReport.unscoped.create(**values)

    return {
        "sep10": make(datetime.date(2026, 9, 10)),
        "sep02": make(datetime.date(2026, 9, 2), status=DailyReport.Status.SUBMITTED),
        "sep02b": make(
            datetime.date(2026, 9, 2), wt=other_type, work_description="<b>弱電</b> & 盤",
        ),
        "oct01": make(datetime.date(2026, 10, 1)),
    }


def _pages(res):
    assert res["Content-Type"] == "application/pdf"
    with pdfplumber.open(BytesIO(res.content)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


@pytest.mark.django_db
class TestSingleReportPdf:
    def test_中身が載る(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:pdf", args=[data["sep10"].pk]))
        assert res.status_code == 200
        pages = _pages(res)
        assert len(pages) == 1
        text = pages[0]
        for expected in ("作業日報", "2026年9月10日（木）", "電工太郎", "A社ビル新築",
                         "山陽建設株式会社", "電気幹線", "08:00 〜 18:00", "9.00 時間",
                         "幹線ケーブル敷設", "分電盤結線", "雨のため午後は屋内"):
            assert expected in text, expected

    def test_記号を含む作業内容もそのまま載る(self, client, user_a, data):
        client.force_login(user_a)
        text = _pages(client.get(reverse("reports:pdf", args=[data["sep02b"].pk])))[0]
        assert "<b>弱電</b> & 盤" in text

    def test_日本語のファイル名でブラウザ内に開く(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:pdf", args=[data["sep10"].pk]))
        disposition = res["Content-Disposition"]
        assert disposition.startswith("inline;")
        assert "filename*=utf-8''" in disposition
        # 「日報_2026-09-10_電工太郎.pdf」を URL エンコードしたもの
        assert "%E6%97%A5%E5%A0%B1_2026-09-10_" in disposition

    def test_他社の日報は404(self, client, user_b, data):
        client.force_login(user_b)
        res = client.get(reverse("reports:pdf", args=[data["sep10"].pk]))
        assert res.status_code == 404

    def test_ログインしていなければ出せない(self, client, data):
        res = client.get(reverse("reports:pdf", args=[data["sep10"].pk]))
        assert res.status_code == 302
        assert res["Content-Type"] != "application/pdf"


@pytest.mark.django_db
class TestListPdf:
    def test_月で絞った日報が1件1ページで古い順に入る(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:list_pdf") + "?month=2026-09")
        assert res.status_code == 200
        pages = _pages(res)
        assert len(pages) == 3
        assert "2026年9月2日" in pages[0]
        assert "2026年9月2日" in pages[1]
        assert "2026年9月10日" in pages[2]
        assert "%E6%97%A5%E5%A0%B1_2026-09.pdf" in res["Content-Disposition"]

    def test_状態でも絞れる(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:list_pdf") + "?month=2026-09&status=submitted")
        pages = _pages(res)
        assert len(pages) == 1
        assert "提出済" in pages[0]

    def test_指定なしは全期間(self, client, user_a, data):
        client.force_login(user_a)
        pages = _pages(client.get(reverse("reports:list_pdf")))
        assert len(pages) == 4

    def test_0件ならPDFを作らず一覧に戻す(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:list_pdf") + "?month=2025-01&status=draft")
        assert res.status_code == 302
        assert res.url == reverse("reports:list") + "?month=2025-01&status=draft"

    def test_上限を超えたらPDFを作らず一覧に戻す(self, client, user_a, data, monkeypatch):
        monkeypatch.setattr(report_views, "REPORT_PDF_MAX", 2)
        client.force_login(user_a)
        res = client.get(reverse("reports:list_pdf") + "?month=2026-09")
        assert res.status_code == 302
        assert res.url == reverse("reports:list") + "?month=2026-09"

    def test_他社の日報は入らない(self, client, user_b, data):
        client.force_login(user_b)
        res = client.get(reverse("reports:list_pdf"))
        assert res.status_code == 302


@pytest.mark.django_db
class TestPdfButtons:
    def test_一覧に行ごとのPDFと一覧のPDFボタンが出る(self, client, user_a, data):
        client.force_login(user_a)
        url = reverse("reports:list") + "?month=2026-09&status=submitted"
        body = client.get(url).content.decode()
        assert reverse("reports:pdf", args=[data["sep02"].pk]) in body
        assert reverse("reports:list_pdf") + "?month=2026-09&amp;status=submitted" in body

    def test_編集画面にPDFボタンが出る(self, client, user_a, data):
        client.force_login(user_a)
        body = client.get(reverse("reports:edit", args=[data["sep10"].pk])).content.decode()
        assert reverse("reports:pdf", args=[data["sep10"].pk]) in body
