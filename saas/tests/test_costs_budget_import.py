"""現場見積もり TOP の受け口から、見積書で実行予算を起こす。

明細の読み取り自体は test_sites_line_import.py で固めてあるので、ここでは
「工種 × 原価区分をどう決めるか」を中心に見る。予算・原価はこの粒度で持つのが
前提（CLAUDE.md 規律5）なので、**片方でも欠けた行は登録しない**ことを固定する。
"""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.core.tenant_context import set_current_company
from apps.costs.models import BudgetItem
from apps.masters.models import CostCategory, WorkType
from apps.sites.line_items import extract_lines, serialize_lines
from apps.sites.models import Site

ESTIMATE_CSV = """御見積書,,,,,
工事件名,○○ビル 電気設備改修工事,,,,
,,,,,
No,名称,規格,数量,単位,単価,金額
1,VVFケーブル,1.6mm 3心,120,m,"1,200","144,000"
2,PF管,22mm,80,m,320,"25,600"
3,配線工事,一式,,式,,"90,000"
合計,,,,,,"259,600"
"""


@pytest.fixture
def cost_categories(db):
    """建設業4原価区分。"""
    cats = {}
    for code, name, order in [
        ("material", "材料費", 1),
        ("labor", "労務費", 2),
        ("outsourcing", "外注費", 3),
        ("expense", "経費", 4),
    ]:
        cats[code], _ = CostCategory.objects.get_or_create(
            code=code, defaults={"name": name, "display_order": order},
        )
    return cats


@pytest.fixture
def admin_a(company_a):
    """原価モジュールの write 権限を持つユーザー。superuser は常に全権限。"""
    return User.objects.create_superuser(
        username="admin_a", password="testpass123", company=company_a,
    )


@pytest.fixture
def site_a(company_a):
    return Site.unscoped.create(
        company=company_a, code="S-001", name="○○ビル 電気設備改修工事",
        status=Site.Status.IN_PROGRESS,
    )


@pytest.fixture
def work_types_a(company_a):
    return {
        "power": WorkType.unscoped.create(
            company=company_a, code="W01", name="幹線・動力", is_active=True,
        ),
        "weak": WorkType.unscoped.create(
            company=company_a, code="W02", name="弱電", is_active=True,
        ),
    }


def _write_csv(tmp_path, text, encoding="cp932", name="estimate.csv"):
    path = tmp_path / name
    path.write_text(text, encoding=encoding)
    return path


def _lines_json():
    return serialize_lines(extract_lines([
        ["名称", "規格", "数量", "単位", "単価", "金額"],
        ["VVFケーブル", "1.6mm 3心", "120", "m", "1200", "144000"],
        ["PF管", "22mm", "80", "m", "320", "25600"],
    ]))


# ---------------------------------------------------------------------------
# TOP の受け口
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestIntakeOnTopScreen:
    def test_top_screen_shows_the_upload_form(
        self, client, company_a, admin_a, site_a, work_types_a, cost_categories
    ):
        set_current_company(company_a)
        client.force_login(admin_a)

        body = client.get(reverse("costs:list")).content.decode("utf-8")

        assert "見積書を読み込む" in body
        assert reverse("costs:budget_import") in body
        assert 'name="file"' in body
        assert 'name="site"' in body
        assert 'name="default_work_type"' in body
        assert 'name="default_cost_category"' in body
        set_current_company(None)

    def test_the_form_accepts_pdf_and_excel(
        self, client, company_a, admin_a, site_a, work_types_a, cost_categories
    ):
        """受け口の accept 属性に PDF と Excel が入っていること。"""
        set_current_company(company_a)
        client.force_login(admin_a)

        body = client.get(reverse("costs:list")).content.decode("utf-8")

        assert ".pdf" in body
        assert ".xlsx" in body
        set_current_company(None)

    def test_uploading_shows_the_confirmation_screen(
        self, client, tmp_path, company_a, admin_a, site_a, work_types_a,
        cost_categories,
    ):
        set_current_company(company_a)
        client.force_login(admin_a)

        with open(_write_csv(tmp_path, ESTIMATE_CSV), "rb") as f:
            res = client.post(reverse("costs:budget_import"), {
                "site": site_a.pk,
                "default_work_type": work_types_a["power"].pk,
                "default_cost_category": cost_categories["material"].pk,
                "file": f,
            })
        body = res.content.decode("utf-8")

        assert res.status_code == 200
        assert "読み取った明細（3 件）" in body
        assert "VVFケーブル" in body
        assert "配線工事" in body            # 一式の行も出る
        assert "幹線・動力" in body           # 工種の既定値
        set_current_company(None)

    def test_a_file_without_lines_does_not_reach_the_confirmation(
        self, client, tmp_path, company_a, admin_a, site_a, work_types_a,
        cost_categories,
    ):
        """ヘッダが無いファイルは推測で拾わない。確認画面まで進めない。"""
        set_current_company(company_a)
        client.force_login(admin_a)

        with open(_write_csv(tmp_path, "工事件名,配線工事のみ\n"), "rb") as f:
            res = client.post(reverse("costs:budget_import"), {
                "site": site_a.pk,
                "default_work_type": work_types_a["power"].pk,
                "default_cost_category": cost_categories["material"].pk,
                "file": f,
            }, follow=True)

        assert "明細を読み取れませんでした" in res.content.decode("utf-8")
        assert not BudgetItem.unscoped.filter(company=company_a).exists()
        set_current_company(None)


