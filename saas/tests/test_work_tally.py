"""作業日報集計（ADR-0105）。

紙の「作業日報集計フォーマット.xlsx」の 1 枚目と同じ形で、作業員ごと・月ごとに 1 日 1 行を出す。
1. 所定・早出・残業・深夜は Excel の数式と同じ（テストデータのシートの期待値で確かめる）
2. 行は承認済の日報から作る。1 日に現場が複数あれば 1 行にまとめる
3. 直した日は日報をあとから直しても書き換わらない。外した日は合計と PDF に入れない
4. 直せるのは社長・管理者と、管理者が付けた人。付け外しは社長・管理者だけ
5. 1 人分・全員分の PDF が出る
"""

from datetime import date, time
from decimal import Decimal
from io import BytesIO

import pdfplumber
import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.masters.models import WorkType
from apps.reports.models import (
    DailyReport,
    DailyReportMaterial,
    WorkTallyEditor,
    WorkTallyEntry,
    WorkTallySettings,
)
from apps.reports.work_tally import (
    build_sheet,
    can_edit_tally,
    column_labels,
    format_hm,
    get_tally_settings,
    split_minutes,
)
from apps.sites.models import Site
from apps.workers.models import Worker

APPROVED = DailyReport.Status.APPROVED


def _hm(text):
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


# ---------------------------------------------------------------------------
# 1. 計算（Excel の「テストデータ」シートの N 列の期待値）
# ---------------------------------------------------------------------------

EXCEL_CASES = [
    # 始業, 終業, 所定, 早出, 残業, 深夜, 内容
    ("8:00", "17:00", "7:00", "0:00", "0:00", "0:00", "通常勤務"),
    ("8:30", "17:30", "6:30", "0:00", "0:30", "0:00", "遅れて開始"),
    ("6:00", "17:00", "7:00", "2:00", "0:00", "0:00", "早出あり"),
    ("8:00", "20:00", "7:00", "0:00", "3:00", "0:00", "残業あり"),
    ("8:00", "23:30", "7:00", "0:00", "5:00", "1:30", "深夜まで"),
    ("7:00", "19:00", "7:00", "1:00", "2:00", "0:00", "早出＋残業"),
    ("20:00", "5:00", "0:00", "0:00", "2:00", "7:00", "夜間工事（日跨ぎ）"),
    ("13:00", "17:00", "3:30", "0:00", "0:00", "0:00", "午後のみ"),
    ("15:00", "16:30", "1:00", "0:00", "0:00", "0:00", "短時間"),
    ("18:00", "21:00", "0:00", "0:00", "3:00", "0:00", "夕方以降のみ"),
    ("10:15", "17:00", "5:00", "0:00", "0:00", "0:00", "休憩①の途中から開始"),
    ("9:00", "12:30", "2:30", "0:00", "0:00", "0:00", "昼休憩の途中で終了"),
]


def _time(text):
    hours, minutes = text.split(":")
    return time(int(hours), int(minutes))


class TestSplitMinutes:
    @pytest.mark.parametrize(
        ("start", "end", "regular", "early", "overtime", "night", "_label"),
        EXCEL_CASES, ids=[case[-1] for case in EXCEL_CASES],
    )
    def test_Excelのテストデータと同じになる(
        self, start, end, regular, early, overtime, night, _label,
    ):
        result = split_minutes(_time(start), _time(end), WorkTallySettings())

        assert result == {
            "regular": _hm(regular), "early": _hm(early),
            "overtime": _hm(overtime), "night": _hm(night),
        }

    def test_時刻の区切りと休憩は会社の設定で変わる(self):
        settings = WorkTallySettings(
            regular_end=time(18, 0), break1_start=None, break1_end=None,
            break3_start=None, break3_end=None,
        )

        result = split_minutes(time(8, 0), time(19, 0), settings)

        # 8～18時の 10 時間から昼休憩 1 時間だけ引く。18～19時は残業
        assert result == {"regular": 540, "early": 0, "overtime": 60, "night": 0}
        assert column_labels(settings)["regular"] == "所定（8-18）"

    def test_見出しはExcelと同じ(self):
        assert column_labels(WorkTallySettings()) == {
            "regular": "所定（8-17）", "early": "早出（～8時）",
            "overtime": "残業（～22時）", "night": "深夜（22時～）",
        }

    def test_時間はExcelと同じh_mm(self):
        assert format_hm(0) == "0:00"
        assert format_hm(3210) == "53:30"
        assert format_hm(None) == ""


