"""日報の詳細画面と、作業時間だけの日報の時間表示（ADR-0054）。

- 一覧の行（と日付）から詳細を開ける。詳細の「一覧に戻る」は一覧の絞り込みを保つ
- 詳細に作業員・現場・時間・作業内容・材料などが出る。他社は 404、ログイン必須
- 承認ボタンは承認できる人・提出済のときだけ、削除は削除できるときだけ
- 開始・終了が無く作業時間だけの日報は、通常・残業を作業時間から出す（保存値は変えない）
- PDF でも作業時間だけの日報に「作業時間」と「残業」が入る
"""

import datetime
from decimal import Decimal
from io import BytesIO
from urllib.parse import quote

import pdfplumber
import pytest
from django.urls import reverse

from apps.masters.models import Customer, WorkType
from apps.reports.models import DailyReport, DailyReportMaterial
from apps.sites.models import Site
from apps.workers.models import Worker


@pytest.fixture
def data(company_a):
    customer = Customer.unscoped.create(company=company_a, code="C001", name="山陽建設株式会社")
    site = Site.unscoped.create(
        company=company_a, code="S001", name="A社ビル新築", customer=customer,
    )
    wt = WorkType.unscoped.create(company=company_a, code="E01", name="電気幹線")
    worker = Worker.unscoped.create(
        company=company_a, employee_code="E001", name="電工太郎", hourly_cost=3000,
    )
    timed = DailyReport.unscoped.create(
        company=company_a, site=site, worker=worker, work_type=wt,
        report_date=datetime.date(2026, 9, 10), weather="sunny",
        start_time=datetime.time(8, 0), end_time=datetime.time(19, 30), work_hours=0,
        work_description="幹線ケーブル敷設\n分電盤結線", memo="雨のため午後は屋内",
        status=DailyReport.Status.SUBMITTED,
    )
    DailyReportMaterial.unscoped.create(
        company=company_a, daily_report=timed, material_name="CVケーブル 60sq",
        quantity_used="45.00", unit="m",
    )
    wt2 = WorkType.unscoped.create(company=company_a, code="E02", name="弱電")
    hours_only = DailyReport.unscoped.create(
        company=company_a, site=site, worker=worker, work_type=wt2,
        report_date=datetime.date(2026, 9, 11), work_hours=Decimal("10.00"),
        work_description="LAN配線",
    )
    short = DailyReport.unscoped.create(
        company=company_a, site=site, worker=worker, work_type=wt,
        report_date=datetime.date(2026, 9, 12), work_hours=Decimal("6.50"),
        work_description="片付け",
    )
    return {"timed": timed, "hours_only": hours_only, "short": short}


@pytest.mark.django_db
class TestHoursBreakdown:
    def test_開始終了があれば保存時の計算値(self, data):
        assert data["timed"].hours_breakdown() == (
            Decimal("10.50"), Decimal("8.00"), Decimal("2.50"),
        )

    def test_作業時間だけなら8時間を超えた分が残業(self, data):
        assert data["hours_only"].hours_breakdown() == (
            Decimal("10.00"), Decimal("8.00"), Decimal("2.00"),
        )

    def test_8時間以下なら残業0(self, data):
        assert data["short"].hours_breakdown() == (
            Decimal("6.50"), Decimal("6.50"), Decimal("0.00"),
        )

    def test_保存値は変えない(self, data):
        report = DailyReport.unscoped.get(pk=data["hours_only"].pk)
        report.hours_breakdown()
        assert report.overtime_hours == Decimal("0.00")
        assert report.regular_hours is None