# ---------------------------------------------------------------------------
# 確認画面からの登録
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestConfirmCreatesBudget:
    def _confirm(self, client, site, lines_json, rows):
        payload = {
            "step": "confirm",
            "site": site.pk,
            "lines_json": lines_json,
        }
        for index, row in rows.items():
            if row.get("include", True):
                payload[f"include_{index}"] = "1"
            if row.get("work_type") is not None:
                payload[f"work_type_{index}"] = row["work_type"]
            if row.get("cost_category") is not None:
                payload[f"cost_category_{index}"] = row["cost_category"]
        return client.post(reverse("costs:budget_import"), payload)

    def test_creates_one_budget_item_per_line(
        self, client, company_a, admin_a, site_a, work_types_a, cost_categories
    ):
        set_current_company(company_a)
        client.force_login(admin_a)

        res = self._confirm(client, site_a, _lines_json(), {
            0: {"work_type": work_types_a["power"].pk,
                "cost_category": cost_categories["material"].pk},
            1: {"work_type": work_types_a["power"].pk,
                "cost_category": cost_categories["material"].pk},
        })

        items = list(BudgetItem.unscoped.filter(company=company_a, site=site_a))
        assert res.status_code == 302
        assert len(items) == 2
        assert items[0].name == "VVFケーブル"
        assert items[0].unit == "m"
        assert items[0].quantity == Decimal("120")
        assert items[0].unit_price == Decimal("1200")
        assert items[0].amount == Decimal("144000")
        assert items[0].work_type == work_types_a["power"]
        assert items[0].cost_category == cost_categories["material"]
        set_current_company(None)

    def test_each_line_can_have_its_own_classification(
        self, client, company_a, admin_a, site_a, work_types_a, cost_categories
    ):
        """行ごとに工種・原価区分を変えられる。粒度を落とさないための要。"""
        set_current_company(company_a)
        client.force_login(admin_a)

        self._confirm(client, site_a, _lines_json(), {
            0: {"work_type": work_types_a["power"].pk,
                "cost_category": cost_categories["material"].pk},
            1: {"work_type": work_types_a["weak"].pk,
                "cost_category": cost_categories["outsourcing"].pk},
        })

        items = {i.name: i for i in BudgetItem.unscoped.filter(site=site_a)}
        assert items["VVFケーブル"].work_type == work_types_a["power"]
        assert items["VVFケーブル"].cost_category == cost_categories["material"]
        assert items["PF管"].work_type == work_types_a["weak"]
        assert items["PF管"].cost_category == cost_categories["outsourcing"]
        set_current_company(None)

    def test_unchecked_lines_are_skipped(
        self, client, company_a, admin_a, site_a, work_types_a, cost_categories
    ):
        set_current_company(company_a)
        client.force_login(admin_a)

        self._confirm(client, site_a, _lines_json(), {
            0: {"work_type": work_types_a["power"].pk,
                "cost_category": cost_categories["material"].pk},
            1: {"include": False,
                "work_type": work_types_a["power"].pk,
                "cost_category": cost_categories["material"].pk},
        })

        names = list(
            BudgetItem.unscoped.filter(site=site_a).values_list("name", flat=True)
        )
        assert names == ["VVFケーブル"]
        set_current_company(None)

    def test_a_line_without_a_work_type_is_not_created(
        self, client, company_a, admin_a, site_a, work_types_a, cost_categories
    ):
        """工種が欠けた行は登録しない。既定値で埋めると予実の集計が崩れる。"""
        set_current_company(company_a)
        client.force_login(admin_a)

        self._confirm(client, site_a, _lines_json(), {
            0: {"work_type": work_types_a["power"].pk,
                "cost_category": cost_categories["material"].pk},
            1: {"work_type": None,
                "cost_category": cost_categories["material"].pk},
        })

        names = list(
            BudgetItem.unscoped.filter(site=site_a).values_list("name", flat=True)
        )
        assert names == ["VVFケーブル"]
        set_current_company(None)

    def test_a_line_with_only_an_amount_is_created_with_zero_quantity(
        self, client, company_a, admin_a, site_a, work_types_a, cost_categories
    ):
        """「一式」の行。金額は読み取った値がそのまま入り、予算合計はずれない。"""
        set_current_company(company_a)
        client.force_login(admin_a)

        lines_json = serialize_lines(extract_lines([
            ["名称", "数量", "単位", "単価", "金額"],
            ["配線工事", "", "式", "", "90000"],
        ]))
        self._confirm(client, site_a, lines_json, {
            0: {"work_type": work_types_a["power"].pk,
                "cost_category": cost_categories["labor"].pk},
        })

        item = BudgetItem.unscoped.get(site=site_a)
        assert item.name == "配線工事"
        assert item.quantity == 0
        assert item.unit_price == 0
        assert item.amount == Decimal("90000")
        set_current_company(None)

    def test_does_not_use_a_work_type_from_another_company(
        self, client, company_a, company_b, admin_a, site_a, cost_categories
    ):
        """他社の工種の pk を送られても拾わない。"""
        set_current_company(company_a)
        own = WorkType.unscoped.create(
            company=company_a, code="W01", name="幹線・動力", is_active=True,
        )
        foreign = WorkType.unscoped.create(
            company=company_b, code="W99", name="他社の工種", is_active=True,
        )
        client.force_login(admin_a)

        self._confirm(client, site_a, _lines_json(), {
            0: {"work_type": own.pk, "cost_category": cost_categories["material"].pk},
            1: {"work_type": foreign.pk,
                "cost_category": cost_categories["material"].pk},
        })

        items = list(BudgetItem.unscoped.filter(site=site_a))
        assert len(items) == 1
        assert items[0].work_type == own
        assert not BudgetItem.unscoped.filter(work_type=foreign).exists()
        set_current_company(None)

    def test_cannot_target_another_companys_site(
        self, client, company_a, company_b, admin_a, work_types_a, cost_categories
    ):
        set_current_company(company_a)
        foreign_site = Site.unscoped.create(
            company=company_b, code="S-999", name="他社の現場",
        )
        client.force_login(admin_a)

        res = self._confirm(client, foreign_site, _lines_json(), {
            0: {"work_type": work_types_a["power"].pk,
                "cost_category": cost_categories["material"].pk},
        })

        assert res.status_code == 404
        assert not BudgetItem.unscoped.filter(site=foreign_site).exists()
        set_current_company(None)

    def test_nothing_selected_creates_nothing(
        self, client, company_a, admin_a, site_a, work_types_a, cost_categories
    ):
        set_current_company(company_a)
        client.force_login(admin_a)

        res = self._confirm(client, site_a, _lines_json(), {
            0: {"include": False}, 1: {"include": False},
        })

        assert res.status_code == 302
        assert not BudgetItem.unscoped.filter(site=site_a).exists()
        set_current_company(None)
