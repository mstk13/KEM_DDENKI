"""日報の PDF 出力（ADR-0049、様式は原本に合わせる ADR-0053）。

- 1 枚＝同じ日・同じ現場。現場名・発注先・令和の年月日・曜日・作業員ごとの作業時間と残業
- 年月日の右に天候、その下の行に工種・工程
- 作業内容の枠に作業内容・その他を書く（使用材料は書かない）
- 自社の作業員は 9 行（作業員名・作業時間 8:30～17:30・通常時間・残業時間・宿泊）
- 作業内容は作業員の表の下に横幅いっぱい。交通手段の行は 1 つ（台数・交通費の空欄つき）
- 現場代理人は左、氏名は右
- 承認済みの日報には「釼持」の承認印を押す
- 協力会社の作業員は協力会社の欄に会社名・人数つきで出る
- 自社 10 人以上は次の用紙に続く。長い作業内容は枠に収める（入らなければ以下略）
- 1 件の PDF ボタンは同じ日・同じ現場の日報をまとめた 1 枚。他社は 404
- 一覧の PDF: 絞り込みどおり、同じ日・同じ現場ごとに 1 枚、古い順
- 0 件・上限超えは PDF を作らず一覧に戻す。一覧と編集画面に PDF ボタンが出る
"""

import datetime
from io import BytesIO

import pdfplumber
import pytest
from django.urls import reverse

from apps.masters.models import Customer, Supplier, WorkType
from apps.reports import views as report_views
from apps.reports.models import DailyReport, DailyReportMaterial
from apps.sites.models import Process, Site
from apps.workers.models import Worker


@pytest.fixture
def data(company_a):
    customer = Customer.unscoped.create(company=company_a, code="C001", name="山陽建設株式会社")
    site = Site.unscoped.create(
        company=company_a, code="S001", name="A社ビル新築", customer=customer,
    )
    site_b = Site.unscoped.create(company=company_a, code="S002", name="B倉庫")
    work_type = WorkType.unscoped.create(company=company_a, code="E01", name="電気幹線")
    other_type = WorkType.unscoped.create(company=company_a, code="E02", name="弱電")
    taro = Worker.unscoped.create(
        company=company_a, employee_code="E002", name="電工太郎", hourly_cost=3000,
    )
    jiro = Worker.unscoped.create(
        company=company_a, employee_code="E001", name="電工次郎", hourly_cost=3000,
    )

    def make(day, worker=taro, wt=work_type, s=site, **kw):
        values = dict(
            company=company_a, site=s, worker=worker, work_type=wt, report_date=day,
            start_time=datetime.time(8, 0), end_time=datetime.time(18, 0), work_hours=0,
            work_description="幹線ケーブル敷設\n分電盤結線", memo="雨のため午後は屋内",
        )
        values.update(kw)
        return DailyReport.unscoped.create(**values)

    return {
        "site": site, "site_b": site_b, "taro": taro, "jiro": jiro,
        "work_type": work_type, "other_type": other_type, "make": make,
        # 9/10 A社ビル: 太郎と次郎（同じ内容）→ 1 枚
        "sep10": make(datetime.date(2026, 9, 10), weather="sunny",
                      end_time=datetime.time(19, 30)),
        "sep10_jiro": make(datetime.date(2026, 9, 10), worker=jiro),
        # 9/2 A社ビル: 太郎（提出済・電気幹線）＋ 太郎（弱電）→ 1 枚
        "sep02": make(datetime.date(2026, 9, 2), status=DailyReport.Status.SUBMITTED),
        "sep02b": make(
            datetime.date(2026, 9, 2), wt=other_type, work_description="<b>弱電</b> & 盤",
        ),
        # 9/2 B倉庫 → 別の 1 枚
        "sep02_b": make(datetime.date(2026, 9, 2), s=site_b, work_description="照明交換"),
        "oct01": make(datetime.date(2026, 10, 1)),
    }


