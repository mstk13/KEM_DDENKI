"""日報の使用材料の入力（ADR-0058）。

- 日報を書く画面に「使用材料を入力する」ボタン。入力欄は最初は閉じている
- 品名・数量・単位・メーカー・型式・備考を保存する。品名が空の行は捨てる。数量は空でもよい
- 数量が数字でない・品名が無いのに他を書いた行はエラーで戻し、入力欄を開いたまま出す
- まとめて書いたときは最初の 1 件の日報にだけ付ける
- 編集では材料が入っていれば最初から開き、画面の内容で入れ替える（入力欄が送られたときだけ）
- PDF は使用材料があれば 2 枚目に使用材料の表だけの用紙。無ければ 1 枚。17 行を超えたら続ける
- 詳細画面にメーカー・型式・備考が出る
"""

import datetime
from decimal import Decimal
from io import BytesIO

import pdfplumber
import pytest
from django.urls import reverse

from apps.masters.models import WorkType
from apps.reports.models import DailyReport, DailyReportMaterial
from apps.sites.models import Site
from apps.workers.models import Worker


@pytest.fixture
def data(company_a, user_a):
    me = Worker.unscoped.create(
        company=company_a, employee_code="E001", name="電工太郎", hourly_cost=3000, user=user_a,
    )
    other = Worker.unscoped.create(
        company=company_a, employee_code="E002", name="佐々木健太郎", hourly_cost=3000,
    )
    return {"me": me, "other": other}


def _post(workers, materials=(), **overrides):
    values = {
        "site": "A社ビル", "workers": [w.pk for w in workers], "report_date": "2026-09-14",
        "weather": "", "process": "", "work_type": "電気", "work_description": "配線",
        "start_date": "", "start_time": "08:30", "end_date": "", "end_time": "17:30",
        "work_hours": "", "partner": "", "memo": "", "action": "draft",
        "materials_submitted": "1",
    }
    columns = {k: [] for k in ("material_name", "material_quantity", "material_unit",
                               "material_maker", "material_model", "material_note",
                               "material_id")}
    for row in materials:
        for key in columns:
            columns[key].append(row.get(key, ""))
    values.update(columns)
    values.update(overrides)
    return values


CABLE = {
    "material_name": "VVFケーブル 2.0-2C", "material_quantity": "100", "material_unit": "m",
    "material_maker": "矢崎電線", "material_model": "VVF2.0-2C", "material_note": "1巻使用",
}


def _pdf_pages(res):
    with pdfplumber.open(BytesIO(res.content)) as pdf:
        return ["".join((p.extract_text() or "").split()) for p in pdf.pages]