@pytest.mark.django_db
class TestDetailPage:
    def test_詳細に中身が出る(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:detail", args=[data["timed"].pk]))
        assert res.status_code == 200
        body = res.content.decode()
        for expected in ("電工太郎", "A社ビル新築", "山陽建設株式会社", "電気幹線", "晴",
                         "08:00 〜 19:30", "10.5 時間", "8 時間", "2.5 時間",
                         "幹線ケーブル敷設", "分電盤結線", "CVケーブル 60sq", "45",
                         "雨のため午後は屋内",
                         "提出済"):
            assert expected in body, expected

    def test_作業時間だけの日報は通常と残業を作業時間から出す(self, client, user_a, data):
        client.force_login(user_a)
        url = reverse("reports:detail", args=[data["hours_only"].pk])
        body = client.get(url).content.decode()
        assert "10 時間" in body and "8 時間" in body and "2 時間" in body
        assert "作業時間から計算しています" in body

    def test_他社は404_ログインしていなければ出せない(self, client, user_b, data):
        url = reverse("reports:detail", args=[data["timed"].pk])
        assert client.get(url).status_code == 302
        client.force_login(user_b)
        assert client.get(url).status_code == 404

    def test_編集とPDFのボタン_戻るは絞り込みを保つ(self, client, user_a, data):
        client.force_login(user_a)
        back = "/reports/?month=2026-09&status=submitted"
        url = reverse("reports:detail", args=[data["timed"].pk]) + "?next=" + quote(back)
        body = client.get(url).content.decode()
        assert reverse("reports:edit", args=[data["timed"].pk]) in body
        assert reverse("reports:pdf", args=[data["timed"].pk]) in body
        assert 'href="/reports/?month=2026-09&amp;status=submitted"' in body

    def test_外部のnextは使わない(self, client, user_a, data):
        client.force_login(user_a)
        url = reverse("reports:detail", args=[data["timed"].pk]) + "?next=https://evil.example/"
        body = client.get(url).content.decode()
        assert "evil.example" not in body

    def test_承認ボタンは承認できる人の提出済だけ(self, client, user_a, data, company_a):
        from apps.workers.models import Position

        client.force_login(user_a)
        url = reverse("reports:detail", args=[data["timed"].pk])
        # 一般のユーザーには出ない
        approve = reverse("reports:approve", args=[data["timed"].pk])
        assert approve not in client.get(url).content.decode()
        # 役職 Developer（承認できる。ADR-0039）には提出済のとき出る
        position = Position.unscoped.create(company=company_a, name="Developer", rank=8)
        Worker.unscoped.create(
            company=company_a, employee_code="G001", name="開発", hourly_cost=0,
            user=user_a, position=position,
        )
        user_a.refresh_from_db()
        assert approve in client.get(url).content.decode()
        # 下書きには出ない
        draft = reverse("reports:detail", args=[data["short"].pk])
        approve_draft = reverse("reports:approve", args=[data["short"].pk])
        assert approve_draft not in client.get(draft).content.decode()


@pytest.mark.django_db
class TestListRowsOpenDetail:
    def test_一覧の行と日付から詳細を開ける(self, client, user_a, data):
        client.force_login(user_a)
        body = client.get(reverse("reports:list") + "?month=2026-09").content.decode()
        detail = reverse("reports:detail", args=[data["timed"].pk])
        assert f'data-href="{detail}?next=' in body
        assert f'<a href="{detail}?next=' in body
        # 一覧の絞り込みを next に入れる
        assert "next=/reports/%3Fmonth%3D2026-09" in body


@pytest.mark.django_db
class TestPdfHoursOnly:
    def test_作業時間だけの日報もPDFに作業時間と残業が入る(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:pdf", args=[data["hours_only"].pk]))
        with pdfplumber.open(BytesIO(res.content)) as pdf:
            text = "".join((pdf.pages[0].extract_text() or "").split())
        # 作業時間（所定始業の既定 08:00 から 10 時間＋休憩 1 時間）・通常時間・残業時間
        # PDF から読むと「～」は波ダッシュ「〜」になるので揃える
        assert "電工太郎08:00～19:008h2h" in text.replace("〜", "～")

    def test_8時間以下は残業0h(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:pdf", args=[data["short"].pk]))
        with pdfplumber.open(BytesIO(res.content)) as pdf:
            text = "".join((pdf.pages[0].extract_text() or "").split())
        # 7 時間以下は休憩を含めない（保存時の計算と同じ）
        assert "電工太郎08:00～14:306.5h0h" in text.replace("〜", "～")

    def test_所定始業が0830なら8時間は0830から1730(self, client, user_a, data, company_a):
        from apps.attendance.models import AttendSettings

        AttendSettings.unscoped.create(company=company_a, key="standard_start", value="08:30")
        report = data["short"]
        for hours, expected in (("8.00", "08:30～17:30"), ("9.50", "08:30～19:00")):
            report.work_hours = hours
            report.save()
            client.force_login(user_a)
            res = client.get(reverse("reports:pdf", args=[report.pk]))
            with pdfplumber.open(BytesIO(res.content)) as pdf:
                text = "".join((pdf.pages[0].extract_text() or "").split()).replace("〜", "～")
            assert expected in text, (hours, expected)
            # 見出しの「作業時間・通常時間・残業時間」以外に「○時間」の表記が残っていない
            rest = text.replace("作業時間", "").replace("通常時間", "").replace("残業時間", "")
            assert "時間" not in rest
