"""見積ファイルからの明細（材料・数量・単価）取り込み。

抽出は「ヘッダ行を見つけて列を対応付ける」方式なので、列の並びが変わっても
読めること、逆に**ヘッダが無ければ何も読まない**ことを固定する。数字を
推測で拾って金額がずれた明細が黙って入るのが一番まずい。

登録側は、材料マスタを自動作成しないこと・確定時にサーバ側で引き当てを
やり直すこと（他社の材料に紐づかないこと）を確かめる。
"""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.tenant_context import set_current_company
from apps.masters.models import Customer
from apps.materials.models import Material, Quotation, QuotationItem
from apps.materials.services import (
    find_material_by_name,
    normalize_material_name,
)
from apps.sites.line_items import (
    deserialize_lines,
    extract_lines,
    parse_estimate_lines,
    serialize_lines,
)
from apps.sites.models import Site

# 見出し部と明細を両方持つ、ライデン出力を模した CSV。
ESTIMATE_CSV = """御見積書,,,,,
株式会社サンプル建設 御中,,,,,
,,見積番号,Q-2026-0142,,
工事件名,○○ビル 電気設備改修工事,,,,
支払条件,月末締め翌月末現金払い,,,,
見積金額,"3,480,000円",,,,
,,,,,
No,名称,規格,数量,単位,単価,金額
1,VVFケーブル,1.6mm 3心,120,m,"1,200","144,000"
2,PF管,22mm,80,m,320,"25,600"
3,埋込スイッチ,片切,45,個,480,"21,600"
小計,,,,,,"191,200"
消費税,,,,,,"19,120"
合計,,,,,,"210,320"
"""


def _write_csv(tmp_path, text, encoding="cp932", name="estimate.csv"):
    path = tmp_path / name
    path.write_text(text, encoding=encoding)
    return path


def _write_xlsx(tmp_path, sheets, name="estimate.xlsx"):
    """{シート名: 行のリスト} から xlsx を作る。"""
    import openpyxl

    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for sheet_name, rows in sheets.items():
        sheet = workbook.create_sheet(sheet_name)
        for row in rows:
            sheet.append(row)
    path = tmp_path / name
    workbook.save(path)
    return path


# ---------------------------------------------------------------------------
# 明細の抽出
# ---------------------------------------------------------------------------

class TestExtractLines:
    def test_reads_every_column_of_each_line(self, tmp_path):
        lines = parse_estimate_lines(_write_csv(tmp_path, ESTIMATE_CSV), ".csv")

        assert len(lines) == 3
        assert lines[0] == {
            "name": "VVFケーブル",
            "spec": "1.6mm 3心",
            "unit": "m",
            "quantity": Decimal("120"),
            "unit_price": Decimal("1200"),
            "amount": Decimal("144000"),
            "remarks": "",
        }
        assert lines[2]["name"] == "埋込スイッチ"
        assert lines[2]["amount"] == Decimal("21600")

    def test_stops_at_the_total_row(self, tmp_path):
        """小計・消費税・合計は明細ではない。登録されると金額が二重になる。"""
        lines = parse_estimate_lines(_write_csv(tmp_path, ESTIMATE_CSV), ".csv")

        names = [line["name"] for line in lines]
        assert "小計" not in names
        assert "消費税" not in names
        assert "合計" not in names

    def test_finds_columns_by_header_name_not_position(self):
        """列の並びが変わっても読める。版によって並びが動くため。"""
        rows = [
            ["金額", "数量", "品名", "単価", "単位"],
            ["144000", "120", "VVFケーブル", "1200", "m"],
        ]
        lines = extract_lines(rows)

        assert len(lines) == 1
        assert lines[0]["name"] == "VVFケーブル"
        assert lines[0]["quantity"] == Decimal("120")
        assert lines[0]["unit_price"] == Decimal("1200")
        assert lines[0]["amount"] == Decimal("144000")

    def test_returns_nothing_when_there_is_no_header(self):
        """ヘッダが無ければ推測で拾わない。空で返して人に入力させる。"""
        rows = [
            ["VVFケーブル", "120", "1200", "144000"],
            ["PF管", "80", "320", "25600"],
        ]
        assert extract_lines(rows) == []

    def test_ignores_a_header_that_only_has_a_name_column(self):
        """「工事名称」だけの見出し行をヘッダと誤認しない。"""
        rows = [
            ["工事名称", "○○ビル 電気設備改修工事"],
            ["支払条件", "月末締め翌月末現金払い"],
        ]
        assert extract_lines(rows) == []

    def test_skips_rows_that_are_only_a_heading(self):
        """数値の無い行は小見出し。明細ではない。"""
        rows = [
            ["名称", "数量", "単価", "金額"],
            ["1. 電気設備工事", "", "", ""],
            ["VVFケーブル", "120", "1200", "144000"],
        ]
        lines = extract_lines(rows)

        assert [line["name"] for line in lines] == ["VVFケーブル"]

    def test_fills_amount_from_quantity_and_unit_price(self):
        rows = [
            ["名称", "数量", "単価", "金額"],
            ["VVFケーブル", "120", "1200", ""],
        ]
        assert extract_lines(rows)[0]["amount"] == Decimal("144000")

    def test_does_not_back_calculate_unit_price_from_amount(self):
        """割り戻すと端数処理で元の単価と変わる。根拠のない数字は入れない。"""
        rows = [
            ["名称", "数量", "単価", "金額"],
            ["一式計上", "1", "", "144000"],
        ]
        line = extract_lines(rows)[0]

        assert line["unit_price"] is None
        assert line["amount"] == Decimal("144000")

    def test_strips_currency_marks_and_separators(self):
        rows = [
            ["名称", "数量", "単価", "金額"],
            ["VVFケーブル", "3.5", "¥1,200", "4,200円"],
        ]
        line = extract_lines(rows)[0]

        assert line["quantity"] == Decimal("3.5")
        assert line["unit_price"] == Decimal("1200")
        assert line["amount"] == Decimal("4200")

    def test_reads_lines_from_excel(self, tmp_path):
        path = _write_xlsx(tmp_path, {"明細": [
            ["名称", "規格", "数量", "単位", "単価", "金額"],
            ["VVFケーブル", "1.6mm 3心", 120, "m", 1200, 144000],
        ]})
        lines = parse_estimate_lines(path, ".xlsx")

        assert len(lines) == 1
        assert lines[0]["name"] == "VVFケーブル"
        assert lines[0]["amount"] == Decimal("144000")

    def test_does_not_stop_at_a_single_blank_row(self):
        """PDF はページ跨ぎで空行が入る。1行空いただけで打ち切らない。"""
        rows = [
            ["名称", "数量", "単価", "金額"],
            ["VVFケーブル", "120", "1200", "144000"],
            ["", "", "", ""],
            ["PF管", "80", "320", "25600"],
        ]
        assert len(extract_lines(rows)) == 2