# ---------------------------------------------------------------------------
# 2・3. 日報から 1 日 1 行を作る／手直し
# ---------------------------------------------------------------------------


@pytest.fixture
def site_a(company_a):
    return Site.unscoped.create(
        company=company_a, code="S001", name="A社ビル新築",
        status=Site.Status.IN_PROGRESS, contract_amount=5000000,
    )


@pytest.fixture
def site_a2(company_a):
    return Site.unscoped.create(
        company=company_a, code="S002", name="B工場改修",
        status=Site.Status.IN_PROGRESS, contract_amount=1000000,
    )


@pytest.fixture
def work_type_a(company_a):
    return WorkType.unscoped.create(company=company_a, code="E01", name="電気幹線")


@pytest.fixture
def worker_a(company_a):
    return Worker.unscoped.create(
        company=company_a, employee_code="E10", name="電工太郎", hourly_cost=3000,
    )


def _report(company, site, worker, work_type, day, start, end, *, status=APPROVED, **extra):
    return DailyReport.unscoped.create(
        company=company, site=site, worker=worker, work_type=work_type,
        report_date=day, start_time=_time(start), end_time=_time(end),
        work_hours=Decimal("8.00"), status=status, **extra,
    )


@pytest.mark.django_db
class TestBuildSheet:
    def test_承認済の日報から1日1行を作り合計を出す(
        self, company_a, site_a, worker_a, work_type_a,
    ):
        _report(company_a, site_a, worker_a, work_type_a, date(2026, 9, 1), "8:00", "17:00",
                work_description="幹線引込")
        _report(company_a, site_a, worker_a, work_type_a, date(2026, 9, 2), "8:00", "23:30")
        _report(company_a, site_a, worker_a, work_type_a, date(2026, 9, 3), "8:00", "17:00",
                status=DailyReport.Status.SUBMITTED)

        sheet = build_sheet(company_a, worker_a, 2026, 9)

        assert [row.day.day for row in sheet["rows"]] == [1, 2]  # 承認前の日報は入らない
        first = sheet["rows"][0]
        assert (first.weekday, first.start, first.end) == ("火", time(8), time(17))
        assert first.work_description == "幹線引込"
        assert first.site_names == "A社ビル新築"
        assert sheet["totals_hm"] == {
            "regular": "14:00", "early": "0:00", "overtime": "5:00", "night": "1:30",
        }
        assert sheet["total_all_hm"] == "20:30"

    def test_1日に現場が複数あれば1行にまとめる(
        self, company_a, site_a, site_a2, worker_a, work_type_a,
    ):
        day = date(2026, 9, 4)
        morning = _report(company_a, site_a, worker_a, work_type_a, day, "8:00", "12:00",
                          work_description="盤取付")
        _report(company_a, site_a2, worker_a, work_type_a, day, "13:00", "18:00",
                work_description="照明器具交換")
        DailyReportMaterial.unscoped.create(
            company=company_a, daily_report=morning, material_name="VVF2.0-3C",
            quantity_used=Decimal("30.00"), unit="m",
        )

        row = build_sheet(company_a, worker_a, 2026, 9)["rows"][0]

        assert (row.start, row.end) == (time(8), time(18))
        assert row.site_names == "A社ビル新築、B工場改修"
        assert row.work_description == "盤取付 / 照明器具交換"
        assert row.materials == "VVF2.0-3C 30m"

    def test_時刻の無い日報は時間を出さない(self, company_a, site_a, worker_a, work_type_a):
        DailyReport.unscoped.create(
            company=company_a, site=site_a, worker=worker_a, work_type=work_type_a,
            report_date=date(2026, 9, 5), work_hours=Decimal("8.00"), status=APPROVED,
        )

        sheet = build_sheet(company_a, worker_a, 2026, 9)

        assert sheet["rows"][0].has_times is False
        assert sheet["rows"][0].regular_hm == ""
        assert sheet["total_all"] == 0

    def test_直した日は日報をあとから直しても書き換わらない(
        self, company_a, site_a, worker_a, work_type_a,
    ):
        day = date(2026, 9, 1)
        report = _report(company_a, site_a, worker_a, work_type_a, day, "8:00", "17:00")
        WorkTallyEntry.unscoped.create(
            company=company_a, worker=worker_a, work_date=day,
            start_time=time(7, 0), end_time=time(17, 0), vehicle="ハイエース 12-34",
            site_names="A社ビル新築",
        )
        report.end_time = time(20, 0)
        report.save()

        row = build_sheet(company_a, worker_a, 2026, 9)["rows"][0]

        assert row.edited is True
        assert (row.start, row.end, row.vehicle) == (time(7), time(17), "ハイエース 12-34")
        assert row.early_hm == "1:00"

    def test_外した日は合計に入れない(self, company_a, site_a, worker_a, work_type_a):
        _report(company_a, site_a, worker_a, work_type_a, date(2026, 9, 1), "8:00", "17:00")
        _report(company_a, site_a, worker_a, work_type_a, date(2026, 9, 2), "8:00", "17:00")
        WorkTallyEntry.unscoped.create(
            company=company_a, worker=worker_a, work_date=date(2026, 9, 2),
            start_time=time(8), end_time=time(17), excluded=True,
        )

        sheet = build_sheet(company_a, worker_a, 2026, 9)

        assert [row.excluded for row in sheet["rows"]] == [False, True]
        assert sheet["totals_hm"]["regular"] == "7:00"

    def test_会社の設定が無ければExcelの初期値(self, company_a):
        settings = get_tally_settings(company_a)

        assert settings.pk is None
        assert (settings.regular_start, settings.regular_end, settings.night_start) == (
            time(8), time(17), time(22),
        )


