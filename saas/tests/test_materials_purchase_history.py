"""材料別の取引履歴（ADR-0034）。

発注明細を材料ごとにまとめ、検収済みの分だけ調達実績から納品日・
リードタイムを足す。固定したいのは次の点:

1. 材料マスタの明細はマスタ単位、自由入力の明細は表記ゆれを潰した名前でまとまる
2. 下書き・取消は数えない。仕入先・現場・期間・キーワードで絞れる
3. 集計（件数・単価の最新/最安/最高・仕入先数）が Decimal のまま正しい
4. 他社の発注は出ない。画面はおかしなパラメータでも落ちない
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from apps.core.tenant_context import set_current_company
from apps.masters.models import Supplier
from apps.materials import purchase_history
from apps.materials.models import (
    Material,
    ProcurementRecord,
    PurchaseOrder,
    PurchaseOrderItem,
)
from apps.materials.purchase_history import search_purchase_history
from apps.sites.models import Site

Status = PurchaseOrder.Status


@pytest.fixture
def data_a(company_a):
    """A社の現場2・仕入先2・材料2。"""
    return {
        "site1": Site.unscoped.create(company=company_a, code="S01", name="A社ビル新築"),
        "site2": Site.unscoped.create(company=company_a, code="S02", name="A社工場改修"),
        "sup1": Supplier.unscoped.create(company=company_a, code="SP1", name="東電材"),
        "sup2": Supplier.unscoped.create(company=company_a, code="SP2", name="西電設"),
        "cable": Material.unscoped.create(
            company=company_a, code="M01", name="VVFケーブル 1.6-2C", unit="m",
        ),
        "box": Material.unscoped.create(
            company=company_a, code="M02", name="スイッチボックス", unit="個",
        ),
    }


def _po(company, site, supplier, order_date, status=Status.ORDERED):
    return PurchaseOrder.unscoped.create(
        company=company, site=site, supplier=supplier,
        order_date=order_date, status=status,
    )


def _line(po, *, material=None, name="", quantity="1", unit_price="100", unit=""):
    return PurchaseOrderItem.unscoped.create(
        company=po.company, purchase_order=po, material=material, material_name=name,
        quantity=Decimal(quantity), unit_price=Decimal(unit_price), unit=unit,
    )


def _names(history):
    return [m.name for m in history.materials]


# ---------------------------------------------------------------------------
# まとめ方と集計
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGrouping:
    def test_materials_are_ordered_by_latest_order_and_transactions_newest_first(
        self, company_a, data_a,
    ):
        d = data_a
        old = _po(company_a, d["site1"], d["sup1"], date(2026, 8, 1))
        mid = _po(company_a, d["site1"], d["sup1"], date(2026, 8, 15))
        new = _po(company_a, d["site2"], d["sup2"], date(2026, 9, 1))
        _line(old, material=d["cable"], quantity="100", unit_price="100")
        _line(mid, material=d["box"], quantity="10", unit_price="300")
        _line(new, material=d["cable"], quantity="50", unit_price="120")

        history = search_purchase_history(company_a)

        assert _names(history) == ["VVFケーブル 1.6-2C", "スイッチボックス"]
        cable = history.materials[0]
        assert [t.purchase_order_id for t in cable.transactions] == [new.pk, old.pk]
        assert cable.material_id == d["cable"].pk
        assert cable.code == "M01"
        assert history.transaction_count == 3
        assert history.truncated is False

    def test_free_text_lines_are_grouped_by_normalized_name(self, company_a, data_a):
        d = data_a
        po1 = _po(company_a, d["site1"], d["sup1"], date(2026, 8, 1))
        po2 = _po(company_a, d["site1"], d["sup2"], date(2026, 8, 20))
        _line(po1, name="ＰＦ管 22", unit="m")
        _line(po2, name="pf管22", unit="m")
        _line(po2, name="結束バンド", unit="袋")

        history = search_purchase_history(company_a)

        assert len(history.materials) == 2
        pf = history.materials[0]
        assert pf.material_id is None
        assert pf.name == "pf管22"  # 新しい明細の表記を出す
        assert pf.count == 2
        assert {m.name for m in history.materials} == {"pf管22", "結束バンド"}

    def test_free_text_and_master_lines_are_not_merged(self, company_a, data_a):
        d = data_a
        po = _po(company_a, d["site1"], d["sup1"], date(2026, 8, 1))
        _line(po, material=d["box"])
        _line(po, name="スイッチボックス")

        history = search_purchase_history(company_a)

        assert sorted((m.material_id is None) for m in history.materials) == [False, True]

    def test_summary_numbers_are_decimal(self, company_a, data_a):
        d = data_a
        po1 = _po(company_a, d["site1"], d["sup1"], date(2026, 7, 1))
        po2 = _po(company_a, d["site1"], d["sup2"], date(2026, 8, 1))
        po3 = _po(company_a, d["site2"], d["sup1"], date(2026, 9, 1))
        _line(po1, material=d["cable"], quantity="100", unit_price="95.50")
        _line(po2, material=d["cable"], quantity="30.5", unit_price="130")
        _line(po3, material=d["cable"], quantity="20", unit_price="110", unit="m")

        cable = search_purchase_history(company_a).materials[0]

        assert cable.count == 3
        assert cable.latest_unit_price == Decimal("110")
        assert cable.last_order_date == date(2026, 9, 1)
        assert cable.min_unit_price == Decimal("95.50")
        assert cable.max_unit_price == Decimal("130")
        assert cable.supplier_count == 2
        # 単位が空の明細は材料マスタの単位で数える
        assert cable.total_quantities == [("m", Decimal("150.5"))]
        amounts = [t.amount for t in cable.transactions]
        assert amounts == [Decimal("2200"), Decimal("3965"), Decimal("9550")]
        assert all(isinstance(a, Decimal) for a in amounts)
        assert isinstance(cable.total_quantities[0][1], Decimal)

    def test_quantities_in_different_units_are_totalled_separately(self, company_a, data_a):
        d = data_a
        po = _po(company_a, d["site1"], d["sup1"], date(2026, 8, 1))
        _line(po, material=d["cable"], quantity="100", unit="m")
        _line(po, material=d["cable"], quantity="2", unit="巻")
        _line(po, material=d["cable"], quantity="50", unit="m")

        cable = search_purchase_history(company_a).materials[0]

        assert cable.total_quantities == [("m", Decimal("150")), ("巻", Decimal("2"))]

    def test_runs_in_two_queries_regardless_of_rows(
        self, company_a, data_a, django_assert_max_num_queries,
    ):
        d = data_a
        for day in range(1, 6):
            po = _po(company_a, d["site1"], d["sup1"], date(2026, 8, day))
            _line(po, material=d["cable"])
            _line(po, material=d["box"])
            _line(po, name="自由入力の材料")

        with django_assert_max_num_queries(2):
            history = search_purchase_history(company_a)
            shown = [
                (t.supplier_name, t.site_name, t.status_label, t.delivered_date)
                for m in history.materials for t in m.transactions
            ]
        assert len(shown) == 15


# ---------------------------------------------------------------------------
# 絞り込み
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestFilters:
    @pytest.fixture
    def orders(self, company_a, data_a):
        d = data_a
        po1 = _po(company_a, d["site1"], d["sup1"], date(2026, 7, 10))
        po2 = _po(company_a, d["site2"], d["sup2"], date(2026, 8, 10))
        po3 = _po(company_a, d["site1"], d["sup2"], date(2026, 9, 10))
        _line(po1, material=d["cable"])
        _line(po2, material=d["box"])
        _line(po3, name="支持金具 手配品")
        return po1, po2, po3

    def test_keyword_matches_material_name(self, company_a, orders):
        assert _names(search_purchase_history(company_a, q="ケーブル")) == ["VVFケーブル 1.6-2C"]

    def test_keyword_matches_material_code(self, company_a, orders):
        assert _names(search_purchase_history(company_a, q="m02")) == ["スイッチボックス"]

    def test_keyword_matches_free_text_name(self, company_a, orders):
        assert _names(search_purchase_history(company_a, q="手配")) == ["支持金具 手配品"]

    def test_keyword_terms_are_all_required(self, company_a, orders):
        # 全角スペース区切りでも語に分ける
        assert _names(search_purchase_history(company_a, q="vvf　1.6")) == [
            "VVFケーブル 1.6-2C",
        ]
        assert _names(search_purchase_history(company_a, q="vvf ボックス")) == []

    def test_supplier_filter(self, company_a, data_a, orders):
        history = search_purchase_history(company_a, supplier_id=data_a["sup2"].pk)
        assert _names(history) == ["支持金具 手配品", "スイッチボックス"]

    def test_site_filter(self, company_a, data_a, orders):
        history = search_purchase_history(company_a, site_id=data_a["site2"].pk)
        assert _names(history) == ["スイッチボックス"]

    def test_date_range_is_inclusive_on_order_date(self, company_a, orders):
        history = search_purchase_history(
            company_a, date_from=date(2026, 7, 10), date_to=date(2026, 8, 10),
        )
        assert _names(history) == ["スイッチボックス", "VVFケーブル 1.6-2C"]
        assert _names(search_purchase_history(company_a, date_from=date(2026, 8, 11))) == [
            "支持金具 手配品",
        ]

    def test_draft_and_cancelled_orders_are_excluded(self, company_a, data_a):
        d = data_a
        for status in (Status.DRAFT, Status.CANCELLED):
            _line(_po(company_a, d["site1"], d["sup1"], date(2026, 9, 1), status), name=status)
        for status in (Status.ORDERED, Status.PARTIALLY_RECEIVED, Status.RECEIVED):
            _line(_po(company_a, d["site1"], d["sup1"], date(2026, 9, 1), status), name=status)

        names = set(_names(search_purchase_history(company_a)))

        assert names == {"ordered", "partially_received", "received"}

    def test_truncates_at_limit(self, company_a, data_a):
        d = data_a
        for day in (1, 2, 3):
            _line(_po(company_a, d["site1"], d["sup1"], date(2026, 8, day)), material=d["cable"])

        history = search_purchase_history(company_a, limit=2)
        assert history.truncated is True
        assert history.transaction_count == 2
        # 新しい方から残す
        assert history.materials[0].last_order_date == date(2026, 8, 3)
        assert history.materials[0].transactions[-1].order_date == date(2026, 8, 2)

        assert search_purchase_history(company_a, limit=3).truncated is False


# ---------------------------------------------------------------------------
# 調達実績（納品日・リードタイム）
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestProcurementInfo:
    def test_delivery_info_is_attached_only_when_a_matching_record_exists(
        self, company_a, data_a,
    ):
        d = data_a
        inspected = _po(company_a, d["site1"], d["sup1"], date(2026, 8, 1), Status.RECEIVED)
        pending = _po(company_a, d["site1"], d["sup1"], date(2026, 8, 5))
        cable_line = _line(inspected, material=d["cable"])
        box_line = _line(inspected, material=d["box"])
        free_line = _line(inspected, name="自由入力")
        pending_line = _line(pending, material=d["cable"])
        ProcurementRecord.unscoped.create(
            company=company_a, site=d["site1"], material=d["cable"], supplier=d["sup1"],
            purchase_order=inspected, ordered_date=date(2026, 8, 1),
            delivered_date=date(2026, 8, 6), actual_lead_days=5,
            ordered_qty=Decimal("1"), unit_price_paid=Decimal("100"),
        )

        history = search_purchase_history(company_a)
        by_item = {t.item_id: t for m in history.materials for t in m.transactions}

        assert by_item[cable_line.pk].delivered_date == date(2026, 8, 6)
        assert by_item[cable_line.pk].lead_days == 5
        # 同じ発注書でも別の材料・自由入力には付けない。未検収の発注にも付けない
        for line in (box_line, free_line, pending_line):
            assert by_item[line.pk].delivered_date is None
            assert by_item[line.pk].lead_days is None

    def test_record_of_another_company_is_ignored(self, company_a, company_b, data_a):
        d = data_a
        po = _po(company_a, d["site1"], d["sup1"], date(2026, 8, 1), Status.RECEIVED)
        line = _line(po, material=d["cable"])
        # 本来ありえないが、他社の調達実績が発注書を指していても拾わないこと
        ProcurementRecord.unscoped.create(
            company=company_b, site=d["site1"], material=d["cable"], supplier=d["sup1"],
            purchase_order=po, ordered_date=date(2026, 8, 1),
            delivered_date=date(2026, 8, 3), actual_lead_days=2,
            ordered_qty=Decimal("1"), unit_price_paid=Decimal("100"),
        )

        transaction = search_purchase_history(company_a).materials[0].transactions[0]

        assert transaction.item_id == line.pk
        assert transaction.delivered_date is None


# ---------------------------------------------------------------------------
# テナント分離
# ---------------------------------------------------------------------------

@pytest.fixture
def data_b(company_b):
    site = Site.unscoped.create(company=company_b, code="S01", name="B社内装改修")
    supplier = Supplier.unscoped.create(company=company_b, code="SP1", name="B社の仕入先")
    material = Material.unscoped.create(
        company=company_b, code="M01", name="B社だけの石膏ボード", unit="枚",
    )
    po = _po(company_b, site, supplier, date(2026, 9, 5))
    _line(po, material=material)
    _line(po, name="B社の自由入力")
    return {"site": site, "supplier": supplier, "material": material, "po": po}


@pytest.mark.django_db
class TestTenantIsolation:
    def test_other_company_lines_never_appear(self, company_a, data_a, data_b):
        po = _po(company_a, data_a["site1"], data_a["sup1"], date(2026, 8, 1))
        _line(po, material=data_a["cable"])

        assert _names(search_purchase_history(company_a)) == ["VVFケーブル 1.6-2C"]
        assert _names(search_purchase_history(company_a, q="B社")) == []
        assert _names(
            search_purchase_history(company_a, supplier_id=data_b["supplier"].pk),
        ) == []
        assert _names(search_purchase_history(company_a, site_id=data_b["site"].pk)) == []

    def test_other_company_sees_only_its_own(self, company_b, data_a, data_b):
        assert set(_names(search_purchase_history(company_b))) == {
            "B社だけの石膏ボード", "B社の自由入力",
        }


# ---------------------------------------------------------------------------
# 画面
# ---------------------------------------------------------------------------

@pytest.fixture
def logged_in(client, company_a, user_a):
    set_current_company(company_a)
    client.force_login(user_a)
    yield client
    set_current_company(None)


@pytest.mark.django_db
class TestView:
    url = "/materials/history/"

    def test_url_name(self):
        assert reverse("materials:purchase_history") == self.url

    def test_anonymous_is_redirected_to_login(self, client):
        res = client.get(self.url)
        assert res.status_code == 302

    def test_renders_empty_state_without_data(self, logged_in):
        res = logged_in.get(self.url)
        assert res.status_code == 200
        assert "材料別の取引履歴" in res.content.decode()
        assert "発注の記録がまだありません" in res.content.decode()

    def test_renders_materials_with_links_and_choices(self, logged_in, company_a, data_a, data_b):
        d = data_a
        po = _po(company_a, d["site1"], d["sup1"], date(2026, 8, 1), Status.RECEIVED)
        _line(po, material=d["cable"], quantity="1200", unit_price="1234.5")

        res = logged_in.get(self.url)
        body = res.content.decode()

        assert res.status_code == 200
        assert "VVFケーブル 1.6-2C" in body
        assert reverse("materials:po_detail", args=[po.pk]) in body
        assert f"?supplier={d['sup1'].pk}" in body
        assert "¥1,481,400" in body  # 1200 × 1234.5
        # 選択肢は自社の仕入先・現場だけ。他社のデータは画面のどこにも出ない
        assert "西電設" in body and "A社工場改修" in body
        assert "B社" not in body

    def test_filters_are_applied_and_kept_in_the_form(self, logged_in, company_a, data_a):
        d = data_a
        _line(_po(company_a, d["site1"], d["sup1"], date(2026, 8, 1)), material=d["cable"])
        _line(_po(company_a, d["site2"], d["sup2"], date(2026, 9, 1)), material=d["box"])

        res = logged_in.get(self.url, {
            "q": "ボックス", "supplier": d["sup2"].pk, "site": d["site2"].pk,
            "date_from": "2026-08-15", "date_to": "2026-09-30",
        })
        body = res.content.decode()

        assert res.status_code == 200
        assert [m.name for m in res.context["history"].materials] == ["スイッチボックス"]
        assert 'value="ボックス"' in body
        assert f'value="{d["sup2"].pk}" selected' in body
        assert 'value="2026-08-15"' in body

    def test_no_match_message(self, logged_in, company_a, data_a):
        _line(_po(company_a, data_a["site1"], data_a["sup1"], date(2026, 8, 1)), name="何か")
        res = logged_in.get(self.url, {"q": "存在しない材料"})
        assert "条件に合う取引がありません" in res.content.decode()

    @pytest.mark.parametrize("params", [
        {"supplier": "abc", "site": "-1"},
        {"supplier": "99999999999999999999999999", "site": "1.5"},
        {"date_from": "2026-13-45", "date_to": "yesterday"},
        {"q": "x" * 1000, "supplier": "", "date_from": ""},
    ])
    def test_invalid_params_do_not_crash(self, logged_in, company_a, data_a, params):
        _line(_po(company_a, data_a["site1"], data_a["sup1"], date(2026, 8, 1)), name="何か")
        res = logged_in.get(self.url, params)
        assert res.status_code == 200

    def test_invalid_params_are_ignored(self, logged_in, company_a, data_a):
        _line(_po(company_a, data_a["site1"], data_a["sup1"], date(2026, 8, 1)), name="何か")
        res = logged_in.get(self.url, {"supplier": "abc", "date_from": "2026-13-45"})
        assert res.context["selected_supplier"] is None
        assert res.context["date_from"] is None
        assert [m.name for m in res.context["history"].materials] == ["何か"]

    def test_truncation_note(self, logged_in, company_a, data_a, monkeypatch):
        monkeypatch.setattr(purchase_history, "TRANSACTION_LIMIT", 1)
        po = _po(company_a, data_a["site1"], data_a["sup1"], date(2026, 8, 1))
        _line(po, name="材料その1")
        _line(po, name="材料その2")

        body = logged_in.get(self.url).content.decode()

        assert "発注日の新しい 1 件までを表示・集計しています" in body

    def test_template_has_no_inline_style(self):
        template = Path(settings.BASE_DIR) / "templates" / "materials" / "purchase_history.html"
        assert 'style="' not in template.read_text(encoding="utf-8")