# ---------------------------------------------------------------------------
# 確認画面との往復
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_survives_serialization(self):
        rows = [
            ["名称", "規格", "数量", "単位", "単価", "金額"],
            ["VVFケーブル", "1.6mm 3心", "120", "m", "1200", "144000"],
        ]
        original = extract_lines(rows)
        restored = deserialize_lines(serialize_lines(original))

        assert restored == original

    def test_broken_json_yields_nothing(self):
        assert deserialize_lines("{壊れている") == []
        assert deserialize_lines("") == []
        assert deserialize_lines('{"not": "a list"}') == []

    def test_drops_entries_without_a_name(self):
        assert deserialize_lines('[{"quantity": "1", "amount": "100"}]') == []

    def test_revalidates_numbers_from_the_browser(self):
        """戻ってきた値は信用しない。数値として読めないものは None にする。"""
        restored = deserialize_lines(
            '[{"name": "VVF", "quantity": "たくさん", "amount": "100"}]'
        )

        assert restored[0]["quantity"] is None
        assert restored[0]["amount"] == Decimal("100")


# ---------------------------------------------------------------------------
# 材料マスタの引き当て
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestMaterialMatching:
    def test_normalizes_notation_differences(self):
        key = normalize_material_name("VVF 1.6mm 2C")

        assert normalize_material_name("ＶＶＦ1.6MM2C") == key
        assert normalize_material_name("VVF-1.6mm-2c") == key

    def test_keeps_different_sizes_apart(self):
        assert (
            normalize_material_name("VVF 1.6mm 2C")
            != normalize_material_name("VVF 2.0mm 2C")
        )

    def test_matches_a_registered_material(self, company_a):
        material = Material.unscoped.create(
            company=company_a, code="M001", name="VVFケーブル 1.6mm 3心", unit="m",
        )
        assert find_material_by_name(company_a, "ＶＶＦケーブル1.6MM3心") == material

    def test_returns_none_when_not_registered(self, company_a):
        assert find_material_by_name(company_a, "存在しない材料") is None

    def test_does_not_reach_another_company(self, company_a, company_b):
        Material.unscoped.create(
            company=company_b, code="M001", name="VVFケーブル", unit="m",
        )
        assert find_material_by_name(company_a, "VVFケーブル") is None

    def test_ignores_inactive_materials(self, company_a):
        Material.unscoped.create(
            company=company_a, code="M001", name="旧VVF", unit="m", is_active=False,
        )
        assert find_material_by_name(company_a, "旧VVF") is None