@pytest.mark.django_db
class TestCreateScreen:
    def test_ボタンがあり入力欄は最初閉じている(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:create"))
        body = res.content.decode()
        assert 'id="toggle-materials"' in body and "使用材料を入力する" in body
        assert 'id="materials-section" style="margin-top:10px;" hidden' in body
        assert 'id="material-row-template"' in body
        assert res.context["form"].show_materials is False

    def test_使用材料を保存する_空の行は捨てる(self, client, user_a, data):
        client.force_login(user_a)
        res = client.post(reverse("reports:create"), _post([data["me"]], [CABLE, {}]))
        assert res.status_code == 302
        report = DailyReport.unscoped.get(worker=data["me"])
        materials = list(report.materials_used.all())
        assert len(materials) == 1
        m = materials[0]
        assert m.material_name == "VVFケーブル 2.0-2C"
        assert (m.quantity_used, m.unit) == (Decimal("100"), "m")
        assert (m.maker, m.model_number, m.note) == ("矢崎電線", "VVF2.0-2C", "1巻使用")

    def test_数量は空でもよい_全角の数字も読む(self, client, user_a, data):
        client.force_login(user_a)
        rows = [
            {"material_name": "結束バンド"},
            {"material_name": "端子", "material_quantity": "１２．５"},
        ]
        client.post(reverse("reports:create"), _post([data["me"]], rows))
        report = DailyReport.unscoped.get(worker=data["me"])
        quantities = {m.material_name: m.quantity_used for m in report.materials_used.all()}
        assert quantities == {"結束バンド": None, "端子": Decimal("12.5")}

    def test_数量が数字でないと戻して入力欄を開く(self, client, user_a, data):
        client.force_login(user_a)
        rows = [{**CABLE, "material_quantity": "たくさん"}]
        res = client.post(reverse("reports:create"), _post([data["me"]], rows))
        assert res.status_code == 200
        assert "数量は数字で入力してください" in res.content.decode()
        assert res.context["form"].show_materials is True
        assert not DailyReport.unscoped.exists()
        # 入力した値は消えずに残る
        assert 'value="たくさん"' in res.content.decode()

    def test_品名が無いのに他を書いた行はエラー(self, client, user_a, data):
        client.force_login(user_a)
        rows = [{"material_maker": "矢崎電線"}]
        res = client.post(reverse("reports:create"), _post([data["me"]], rows))
        assert res.status_code == 200
        assert "品名を入力してください" in res.content.decode()

    def test_まとめて書いたときは最初の1件にだけ付ける(self, client, user_a, data):
        client.force_login(user_a)
        client.post(reverse("reports:create"), _post([data["me"], data["other"]], [CABLE]))
        assert DailyReport.unscoped.count() == 2
        assert DailyReportMaterial.unscoped.count() == 1


@pytest.mark.django_db
class TestEdit:
    def _report_with_material(self, company, worker):
        site = Site.unscoped.create(company=company, code="S001", name="A社ビル")
        wt = WorkType.unscoped.create(company=company, code="E01", name="電気")
        report = DailyReport.unscoped.create(
            company=company, site=site, worker=worker, work_type=wt,
            report_date=datetime.date(2026, 9, 14), start_time=datetime.time(8, 30),
            end_time=datetime.time(17, 30), work_hours=0, work_description="配線",
        )
        DailyReportMaterial.unscoped.create(
            company=company, daily_report=report, material_name="VVFケーブル 2.0-2C",
            quantity_used=Decimal("100"), unit="m", maker="矢崎電線",
        )
        return report

    def test_材料があれば最初から開いて出す(self, client, user_a, data, company_a):
        report = self._report_with_material(company_a, data["me"])
        client.force_login(user_a)
        res = client.get(reverse("reports:edit", args=[report.pk]))
        assert res.context["form"].show_materials is True
        body = res.content.decode()
        assert 'value="VVFケーブル 2.0-2C"' in body and 'value="100"' in body
        assert 'value="矢崎電線"' in body

    def test_画面の内容で入れ替える(self, client, user_a, data, company_a):
        report = self._report_with_material(company_a, data["me"])
        client.force_login(user_a)
        rows = [{"material_name": "圧着端子", "material_quantity": "20", "material_unit": "個"}]
        client.post(reverse("reports:edit", args=[report.pk]), _post([data["me"]], rows))
        assert [m.material_name for m in report.materials_used.all()] == ["圧着端子"]

    def test_材料マスタとの結び付きは編集で残す(self, client, user_a, data, company_a):
        from apps.materials.models import Material

        report = self._report_with_material(company_a, data["me"])
        master = Material.unscoped.create(company=company_a, code="M001", name="VVF", unit="巻")
        report.materials_used.update(material=master)
        client.force_login(user_a)
        row = {"material_name": "VVFケーブル 2.0-2C", "material_quantity": "50",
               "material_unit": "m", "material_id": str(master.pk)}
        client.post(reverse("reports:edit", args=[report.pk]), _post([data["me"]], [row]))
        saved = report.materials_used.get()
        assert saved.material_id == master.pk and saved.quantity_used == Decimal("50")

    def test_他社の材料マスタは結び付けない(self, client, user_a, data, company_a, company_b):
        from apps.materials.models import Material

        report = self._report_with_material(company_a, data["me"])
        foreign = Material.unscoped.create(company=company_b, code="M001", name="他社", unit="個")
        client.force_login(user_a)
        row = {"material_name": "端子", "material_id": str(foreign.pk)}
        client.post(reverse("reports:edit", args=[report.pk]), _post([data["me"]], [row]))
        assert report.materials_used.get().material_id is None

    def test_入力欄が送られていなければ材料は触らない(self, client, user_a, data, company_a):
        report = self._report_with_material(company_a, data["me"])
        client.force_login(user_a)
        values = _post([data["me"]])
        del values["materials_submitted"]
        client.post(reverse("reports:edit", args=[report.pk]), values)
        assert report.materials_used.count() == 1


@pytest.mark.django_db
class TestPdfAndDetail:
    def _create(self, client, user_a, data, rows):
        client.force_login(user_a)
        client.post(reverse("reports:create"), _post([data["me"]], rows))
        return DailyReport.unscoped.get(worker=data["me"])

    def test_材料があれば2枚目に使用材料(self, client, user_a, data):
        report = self._create(client, user_a, data, [CABLE])
        pages = _pdf_pages(client.get(reverse("reports:pdf", args=[report.pk])))
        assert len(pages) == 2
        assert "使用材料品名" not in pages[0]
        second = pages[1]
        for expected in ("使用材料品名", "数量", "メーカー", "型式", "備考",
                         "VVFケーブル2.0-2C", "100m", "矢崎電線", "VVF2.0-2C", "1巻使用"):
            assert expected in second, expected
        # 2 枚目は表だけ。見出し（タイトル・現場名・年月日・天候・工種・工程）は付けない
        for absent in ("作業日報", "現場名", "発注先", "年月日",
                       "天候", "工種", "工程", "A社ビル"):
            assert absent not in second, absent

    def test_材料が無ければ1枚(self, client, user_a, data):
        report = self._create(client, user_a, data, [])
        assert len(_pdf_pages(client.get(reverse("reports:pdf", args=[report.pk])))) == 1

    def test_17行を超えたら続ける(self, client, user_a, data):
        rows = [{"material_name": f"材料{i:02d}", "material_quantity": "1"} for i in range(18)]
        report = self._create(client, user_a, data, rows)
        pages = _pdf_pages(client.get(reverse("reports:pdf", args=[report.pk])))
        assert len(pages) == 3
        assert "材料16" in pages[1] and "材料17" in pages[2]

    def test_詳細にメーカー型式備考が出る(self, client, user_a, data):
        report = self._create(client, user_a, data, [CABLE])
        body = client.get(reverse("reports:detail", args=[report.pk])).content.decode()
        for expected in ("使用材料品名", "メーカー", "型式", "備考",
                         "矢崎電線", "VVF2.0-2C", "1巻使用"):
            assert expected in body, expected