# ---------------------------------------------------------------------------
# 4. 画面と権限
# ---------------------------------------------------------------------------


def _admin(company):
    return get_user_model().objects.create_superuser(
        username="tally_admin", password="x", company=company,
    )


def _link_worker(user, worker):
    worker.user = user
    worker.save(update_fields=["user"])
    user.refresh_from_db()


def _edit_url(worker, day):
    return reverse("reports:tally_entry_edit", args=[worker.pk, day.year, day.month, day.day])


@pytest.mark.django_db
class TestScreens:
    def test_集計表は誰でも見られるが直すボタンは出ない(
        self, client, user_a, company_a, site_a, worker_a, work_type_a,
    ):
        _report(company_a, site_a, worker_a, work_type_a, date(2026, 9, 1), "8:00", "17:00")
        client.force_login(user_a)

        res = client.get(
            reverse("reports:tally_sheet", args=[worker_a.pk]), {"year": 2026, "month": 9},
        )

        html = res.content.decode()
        assert res.status_code == 200
        assert "作業日報集計" in html and "所定（8-17）" in html and "7:00" in html
        assert "直す</a>" not in html

    def test_付けていない人は直せない(self, client, user_a, company_a, worker_a):
        client.force_login(user_a)

        res = client.get(_edit_url(worker_a, date(2026, 9, 1)))

        assert res.status_code == 403
        assert can_edit_tally(user_a) is False

    def test_付けた人は直せて手直しが残り履歴も付く(
        self, client, user_a, company_a, site_a, worker_a, work_type_a,
    ):
        day = date(2026, 9, 1)
        _report(company_a, site_a, worker_a, work_type_a, day, "8:00", "17:00")
        editor = Worker.unscoped.create(
            company=company_a, employee_code="E20", name="事務花子", hourly_cost=2000,
        )
        _link_worker(user_a, editor)
        WorkTallyEditor.unscoped.create(company=company_a, worker=editor)
        client.force_login(user_a)

        page = client.get(_edit_url(worker_a, day))
        res = client.post(_edit_url(worker_a, day), {
            "start_time": "07:30", "end_time": "17:00", "work_description": "盤取付",
            "materials": "", "vehicle": "軽トラ 1号", "site_names": "A社ビル新築",
        })

        assert page.status_code == 200
        assert "8:00～17:00" in page.content.decode()  # 日報から作った内容を並べて出す
        assert res.status_code == 302
        entry = WorkTallyEntry.unscoped.get(worker=worker_a, work_date=day)
        assert (entry.start_time, entry.vehicle) == (time(7, 30), "軽トラ 1号")
        assert entry.updated_by == user_a
        assert entry.history.count() == 1

    def test_始業だけでは保存できない(self, client, company_a, worker_a):
        client.force_login(_admin(company_a))

        res = client.post(_edit_url(worker_a, date(2026, 9, 1)), {
            "start_time": "08:00", "end_time": "",
        })

        assert res.status_code == 200
        assert "両方入れるか" in res.content.decode()
        assert not WorkTallyEntry.unscoped.exists()

    def test_日報の内容に戻すと手直しが消え_外すと合計から外れる(
        self, client, company_a, site_a, worker_a, work_type_a,
    ):
        day = date(2026, 9, 1)
        _report(company_a, site_a, worker_a, work_type_a, day, "8:00", "17:00")
        client.force_login(_admin(company_a))
        args = [worker_a.pk, 2026, 9, 1]

        client.post(reverse("reports:tally_entry_exclude", args=args))
        excluded = WorkTallyEntry.unscoped.get(worker=worker_a, work_date=day)
        client.post(reverse("reports:tally_entry_reset", args=args))

        assert excluded.excluded is True
        assert excluded.start_time == time(8)  # 日報の内容を控えてから外す
        assert not WorkTallyEntry.unscoped.exists()

    def test_日報の無い日を足せる(self, client, company_a, worker_a):
        client.force_login(_admin(company_a))

        res = client.get(
            reverse("reports:tally_add_day", args=[worker_a.pk]), {"date": "2026-09-06"},
        )

        assert res.status_code == 302
        assert res["Location"] == _edit_url(worker_a, date(2026, 9, 6))

    def test_他社の作業員の集計表は開けない(self, client, user_b, worker_a):
        client.force_login(user_b)

        res = client.get(reverse("reports:tally_sheet", args=[worker_a.pk]))

        assert res.status_code == 404

    def test_他社の手直しは入らない(self, company_a, company_b, worker_a):
        other = Worker.unscoped.create(
            company=company_b, employee_code="E10", name="他社太郎", hourly_cost=3000,
        )
        WorkTallyEntry.unscoped.create(
            company=company_b, worker=other, work_date=date(2026, 9, 1),
            start_time=time(8), end_time=time(17),
        )

        assert build_sheet(company_a, worker_a, 2026, 9)["rows"] == []