# ---------------------------------------------------------------------------
# 取り込み画面
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestImportViewWithLines:
    def _confirm_payload(self, customer, lines_json, **extra):
        payload = {
            "step": "confirm",
            "code": "Q-2026-0142",
            "name": "○○ビル 電気設備改修工事",
            # 顧客欄は自由入力になったので、pk ではなく会社名を送る。
            "customer_name": customer.name,
            "status": Site.Status.ESTIMATING,
            "contract_amount": 3480000,
            "lines_json": lines_json,
            "register_lines": "1",
        }
        payload.update(extra)
        return payload

    def test_upload_shows_the_parsed_lines(
        self, client, tmp_path, company_a, user_a
    ):
        set_current_company(company_a)
        client.force_login(user_a)

        with open(_write_csv(tmp_path, ESTIMATE_CSV), "rb") as f:
            body = client.post(
                reverse("sites:import"), {"file": f}
            ).content.decode("utf-8")

        assert "読み取った見積明細（3 件）" in body
        assert "VVFケーブル" in body
        assert "埋込スイッチ" in body
        set_current_company(None)

    def test_confirming_creates_the_quotation_and_items(
        self, client, company_a, user_a
    ):
        set_current_company(company_a)
        customer = Customer.unscoped.create(
            company=company_a, code="C001", name="株式会社サンプル建設",
        )
        material = Material.unscoped.create(
            company=company_a, code="M001", name="VVFケーブル", unit="m",
        )
        client.force_login(user_a)

        lines_json = serialize_lines(extract_lines([
            ["名称", "規格", "数量", "単位", "単価", "金額"],
            ["VVFケーブル", "1.6mm 3心", "120", "m", "1200", "144000"],
            ["PF管", "22mm", "80", "m", "320", "25600"],
        ]))
        res = client.post(
            reverse("sites:import"),
            self._confirm_payload(customer, lines_json),
        )

        assert res.status_code == 302
        site = Site.unscoped.get(company=company_a, code="Q-2026-0142")
        quotation = Quotation.unscoped.get(company=company_a, site=site)

        assert quotation.kind == Quotation.Kind.ISSUED
        assert quotation.customer == customer
        assert quotation.supplier is None
        assert quotation.total_amount == Decimal("169600")
        assert quotation.quotation_date == datetime.date.today()

        items = list(QuotationItem.unscoped.filter(quotation=quotation))
        assert len(items) == 2
        assert items[0].material == material          # マスタに当たった
        assert items[0].material_name == "VVFケーブル"  # 読み取った名称も残る
        assert items[0].spec == "1.6mm 3心"
        assert items[0].unit == "m"
        assert items[1].material is None              # マスタに無い
        assert items[1].material_name == "PF管"
        set_current_company(None)

    def test_does_not_create_materials_automatically(
        self, client, company_a, user_a
    ):
        set_current_company(company_a)
        customer = Customer.unscoped.create(
            company=company_a, code="C001", name="株式会社サンプル建設",
        )
        client.force_login(user_a)

        lines_json = serialize_lines(extract_lines([
            ["名称", "数量", "単価", "金額"],
            ["新種のケーブル", "10", "500", "5000"],
        ]))
        client.post(
            reverse("sites:import"),
            self._confirm_payload(customer, lines_json),
        )

        assert not Material.unscoped.filter(company=company_a).exists()
        set_current_company(None)

    def test_unchecking_skips_the_quotation(self, client, company_a, user_a):
        set_current_company(company_a)
        customer = Customer.unscoped.create(
            company=company_a, code="C001", name="株式会社サンプル建設",
        )
        client.force_login(user_a)

        lines_json = serialize_lines(extract_lines([
            ["名称", "数量", "単価", "金額"],
            ["VVFケーブル", "120", "1200", "144000"],
        ]))
        payload = self._confirm_payload(customer, lines_json)
        del payload["register_lines"]
        res = client.post(reverse("sites:import"), payload)

        assert res.status_code == 302
        assert Site.unscoped.filter(company=company_a).exists()
        assert not Quotation.unscoped.filter(company=company_a).exists()
        set_current_company(None)

    def test_a_site_is_still_created_when_no_lines_were_read(
        self, client, company_a, user_a
    ):
        set_current_company(company_a)
        customer = Customer.unscoped.create(
            company=company_a, code="C001", name="株式会社サンプル建設",
        )
        client.force_login(user_a)

        res = client.post(
            reverse("sites:import"),
            self._confirm_payload(customer, ""),
        )

        assert res.status_code == 302
        assert Site.unscoped.filter(company=company_a, code="Q-2026-0142").exists()
        assert not Quotation.unscoped.filter(company=company_a).exists()
        set_current_company(None)

    def test_does_not_link_a_material_from_another_company(
        self, client, company_a, company_b, user_a
    ):
        """画面が持ち回るのは名称だけ。他社の材料には決して紐づかない。"""
        set_current_company(company_a)
        customer = Customer.unscoped.create(
            company=company_a, code="C001", name="株式会社サンプル建設",
        )
        foreign = Material.unscoped.create(
            company=company_b, code="M001", name="VVFケーブル", unit="m",
        )
        client.force_login(user_a)

        lines_json = serialize_lines(extract_lines([
            ["名称", "数量", "単価", "金額"],
            ["VVFケーブル", "120", "1200", "144000"],
        ]))
        client.post(
            reverse("sites:import"),
            self._confirm_payload(customer, lines_json),
        )

        item = QuotationItem.unscoped.get(quotation__company=company_a)
        assert item.material is None
        assert item.material_name == "VVFケーブル"
        assert QuotationItem.unscoped.filter(material=foreign).count() == 0
        set_current_company(None)