def _pages(res):
    assert res["Content-Type"] == "application/pdf"
    with pdfplumber.open(BytesIO(res.content)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def _flat(text):
    """PDF から読んだ文字の空白・改行を詰める（様式の字間や折り返しに左右されないように）。

    全角チルダ「～」は PDF から読むと波ダッシュ「〜」になるので「～」に揃える（見た目は同じ）。
    """
    return "".join(text.split()).replace("〜", "～")


@pytest.mark.django_db
class TestSheetContents:
    def test_原本の見出しと作業員ごとの時間が載る(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:pdf", args=[data["sep10"].pk]))
        assert res.status_code == 200
        pages = _pages(res)
        assert len(pages) == 1
        text = _flat(pages[0])
        for expected in ("作業日報", "現場名", "A社ビル新築", "発注先", "山陽建設株式会社",
                         "令和8年9月10日木曜日", "作業員名", "作業時間", "通常時間", "残業時間",
                         "宿泊", "作業内容", "電工太郎", "電工次郎",
                         # 次郎 8:00～18:00・通常 8h・残業 1h
                         # 太郎 8:00～19:30・通常 8h・残業 2.5h
                         "電工次郎8:00～18:008h1h", "電工太郎8:00～19:308h2.5h",
                         "合計2人", "交通手段等", "会社名", "承認印", "現場代理人又は責任者"):
            assert expected in text, expected
        # 交通手段の行は 1 つ（協力会社の欄には置かない）
        assert text.count("交通手段") == 1
        assert text.count("乗合") == 1
        # 作業時間は時の前に 0 を付けない
        assert "08:00" not in text
        # 作業内容の欄は作業員の表（合計）の下、交通手段の行の上
        assert text.index("合計2人") < text.index("幹線ケーブル敷設") < text.index("交通手段等")
        assert "作業内容・使用材料" not in text
        # 自社の作業員の行は 9 行（空の行の「：～：」は 2 人ぶんを除いた 7 つ）
        assert text.count("：～：") == 7

    def test_同じ日同じ現場の作業員は社員番号順に1枚に並ぶ(self, client, user_a, data):
        client.force_login(user_a)
        text = _pages(client.get(reverse("reports:pdf", args=[data["sep10_jiro"].pk])))[0]
        # E001 次郎 → E002 太郎
        assert text.index("電工次郎") < text.index("電工太郎")

    def test_天候と工種工程の位置_材料は書かない(self, client, user_a, data, company_a):
        report = data["sep10"]
        process = Process.unscoped.create(
            company=company_a, site=report.site, work_type=report.work_type, name="施工",
        )
        # 同じ日の次郎の日報も同じ工種・工程・作業内容にして、重ねて書かないことを確かめる
        for r in (report, data["sep10_jiro"]):
            r.process = process
            r.save()
        for name, qty, unit in (("CVケーブル 60sq", "45.00", "m"), ("圧着端子", "12.50", "個")):
            DailyReportMaterial.unscoped.create(
                company=company_a, daily_report=report, material_name=name,
                quantity_used=qty, unit=unit,
            )
        client.force_login(user_a)
        text = _flat(_pages(client.get(reverse("reports:pdf", args=[report.pk])))[0])
        for expected in ("日木曜日天候晴", "工種電気幹線工程施工",
                         "幹線ケーブル敷設", "分電盤結線", "その他:雨のため午後は屋内"):
            assert expected in text, expected
        # 使用材料は書かない
        assert "使用材料:" not in text
        assert "CVケーブル" not in text and "圧着端子" not in text
        # 同じ作業内容の次郎の分は重ねて書かない
        assert text.count("幹線ケーブル敷設") == 1
        # 天候・工種・工程は見出しに出すので、枠に【】見出しや「天候:」は書かない
        assert "【" not in text
        assert "天候:" not in text

    def test_記号を含む作業内容もそのまま載る(self, client, user_a, data):
        client.force_login(user_a)
        text = _flat(_pages(client.get(reverse("reports:pdf", args=[data["sep02b"].pk])))[0])
        assert "<b>弱電</b>&盤" in text
        # 工種の違う日報が同じ用紙に混ざるときは、見出しは両方を並べ、枠には【】を付けて分ける
        assert "工種電気幹線・弱電" in text
        assert "【弱電】" in text and "【電気幹線】" in text

    def test_協力会社の作業員は協力会社の欄に出る(self, client, user_a, data, company_a):
        supplier = Supplier.unscoped.create(company=company_a, code="P001", name="山田電設")
        helper = Worker.unscoped.create(
            company=company_a, employee_code="W001", name="応援一郎", hourly_cost=0,
        )
        data["make"](datetime.date(2026, 9, 10), worker=helper, is_partner_worker=True,
                     partner=supplier, work_description="照明器具取付")
        client.force_login(user_a)
        text = _flat(_pages(client.get(reverse("reports:pdf", args=[data["sep10"].pk])))[0])
        assert "山田電設" in text and "応援一郎" in text and "照明器具取付" in text
        # 自社の合計は 2 人のまま、協力会社は 1 人
        assert "合計2人" in text
        assert "1人" in text

    def test_自社10人以上は次の用紙に続く(self, client, user_a, data, company_a):
        day = datetime.date(2026, 9, 20)
        first = None
        for i in range(10):
            worker = Worker.unscoped.create(
                company=company_a, employee_code=f"E{100 + i}", name=f"作業員{i:02d}",
                hourly_cost=3000,
            )
            report = data["make"](day, worker=worker)
            first = first or report
        client.force_login(user_a)
        pages = _pages(client.get(reverse("reports:pdf", args=[first.pk])))
        assert len(pages) == 2
        assert "(1/2)" in _flat(pages[0]).replace("（", "(").replace("）", ")")
        assert "作業員09" in pages[1]
        assert "合計10人" in _flat(pages[0]) and "合計10人" in _flat(pages[1])

    def test_長い作業内容も枠に収まり入らなければ以下略(self, client, user_a, data):
        report = data["sep10"]
        lines = (f"{i}行目の作業内容をここに書きます" for i in range(400))
        report.work_description = "\n".join(lines)
        report.save()
        client.force_login(user_a)
        pages = _pages(client.get(reverse("reports:pdf", args=[report.pk])))
        assert len(pages) == 1
        assert "以下略" in _flat(pages[0])

    def test_承認済みなら釼持の承認印_協力会社なし(self, client, user_a, data):
        client.force_login(user_a)
        url = reverse("reports:pdf", args=[data["sep10"].pk])
        # 1 人でも承認されていなければ押さない
        DailyReport.unscoped.filter(pk=data["sep10"].pk).update(
            status=DailyReport.Status.APPROVED,
        )
        assert "釼" not in _flat(_pages(client.get(url))[0])
        # 同じ用紙の全員が承認済みなら押す（1 つだけ）
        DailyReport.unscoped.filter(pk=data["sep10_jiro"].pk).update(
            status=DailyReport.Status.APPROVED,
        )
        text = _flat(_pages(client.get(url))[0])
        assert text.count("釼") == 1 and text.count("持") == 1

    def test_協力会社は会社ごとに承認済みなら押す(self, client, user_a, data, company_a):
        supplier = Supplier.unscoped.create(company=company_a, code="P001", name="山田電設")
        other = Supplier.unscoped.create(company=company_a, code="P002", name="港電気")
        make = data["make"]
        day = datetime.date(2026, 9, 10)
        for code, name, sup, status in (
            ("W001", "応援一郎", supplier, DailyReport.Status.APPROVED),
            ("W002", "応援二郎", supplier, DailyReport.Status.APPROVED),
            ("W003", "港三郎", other, DailyReport.Status.SUBMITTED),
        ):
            helper = Worker.unscoped.create(
                company=company_a, employee_code=code, name=name, hourly_cost=0,
            )
            make(day, worker=helper, is_partner_worker=True, partner=sup, status=status)
        client.force_login(user_a)
        text = _flat(_pages(client.get(reverse("reports:pdf", args=[data["sep10"].pk])))[0])
        # 山田電設（2 人とも承認済み）だけに押す。港電気（提出済）と自社（下書き）には押さない
        assert text.count("釼") == 1

    def test_現場代理人又は責任者は左に寄せ右に氏名の欄(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:pdf", args=[data["sep10"].pk]))
        with pdfplumber.open(BytesIO(res.content)) as pdf:
            page = pdf.pages[0]
            words = [w for w in page.extract_words() if "現場代理人" in w["text"]]
            assert words, "label not found"
            label = words[0]
            # 文字の左端あたりから始まり、右へ長く続く署名用の線がある
            # （枠の下辺は用紙の左端から始まるので、x0 が文字の近くかどうかで区別する）
            lines = [
                ln for ln in page.lines
                if abs(ln["top"] - ln["bottom"]) < 0.5
                and label["x0"] - 12 <= ln["x0"] <= label["x0"] + 1
                and ln["x1"] > label["x1"] + 60 and 0 < ln["top"] - label["bottom"] < 12
            ]
            assert lines, "signature line not found"
            # 文字は用紙の中央より左側から始まる
            assert label["x0"] < page.width / 2

    def test_日本語のファイル名でブラウザ内に開く(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:pdf", args=[data["sep10"].pk]))
        disposition = res["Content-Disposition"]
        assert disposition.startswith("inline;")
        assert "filename*=utf-8''" in disposition
        # 「日報_2026-09-10_A社ビル新築.pdf」を URL エンコードしたもの
        assert "%E6%97%A5%E5%A0%B1_2026-09-10_A%E7%A4%BE" in disposition

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
    def test_同じ日同じ現場ごとに1枚で古い順(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:list_pdf") + "?month=2026-09")
        assert res.status_code == 200
        pages = [_flat(p) for p in _pages(res)]
        # 9/2 A社ビル（2件）、9/2 B倉庫、9/10 A社ビル（2件）の 3 枚
        assert len(pages) == 3
        assert "令和8年9月2日" in pages[0] and "A社ビル新築" in pages[0]
        assert "令和8年9月2日" in pages[1] and "B倉庫" in pages[1]
        assert "令和8年9月10日" in pages[2]
        assert "%E6%97%A5%E5%A0%B1_2026-09.pdf" in res["Content-Disposition"]

    def test_状態でも絞れる(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:list_pdf") + "?month=2026-09&status=submitted")
        pages = _pages(res)
        assert len(pages) == 1
        text = _flat(pages[0])
        assert "提出済1件" in text
        # 絞り込みで外れた同じ日の弱電の日報は入らない
        assert "弱電" not in text

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