@pytest.mark.django_db
class TestEditors:
    def test_社長管理者は付け外しできる(self, client, company_a, worker_a):
        client.force_login(_admin(company_a))

        page = client.get(reverse("reports:tally_editors"))
        client.post(reverse("reports:tally_editor_grant", args=[worker_a.pk]))
        granted = WorkTallyEditor.unscoped.filter(worker=worker_a).exists()
        client.post(reverse("reports:tally_editor_revoke", args=[worker_a.pk]))

        assert page.status_code == 200
        assert "電工太郎" in page.content.decode()
        assert granted is True
        assert not WorkTallyEditor.unscoped.filter(worker=worker_a).exists()

    def test_管理者でない人は付け外しも設定もできない(self, client, user_a, worker_a):
        client.force_login(user_a)

        assert client.get(reverse("reports:tally_editors")).status_code == 403
        assert client.post(
            reverse("reports:tally_editor_grant", args=[worker_a.pk]),
        ).status_code == 403
        assert client.get(reverse("reports:tally_settings")).status_code == 403
        assert not WorkTallyEditor.unscoped.exists()

    def test_社員番号Yの管理者は付けなくても直せる(self, user_a, company_a):
        admin_worker = Worker.unscoped.create(
            company=company_a, employee_code="Y1", name="管理者", hourly_cost=3000,
        )
        _link_worker(user_a, admin_worker)

        assert can_edit_tally(user_a) is True

    def test_他社の作業員には付けられない(self, client, company_a, company_b):
        other = Worker.unscoped.create(
            company=company_b, employee_code="E10", name="他社太郎", hourly_cost=3000,
        )
        client.force_login(_admin(company_a))

        res = client.post(reverse("reports:tally_editor_grant", args=[other.pk]))

        assert res.status_code == 404
        assert not WorkTallyEditor.unscoped.exists()

    def test_時間の区切りを保存できる(self, client, company_a):
        client.force_login(_admin(company_a))
        data = {
            "regular_start": "08:30", "regular_end": "17:30", "night_start": "22:00",
            "break1_start": "", "break1_end": "",
            "break2_start": "12:00", "break2_end": "13:00",
            "break3_start": "", "break3_end": "",
        }

        res = client.post(reverse("reports:tally_settings"), data)

        saved = WorkTallySettings.unscoped.get(company=company_a)
        assert res.status_code == 302
        assert (saved.regular_start, saved.breaks()) == (time(8, 30), [(time(12), time(13))])

    def test_区切りの順が逆なら保存しない(self, client, company_a):
        client.force_login(_admin(company_a))

        res = client.post(reverse("reports:tally_settings"), {
            "regular_start": "18:00", "regular_end": "17:00", "night_start": "22:00",
        })

        assert res.status_code == 200
        assert not WorkTallySettings.unscoped.exists()

    def test_月次サマリに集計表とPDFの入口が出る(
        self, client, user_a, company_a, site_a, worker_a, work_type_a,
    ):
        _report(company_a, site_a, worker_a, work_type_a, date(2026, 9, 1), "8:00", "17:00")
        client.force_login(user_a)

        html = client.get(
            reverse("reports:monthly_summary"), {"year": 2026, "month": 9},
        ).content.decode()

        assert reverse("reports:tally_sheet", args=[worker_a.pk]) in html
        assert "作業日報集計 PDF（全員分）" in html
        assert "集計表を直せる人" not in html  # 付け外しは社長・管理者だけ


