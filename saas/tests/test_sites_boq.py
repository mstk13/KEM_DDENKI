"""現場の内訳書・内訳明細書のテスト。

- モデル制約（持ち主は積算案件か現場のどちらか一方）
- テナント越境
- Excel / PDF の取込パーサ
- 階層の組み立て（並び順と階層から親子を作る）
- 現場詳細での表示、表形式編集、Excel出力
"""

import io
from decimal import Decimal

import openpyxl
import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.estimation.models import BoqLine, EstimationProject, Orderer
from apps.estimation.services import boq_import
from apps.estimation.services.boq_export import export_boq_to_excel
from apps.sites.models import Site


def _site(company, code="S-001", name="○○ビル電気設備工事"):
    return Site.unscoped.create(company=company, code=code, name=name)


def _line(company, site, name, level=BoqLine.Level.SAIMOKU, order=1, **kwargs):
    return BoqLine.unscoped.create(
        company=company, site=site, name=name, level=level,
        sort_order=order, **kwargs,
    )


def _excel_bytes(rows) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


HEADER = ["階層", "名称", "仕様", "単位", "数量", "単価", "金額", "備考"]


# ---------------------------------------------------------------------------
# モデル
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBoqLineOwner:
    def test_site_only_is_allowed(self, company_a):
        site = _site(company_a)
        line = _line(company_a, site, "VVFケーブル")
        assert line.site_id == site.pk
        assert line.project_id is None

    def test_neither_owner_is_rejected(self, company_a):
        """持ち主のいない明細は作れない。"""
        with pytest.raises(IntegrityError), transaction.atomic():
            BoqLine.unscoped.create(
                company=company_a, name="宙に浮いた明細",
                level=BoqLine.Level.SAIMOKU,
            )

    def test_both_owners_are_rejected(self, company_a):
        """両方に紐づけるとどちらの内訳書に出すか決まらない。"""
        site = _site(company_a)
        orderer = Orderer.unscoped.create(company=company_a, name="○○市")
        project = EstimationProject.unscoped.create(
            company=company_a, name="案件", orderer=orderer,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            BoqLine.unscoped.create(
                company=company_a, site=site, project=project,
                name="二重", level=BoqLine.Level.SAIMOKU,
            )

    def test_is_meisai_only_for_saimoku(self, company_a):
        site = _site(company_a)
        assert _line(company_a, site, "細目", BoqLine.Level.SAIMOKU).is_meisai is True
        assert _line(company_a, site, "科目", BoqLine.Level.KAMOKU).is_meisai is False

    def test_calc_amount_keeps_imported_amount(self, company_a):
        """一式計上の行の金額を計算で消さない。"""
        site = _site(company_a)
        line = _line(
            company_a, site, "仮設工事一式",
            quantity=None, unit_price=None, amount=Decimal("500000"),
        )
        line.calc_amount()
        assert line.amount == Decimal("500000")


@pytest.mark.django_db
class TestBoqTenantIsolation:
    def test_lines_do_not_cross_tenants(self, company_a, company_b):
        from apps.core.tenant_context import set_current_company

        site_a = _site(company_a, "A-001")
        site_b = _site(company_b, "B-001")
        _line(company_a, site_a, "A社の明細")
        _line(company_b, site_b, "B社の明細")

        set_current_company(company_a)
        names = list(BoqLine.objects.values_list("name", flat=True))
        assert names == ["A社の明細"]

    def test_other_tenant_site_is_not_reachable(self, client, user_a, company_b):
        site_b = _site(company_b, "B-001")
        client.force_login(user_a)
        response = client.get(reverse("sites:boq_edit", args=[site_b.pk]))
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# 値の正規化
# ---------------------------------------------------------------------------


class TestValueParsing:
    @pytest.mark.parametrize(("raw", "expected"), [
        ("1,234", Decimal("1234")),
        ("¥1,234", Decimal("1234")),
        ("1234円", Decimal("1234")),
        ("１２３４", Decimal("1234")),      # 全角
        ("12.500", Decimal("12.500")),
        ("-500", Decimal("-500")),
        (1234, Decimal("1234")),
        (12.5, Decimal("12.5")),
    ])
    def test_numbers(self, raw, expected):
        assert boq_import._to_decimal(raw) == expected

    @pytest.mark.parametrize("raw", ["", None, "一式", "式", "-", "―", "　"])
    def test_unreadable_becomes_none(self, raw):
        """読めない値は None。0 にすると読めた 0 と区別できなくなる。"""
        assert boq_import._to_decimal(raw) is None

    def test_lump_sum_with_number_is_read(self):
        """「1式」でも数字があるものは読む。"""
        assert boq_import._to_decimal("1式") == Decimal("1")

    @pytest.mark.parametrize("name", ["小計", "合計", "計", "小　計", "総計"])
    def test_subtotal_rows_are_detected(self, name):
        assert boq_import._is_subtotal(name) is True

    def test_normal_name_is_not_subtotal(self):
        assert boq_import._is_subtotal("電灯設備工事") is False


class TestIndentDepth:
    @pytest.mark.parametrize(("raw", "depth"), [
        ("電気設備工事", 0),
        ("  電灯設備", 1),
        ("　電灯設備", 1),        # 全角空白1つ
        ("    配線器具", 2),
        ("　　配線器具", 2),
        ("      VVFケーブル", 3),
    ])
    def test_depth(self, raw, depth):
        assert boq_import._indent_depth(raw) == depth


# ---------------------------------------------------------------------------
# Excel 取込
# ---------------------------------------------------------------------------


class TestExcelImport:
    def test_reads_rows_with_level_column(self):
        data = _excel_bytes([
            ["工事名称", "○○ビル電気設備工事"],
            [],
            HEADER,
            ["種目別", "電気設備工事", "", "式", None, None, 5000000, ""],
            ["細目別", "VVFケーブル", "1.6mm 2芯", "m", 1200, 150, 180000, "屋内"],
        ])
        result = boq_import.parse_excel(data)

        assert result.warnings == []
        assert len(result.drafts) == 2
        assert result.drafts[0].level == BoqLine.Level.SHUMOKU
        assert result.drafts[1].level == BoqLine.Level.SAIMOKU
        assert result.drafts[1].spec == "1.6mm 2芯"
        assert result.drafts[1].quantity == Decimal("1200")
        assert result.drafts[1].unit_price == Decimal("150")
        assert result.drafts[1].amount == Decimal("180000")
        assert result.meisai_count == 1

    def test_infers_level_from_indent(self):
        """全角空白1つで1段。4階層が素直に読める。"""
        data = _excel_bytes([
            ["名称", "仕様", "単位", "数量", "単価", "金額"],
            ["電気設備工事", "", "式", None, None, 5000000],
            ["　電灯設備", "", "式", None, None, 3000000],
            ["　　配線工事", "", "式", None, None, 1000000],
            ["　　　VVFケーブル", "1.6-2C", "m", 1200, 150, 180000],
        ])
        result = boq_import.parse_excel(data)

        levels = [d.level for d in result.drafts]
        assert levels == [
            BoqLine.Level.SHUMOKU,
            BoqLine.Level.KAMOKU,
            BoqLine.Level.CHUKAMOKU,
            BoqLine.Level.SAIMOKU,
        ]

    def test_priced_row_is_meisai_regardless_of_indent(self):
        """数量×単価がそろう行は、インデントが浅くても内訳明細書。

        実ファイルのインデントは2段だったり4段だったりばらつくので、
        段数だけで見ると最下層が細目別にならない。内訳明細書とは
        「数量×単価で金額を積む階層」のことなので、そこで判定する。
        """
        data = _excel_bytes([
            ["名称", "規格・仕様", "単位", "数量", "単価", "金額"],
            ["電気設備工事", "", "式", None, None, 5180000],
            ["　電灯設備", "", "式", None, None, 180000],
            ["　　VVFケーブル", "1.6mm 2芯", "m", 1200, 150, 180000],
        ])
        result = boq_import.parse_excel(data)

        levels = [d.level for d in result.drafts]
        assert levels == [
            BoqLine.Level.SHUMOKU,
            BoqLine.Level.KAMOKU,
            BoqLine.Level.SAIMOKU,
        ]
        assert result.meisai_count == 1

    def test_lump_sum_row_is_not_meisai(self):
        """一式計上（金額だけ）の行は見出し扱いのまま。"""
        data = _excel_bytes([
            ["名称", "単位", "数量", "単価", "金額"],
            ["　仮設工事", "式", "一式", None, 500000],
        ])
        result = boq_import.parse_excel(data)

        assert result.drafts[0].quantity is None
        assert result.drafts[0].level != BoqLine.MEISAI_LEVEL

    def test_top_level_row_with_amount_is_not_demoted(self):
        """インデントのある表では、最上位行が金額を持っていても種目別のまま。

        インデントの有無を行ごとに見ていた頃、金額を持つ最上位行だけが
        数値の有無で判定され細目別になっていた。
        """
        data = _excel_bytes([
            ["名称", "単位", "数量", "単価", "金額"],
            ["電気設備工事", "式", None, None, 5000000],
            ["　VVFケーブル", "m", 1200, 150, 180000],
        ])
        result = boq_import.parse_excel(data)

        assert result.drafts[0].level == BoqLine.Level.SHUMOKU

    def test_infers_level_from_numbers_when_flat(self):
        """インデントも階層列も無い様式。数量があれば明細とみなす。"""
        data = _excel_bytes([
            ["名称", "単位", "数量", "単価", "金額"],
            ["電灯設備", "", None, None, None],
            ["VVFケーブル", "m", 1200, 150, 180000],
        ])
        result = boq_import.parse_excel(data)

        assert result.drafts[0].level == BoqLine.Level.KAMOKU
        assert result.drafts[1].level == BoqLine.Level.SAIMOKU

    def test_skips_subtotal_rows(self):
        data = _excel_bytes([
            HEADER,
            ["細目別", "VVFケーブル", "", "m", 1200, 150, 180000, ""],
            ["", "小計", "", "", None, None, 180000, ""],
            ["", "合計", "", "", None, None, 180000, ""],
        ])
        result = boq_import.parse_excel(data)

        assert [d.name for d in result.drafts] == ["VVFケーブル"]

    def test_column_alias_is_absorbed(self):
        data = _excel_bytes([
            ["品名", "規格", "単位", "数量", "単価", "金額"],
            ["VVFケーブル", "1.6-2C", "m", 1200, 150, 180000],
        ])
        result = boq_import.parse_excel(data)

        assert result.drafts[0].name == "VVFケーブル"
        assert result.drafts[0].spec == "1.6-2C"

    def test_cover_sheet_is_skipped_without_noise(self):
        """表紙しかないシートで警告を出さない（本当の失敗が埋もれる）。"""
        wb = openpyxl.Workbook()
        cover = wb.active
        cover.title = "鑑"
        cover.append(["工事名称", "○○ビル"])
        body = wb.create_sheet("内訳書")
        for row in [HEADER, ["細目別", "VVF", "", "m", 10, 100, 1000, ""]]:
            body.append(row)
        buf = io.BytesIO()
        wb.save(buf)

        result = boq_import.parse_excel(buf.getvalue())
        assert result.warnings == []
        assert len(result.drafts) == 1

    def test_unreadable_file_reports_reason(self):
        result = boq_import.parse_excel(b"not an excel file")
        assert result.drafts == []
        assert result.warnings
        assert "Excel を開けません" in result.warnings[0]

    def test_no_table_reports_reason(self):
        data = _excel_bytes([["工事名称", "○○ビル"], ["発注者", "△△市"]])
        result = boq_import.parse_excel(data)
        assert result.drafts == []
        assert result.warnings


class TestParseUploadDispatch:
    def test_xls_is_rejected_with_guidance(self):
        result = boq_import.parse_upload("内訳書.xls", b"")
        assert ".xlsx で保存し直して" in result.warnings[0]

    def test_unknown_extension_is_rejected(self):
        result = boq_import.parse_upload("内訳書.docx", b"")
        assert result.drafts == []
        assert result.warnings


# ---------------------------------------------------------------------------
# 保存と階層の組み立て
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLoadDrafts:
    def _drafts(self):
        return [
            boq_import.BoqDraft(level=BoqLine.Level.SHUMOKU, name="電気設備工事"),
            boq_import.BoqDraft(level=BoqLine.Level.KAMOKU, name="電灯設備"),
            boq_import.BoqDraft(
                level=BoqLine.Level.SAIMOKU, name="VVFケーブル",
                quantity=Decimal("1200"), unit_price=Decimal("150"),
            ),
            boq_import.BoqDraft(level=BoqLine.Level.KAMOKU, name="動力設備"),
            boq_import.BoqDraft(
                level=BoqLine.Level.SAIMOKU, name="CVケーブル",
                quantity=Decimal("300"), unit_price=Decimal("800"),
            ),
        ]

    def test_builds_parent_links(self, company_a):
        site = _site(company_a)
        created = boq_import.load_drafts(
            self._drafts(), company=company_a, site=site,
        )
        assert created == 5

        lines = {line.name: line for line in BoqLine.unscoped.filter(site=site)}
        assert lines["電気設備工事"].parent is None
        assert lines["電灯設備"].parent == lines["電気設備工事"]
        assert lines["VVFケーブル"].parent == lines["電灯設備"]
        # 2つめの科目の子が、1つめの科目の子にぶら下がらないこと。
        assert lines["動力設備"].parent == lines["電気設備工事"]
        assert lines["CVケーブル"].parent == lines["動力設備"]

    def test_amount_is_calculated(self, company_a):
        site = _site(company_a)
        boq_import.load_drafts(self._drafts(), company=company_a, site=site)
        line = BoqLine.unscoped.get(site=site, name="VVFケーブル")
        assert line.amount == Decimal("180000")

    def test_replace_clears_existing(self, company_a):
        site = _site(company_a)
        _line(company_a, site, "古い明細")
        boq_import.load_drafts(
            self._drafts(), company=company_a, site=site, replace=True,
        )
        names = set(BoqLine.unscoped.filter(site=site).values_list("name", flat=True))
        assert "古い明細" not in names

    def test_append_keeps_existing(self, company_a):
        site = _site(company_a)
        _line(company_a, site, "古い明細")
        boq_import.load_drafts(
            self._drafts(), company=company_a, site=site, replace=False,
        )
        names = set(BoqLine.unscoped.filter(site=site).values_list("name", flat=True))
        assert "古い明細" in names

    def test_requires_exactly_one_owner(self, company_a):
        with pytest.raises(ValueError):
            boq_import.load_drafts([], company=company_a)


@pytest.mark.django_db
class TestRebuildTree:
    def test_reassigns_parents_from_order(self, company_a):
        site = _site(company_a)
        parent = _line(company_a, site, "電灯設備", BoqLine.Level.KAMOKU, order=1)
        child = _line(company_a, site, "VVF", BoqLine.Level.SAIMOKU, order=2)
        # わざと誤った親子にしておく
        child.parent = None
        child.save()

        boq_import.rebuild_tree([parent, child])

        child.refresh_from_db()
        assert child.parent == parent


# ---------------------------------------------------------------------------
# 画面
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSiteDetailBoqSection:
    def test_section_is_rendered(self, client, user_a, company_a):
        site = _site(company_a)
        client.force_login(user_a)
        response = client.get(reverse("sites:detail", args=[site.pk]))

        assert response.status_code == 200
        assert "内訳書・内訳明細書" in response.content.decode()

    def test_lines_and_total_are_shown(self, client, user_a, company_a):
        site = _site(company_a)
        _line(
            company_a, site, "VVFケーブル", spec="1.6mm 2芯", unit="m",
            quantity=Decimal("1200"), unit_price=Decimal("150"),
            amount=Decimal("180000"),
        )
        client.force_login(user_a)
        response = client.get(reverse("sites:detail", args=[site.pk]))
        body = response.content.decode()

        assert "VVFケーブル" in body
        assert "1.6mm 2芯" in body
        assert response.context["boq_total"] == Decimal("180000")
        assert response.context["boq_meisai_count"] == 1

    def test_total_counts_top_level_only(self, client, user_a, company_a):
        """種目を立てた内訳書で、上位行と細目を二重に数えない。"""
        site = _site(company_a)
        parent = _line(
            company_a, site, "電気設備工事", BoqLine.Level.SHUMOKU,
            order=1, amount=Decimal("180000"),
        )
        _line(
            company_a, site, "VVFケーブル", BoqLine.Level.SAIMOKU,
            order=2, amount=Decimal("180000"), parent=parent,
        )
        client.force_login(user_a)
        response = client.get(reverse("sites:detail", args=[site.pk]))

        assert response.context["boq_total"] == Decimal("180000")


@pytest.mark.django_db
class TestSiteBoqEdit:
    def _post_data(self, rows, initial=0):
        data = {
            "form-TOTAL_FORMS": str(len(rows)),
            "form-INITIAL_FORMS": str(initial),
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
        }
        for i, row in enumerate(rows):
            for key, value in row.items():
                data[f"form-{i}-{key}"] = value
        return data

    def test_creates_rows_from_table(self, client, user_a, company_a):
        site = _site(company_a)
        client.force_login(user_a)

        response = client.post(
            reverse("sites:boq_edit", args=[site.pk]),
            self._post_data([
                {"level": BoqLine.Level.KAMOKU, "name": "電灯設備"},
                {
                    "level": BoqLine.Level.SAIMOKU, "name": "VVFケーブル",
                    "spec": "1.6mm 2芯", "unit": "m",
                    "quantity": "1200", "unit_price": "150",
                },
                {"level": "", "name": ""},   # 空行
            ]),
        )

        assert response.status_code == 302
        lines = list(BoqLine.unscoped.filter(site=site).order_by("sort_order"))
        assert [line.name for line in lines] == ["電灯設備", "VVFケーブル"]
        assert lines[1].amount == Decimal("180000")
        assert lines[1].parent == lines[0]

    def test_blank_rows_do_not_error(self, client, user_a, company_a):
        site = _site(company_a)
        client.force_login(user_a)
        response = client.post(
            reverse("sites:boq_edit", args=[site.pk]),
            self._post_data([{"level": "", "name": ""} for _ in range(5)]),
        )
        assert response.status_code == 302
        assert BoqLine.unscoped.filter(site=site).count() == 0

    def test_level_defaults_from_numbers(self, client, user_a, company_a):
        """階層未指定でも、数量があれば内訳明細書として保存する。"""
        site = _site(company_a)
        client.force_login(user_a)
        client.post(
            reverse("sites:boq_edit", args=[site.pk]),
            self._post_data([
                {"level": "", "name": "VVFケーブル", "quantity": "10", "unit_price": "100"},
            ]),
        )
        line = BoqLine.unscoped.get(site=site)
        assert line.level == BoqLine.MEISAI_LEVEL

    def test_saved_line_belongs_to_site_not_project(self, client, user_a, company_a):
        site = _site(company_a)
        client.force_login(user_a)
        client.post(
            reverse("sites:boq_edit", args=[site.pk]),
            self._post_data([{"level": BoqLine.Level.SAIMOKU, "name": "VVF"}]),
        )
        line = BoqLine.unscoped.get(site=site)
        assert line.project_id is None
        assert line.company_id == company_a.id


@pytest.mark.django_db
class TestSiteBoqImportView:
    def test_uploads_excel_and_redirects(self, client, user_a, company_a):
        from django.core.files.uploadedfile import SimpleUploadedFile

        site = _site(company_a)
        client.force_login(user_a)
        data = _excel_bytes([
            HEADER,
            ["細目別", "VVFケーブル", "1.6-2C", "m", 1200, 150, 180000, ""],
        ])
        upload = SimpleUploadedFile(
            "内訳書.xlsx", data,
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )

        response = client.post(
            reverse("sites:boq_import", args=[site.pk]),
            {"upload": upload, "replace": "on"},
        )

        assert response.status_code == 302
        line = BoqLine.unscoped.get(site=site)
        assert line.name == "VVFケーブル"
        assert line.amount == Decimal("180000")

    def test_unreadable_file_stays_on_page(self, client, user_a, company_a):
        from django.core.files.uploadedfile import SimpleUploadedFile

        site = _site(company_a)
        client.force_login(user_a)
        upload = SimpleUploadedFile("内訳書.xlsx", b"broken")

        response = client.post(
            reverse("sites:boq_import", args=[site.pk]),
            {"upload": upload},
        )

        assert response.status_code == 200
        assert BoqLine.unscoped.filter(site=site).count() == 0


@pytest.mark.django_db
class TestSiteBoqExport:
    def test_downloads_excel(self, client, user_a, company_a):
        site = _site(company_a)
        _line(
            company_a, site, "VVFケーブル", unit="m",
            quantity=Decimal("1200"), unit_price=Decimal("150"),
            amount=Decimal("180000"),
        )
        client.force_login(user_a)
        response = client.get(reverse("sites:boq_export", args=[site.pk]))

        assert response.status_code == 200
        assert "spreadsheetml" in response["Content-Type"]

        wb = openpyxl.load_workbook(io.BytesIO(response.content))
        # 名称セルは階層ぶんのインデントが付くので、前後の空白を落として比べる。
        values = [
            str(cell.value).strip()
            for row in wb["内訳書"].iter_rows()
            for cell in row
            if cell.value is not None
        ]
        assert "VVFケーブル" in values
        assert site.name in values
        assert "180000" in values or 180000 in [
            cell.value
            for row in wb["内訳書"].iter_rows()
            for cell in row
        ]

    def test_export_requires_one_owner(self, company_a):
        with pytest.raises(ValueError):
            export_boq_to_excel()

    def test_roundtrip_export_then_import(self, company_a):
        """出力した Excel を読み戻せる（階層列を自分で書いているため）。"""
        site = _site(company_a)
        parent = _line(
            company_a, site, "電灯設備", BoqLine.Level.KAMOKU,
            order=1, amount=Decimal("180000"),
        )
        _line(
            company_a, site, "VVFケーブル", BoqLine.Level.SAIMOKU, order=2,
            spec="1.6-2C", unit="m", quantity=Decimal("1200"),
            unit_price=Decimal("150"), amount=Decimal("180000"), parent=parent,
        )

        result = boq_import.parse_excel(export_boq_to_excel(site=site))

        names = [d.name for d in result.drafts]
        assert "電灯設備" in names
        assert "VVFケーブル" in names
        meisai = next(d for d in result.drafts if d.name == "VVFケーブル")
        assert meisai.level == BoqLine.Level.SAIMOKU
        assert meisai.quantity == Decimal("1200")