# ---------------------------------------------------------------------------
# 5. PDF
# ---------------------------------------------------------------------------


def _pdf_text(content):
    """PDF の文字を空白を詰めて返す。

    日本語フォントの「～」（全角チルダ）は読み取ると「〜」（波ダッシュ）になるので戻す。
    """
    with pdfplumber.open(BytesIO(content)) as pdf:
        text = "".join((page.extract_text() or "") for page in pdf.pages)
    return text.replace(" ", "").replace("〜", "～")


@pytest.mark.django_db
class TestPdf:
    def test_1人分のPDFにExcelと同じ見出しと合計が出る(
        self, client, user_a, company_a, site_a, worker_a, work_type_a,
    ):
        _report(company_a, site_a, worker_a, work_type_a, date(2026, 9, 1), "8:00", "23:30",
                work_description="幹線引込")
        WorkTallyEntry.unscoped.create(
            company=company_a, worker=worker_a, work_date=date(2026, 9, 2),
            start_time=time(20), end_time=time(5), vehicle="ハイエース", site_names="夜間現場",
        )
        client.force_login(user_a)

        res = client.get(
            reverse("reports:tally_pdf", args=[worker_a.pk]), {"year": 2026, "month": 9},
        )

        text = _pdf_text(res.content)
        assert res["Content-Type"] == "application/pdf"
        for word in (
            "作業日報集計", "令和8年9月", "電工太郎", "作業者名", "労働時間（実労働時間）",
            # 所定・早出・残業・深夜の見出しは「所定」と「（8-17）」の 2 行
            "所定早出残業深夜", "（8-17）（～8時）（～22時）（22時～）",
            "令和8年9月1日", "幹線引込", "ハイエース",
            "夜間現場", "合計", "実労働時間計22:30",
        ):
            assert word in text, word

    def test_全員分のPDFは1人1枚(self, client, user_a, company_a, site_a, work_type_a):
        for code, name in (("E1", "一郎"), ("E2", "二郎")):
            worker = Worker.unscoped.create(
                company=company_a, employee_code=code, name=name, hourly_cost=3000,
            )
            _report(company_a, site_a, worker, work_type_a, date(2026, 9, 1), "8:00", "17:00")
        client.force_login(user_a)

        res = client.get(reverse("reports:tally_pdf_all"), {"year": 2026, "month": 9})

        with pdfplumber.open(BytesIO(res.content)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        assert len(pages) == 2
        assert "一郎" in pages[0] and "二郎" in pages[1]

    def test_載せる日が無い月は月次サマリに戻る(self, client, user_a):
        client.force_login(user_a)

        res = client.get(reverse("reports:tally_pdf_all"), {"year": 2026, "month": 9})

        assert res.status_code == 302


def test_管理画面に登録してある():
    for model in (WorkTallySettings, WorkTallyEntry, WorkTallyEditor):
        assert model in admin.site._registry
