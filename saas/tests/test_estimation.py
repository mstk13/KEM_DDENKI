"""積算アプリのテスト。

- テナント越境テスト（EstimationItem, ItemAlias, Orderer, OrdererDataSource）
- 正規化テスト（純粋関数、DB不要）
- マッチングテスト
- M2: 労務単価・積算基準・歩掛
- S2: 有効期間管理・引き当てサービス
- S4: データ所有区分
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError

from apps.core.tenant_context import set_current_company
from apps.estimation.models import (
    EstimationItem,
    EstimationStandard,
    ItemAlias,
    LaborRate,
    Orderer,
    OrdererDataSource,
    OverheadRule,
    WageFloor,
    WorkRate,
)
from apps.estimation.services.normalization import (
    extract_spec,
    normalize,
    normalize_cores,
    normalize_diameter,
    normalize_sq,
    normalize_voltage,
    normalize_width,
)

# ---------------------------------------------------------------------------
# テナント越境テスト
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEstimationItemIsolation:
    def test_item_isolation(self, company_a, company_b):
        EstimationItem.unscoped.create(
            company=company_a, code="W001", canonical_name="600V CV 3C 38sq",
            category="wire", unit="m",
        )
        EstimationItem.unscoped.create(
            company=company_b, code="W001", canonical_name="600V CV 3C 14sq",
            category="wire", unit="m",
        )
        set_current_company(company_a)
        assert EstimationItem.objects.count() == 1
        assert EstimationItem.objects.first().canonical_name == "600V CV 3C 38sq"
        set_current_company(company_b)
        assert EstimationItem.objects.count() == 1
        assert EstimationItem.objects.first().canonical_name == "600V CV 3C 14sq"
        set_current_company(None)

    def test_unique_code_per_company(self, company_a):
        EstimationItem.unscoped.create(
            company=company_a, code="W001", canonical_name="test1",
            category="wire", unit="m",
        )
        with pytest.raises(IntegrityError):
            EstimationItem.unscoped.create(
                company=company_a, code="W001", canonical_name="test2",
                category="wire", unit="m",
            )

    def test_standard_price_is_decimal(self, company_a):
        item = EstimationItem.unscoped.create(
            company=company_a, code="W003", canonical_name="test",
            category="wire", unit="m", standard_price=Decimal("1500"),
        )
        assert isinstance(item.standard_price, Decimal)


@pytest.mark.django_db
class TestItemAliasIsolation:
    def test_alias_isolation(self, company_a, company_b):
        item_a = EstimationItem.unscoped.create(
            company=company_a, code="W001", canonical_name="test",
            category="wire", unit="m",
        )
        ItemAlias.unscoped.create(
            company=company_a, estimation_item=item_a,
            source_type="orderer_boq", raw_name="CV 3×38",
            normalized_name="cv 3c 38sq",
        )
        ItemAlias.unscoped.create(
            company=company_b, source_type="orderer_boq",
            raw_name="CV 3×14", normalized_name="cv 3c 14sq",
        )
        set_current_company(company_a)
        assert ItemAlias.objects.count() == 1
        set_current_company(company_b)
        assert ItemAlias.objects.count() == 1
        set_current_company(None)


@pytest.mark.django_db
class TestOrdererIsolation:
    def test_orderer_isolation(self, company_a, company_b):
        Orderer.unscoped.create(company=company_a, name="国交省", kind="national")
        Orderer.unscoped.create(company=company_b, name="神奈川県", kind="prefecture")
        set_current_company(company_a)
        assert Orderer.objects.count() == 1
        set_current_company(company_b)
        assert Orderer.objects.count() == 1
        set_current_company(None)


@pytest.mark.django_db
class TestOrdererDataSource:
    def test_datasource_isolation(self, company_a, company_b):
        o_a = Orderer.unscoped.create(company=company_a, name="国交省", kind="national")
        o_b = Orderer.unscoped.create(company=company_b, name="神奈川県", kind="prefecture")
        OrdererDataSource.unscoped.create(
            company=company_a, orderer=o_a, category="labor_rate",
            scope="common", name="労務単価",
        )
        OrdererDataSource.unscoped.create(
            company=company_b, orderer=o_b, category="unit_price",
            scope="orderer_own", name="神奈川県設計単価表",
        )
        set_current_company(company_a)
        assert OrdererDataSource.objects.count() == 1
        set_current_company(company_b)
        assert OrdererDataSource.objects.count() == 1
        set_current_company(None)


# ---------------------------------------------------------------------------
# 正規化テスト（DB不要）
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_width_normalization(self):
        assert normalize_width("ＣＶＴ") == "CVT"
        assert normalize_width("１４ｓｑ") == "14sq"

    @pytest.mark.parametrize("input_text,expected", [
        ("38sq", "38sq"), ("38㎟", "38sq"), ("38mm2", "38sq"),
        ("38mm²", "38sq"), ("38SQ", "38sq"), ("38スケア", "38sq"), ("2.0sq", "2.0sq"),
    ])
    def test_normalize_sq(self, input_text, expected):
        assert normalize_sq(input_text) == expected

    @pytest.mark.parametrize("input_text,expected", [
        ("3心", "3C"), ("3芯", "3C"), ("3C", "3C"), ("3c", "3C"),
    ])
    def test_normalize_cores(self, input_text, expected):
        assert normalize_cores(input_text) == expected

    @pytest.mark.parametrize("input_text,expected", [
        ("φ25", "D25"), ("Φ25", "D25"), ("径25", "D25"),
    ])
    def test_normalize_diameter(self, input_text, expected):
        assert normalize_diameter(input_text) == expected

    @pytest.mark.parametrize("input_text,expected", [
        ("600V", "600V"), ("600v", "600V"), ("600ボルト", "600V"),
    ])
    def test_normalize_voltage(self, input_text, expected):
        assert normalize_voltage(input_text) == expected

    def test_full_pipeline(self):
        assert normalize("６００Ｖ　ＣＶ　３心　３８㎟") == "600v cv 3c 38sq"

    def test_full_pipeline_with_multiply(self):
        result = normalize("CV 3×38sq")
        assert "x" in result and "38sq" in result

    def test_empty_string(self):
        assert normalize("") == ""

    def test_extract_spec_cv_cable(self):
        spec = extract_spec("600v cv 3c 38sq")
        assert spec == {"voltage": "600V", "type": "CV", "cores": 3, "size": "38sq"}

    def test_extract_spec_no_match(self):
        assert extract_spec("普通の文字列") == {}


# ---------------------------------------------------------------------------
# マッチングテスト
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMatching:
    def test_match_by_exact_code(self, company_a):
        from apps.estimation.services.matching import match_item
        EstimationItem.unscoped.create(
            company=company_a, code="W001", canonical_name="600V CV 3C 38sq",
            category="wire", unit="m",
        )
        alias = match_item("CV ３×３８", "orderer_boq", "W001", company_a)
        assert alias.estimation_item is not None
        assert alias.confidence == Decimal("100")
        assert alias.matched_by == ItemAlias.MatchMethod.EXACT_CODE

    def test_match_by_normalized_name(self, company_a):
        from apps.estimation.services.matching import match_item
        EstimationItem.unscoped.create(
            company=company_a, code="W002", canonical_name="600V CV 3心 38㎟",
            category="wire", unit="m",
        )
        alias = match_item("600V CV 3芯 38sq", "orderer_boq", "", company_a)
        assert alias.estimation_item is not None
        assert alias.confidence == Decimal("90")

    def test_no_match_creates_pending(self, company_a):
        from apps.estimation.services.matching import match_item
        alias = match_item("存在しない品目ABC", "orderer_boq", "", company_a)
        assert alias.estimation_item is None
        assert alias.status == ItemAlias.Status.PENDING


# ---------------------------------------------------------------------------
# S2: 有効期間管理・引き当てサービス
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLaborRateResolution:
    def test_labor_rate_isolation(self, company_a, company_b):
        LaborRate.unscoped.create(
            company=company_a, prefecture="神奈川県", occupation_code="ELEC",
            occupation_name="電工", unit_price=Decimal("25600"),
            valid_from=date(2026, 3, 1), status="approved", data_scope="public",
        )
        LaborRate.unscoped.create(
            company=company_b, prefecture="東京都", occupation_code="ELEC",
            occupation_name="電工", unit_price=Decimal("27200"),
            valid_from=date(2026, 3, 1), status="approved", data_scope="public",
        )
        set_current_company(company_a)
        assert LaborRate.objects.count() == 1
        assert LaborRate.objects.first().prefecture == "神奈川県"
        set_current_company(company_b)
        assert LaborRate.objects.count() == 1
        set_current_company(None)

    def test_null_unit_price_for_unset_occupation(self, company_a):
        """未設定職種は unit_price=None。0ではない。"""
        rate = LaborRate.unscoped.create(
            company=company_a, prefecture="神奈川県", occupation_code="TATEGU",
            occupation_name="建具工", unit_price=None,
            valid_from=date(2026, 3, 1), status="approved", data_scope="public",
        )
        assert rate.unit_price is None

    def test_resolve_across_march_boundary(self, company_a):
        """2月と3月で異なる単価が引けること（S2-5）。"""
        from apps.estimation.services.resolution import resolve_labor_rate

        # 旧単価（〜2月末）
        LaborRate.unscoped.create(
            company=company_a, prefecture="神奈川県", occupation_code="ELEC",
            occupation_name="電工", unit_price=Decimal("24000"),
            valid_from=date(2025, 3, 1), valid_to=date(2026, 2, 28),
            status="approved", data_scope="public",
        )
        # 新単価（3月〜）
        LaborRate.unscoped.create(
            company=company_a, prefecture="神奈川県", occupation_code="ELEC",
            occupation_name="電工", unit_price=Decimal("25600"),
            valid_from=date(2026, 3, 1),
            status="approved", data_scope="public",
        )
        set_current_company(company_a)
        feb = resolve_labor_rate(
            prefecture="神奈川県", occupation_code="ELEC",
            reference_date=date(2026, 2, 28),
        )
        mar = resolve_labor_rate(
            prefecture="神奈川県", occupation_code="ELEC",
            reference_date=date(2026, 3, 1),
        )
        assert feb.unit_price == Decimal("24000")
        assert mar.unit_price == Decimal("25600")
        assert feb.pk != mar.pk
        set_current_company(None)

    def test_draft_not_resolved(self, company_a):
        """draft ステータスは引き当てに使われない。"""
        from apps.estimation.services.resolution import resolve_labor_rate

        LaborRate.unscoped.create(
            company=company_a, prefecture="神奈川県", occupation_code="ELEC",
            occupation_name="電工", unit_price=Decimal("25600"),
            valid_from=date(2026, 3, 1), status="draft", data_scope="public",
        )
        set_current_company(company_a)
        result = resolve_labor_rate(
            prefecture="神奈川県", occupation_code="ELEC",
            reference_date=date(2026, 3, 1),
        )
        assert result is None
        set_current_company(None)


@pytest.mark.django_db
class TestEstimationStandardResolution:
    def test_standard_with_work_rates(self, company_a):
        orderer = Orderer.unscoped.create(company=company_a, name="国交省", kind="national")
        std = EstimationStandard.unscoped.create(
            company=company_a, orderer=orderer,
            name="公共建築工事積算基準", valid_from=date(2026, 3, 11),
            data_scope="public",
        )
        wr = WorkRate.unscoped.create(
            company=company_a, standard=std,
            work_name="ケーブル配線 CV 38sq以下", unit="m",
            labor=[{"trade": "電工", "qty": 0.12}],
            status="draft", extracted_by="manual", data_scope="public",
        )
        assert std.work_rates.count() == 1
        assert wr.labor[0]["trade"] == "電工"

    def test_cascade_delete(self, company_a):
        orderer = Orderer.unscoped.create(company=company_a, name="削除テスト", kind="national")
        std = EstimationStandard.unscoped.create(
            company=company_a, orderer=orderer,
            name="テスト基準", valid_from=date(2026, 3, 11),
        )
        WorkRate.unscoped.create(company=company_a, standard=std, work_name="テスト", unit="m")
        OverheadRule.unscoped.create(
            company=company_a, standard=std,
            work_category="electrical", cost_type="common_temp", formula="rate=0.1",
        )
        std.delete()
        assert WorkRate.unscoped.filter(company=company_a).count() == 0
        assert OverheadRule.unscoped.filter(company=company_a).count() == 0


# ---------------------------------------------------------------------------
# S4: データ所有区分
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDataScope:
    def test_default_scope_is_tenant(self, company_a):
        item = EstimationItem.unscoped.create(
            company=company_a, code="T001", canonical_name="test",
            category="wire", unit="m",
        )
        assert item.data_scope == "tenant"

    def test_public_scope(self, company_a):
        rate = LaborRate.unscoped.create(
            company=company_a, prefecture="東京都", occupation_code="ELEC",
            occupation_name="電工", unit_price=Decimal("27200"),
            valid_from=date(2026, 3, 1), data_scope="public",
        )
        assert rate.data_scope == "public"

    def test_export_guard(self, company_a):
        from apps.estimation.services.export import DataScopeViolation, check_export_safety

        LaborRate.unscoped.create(
            company=company_a, prefecture="東京都", occupation_code="ELEC",
            occupation_name="電工", unit_price=Decimal("27200"),
            valid_from=date(2026, 3, 1), data_scope="public",
        )
        LaborRate.unscoped.create(
            company=company_a, prefecture="神奈川県", occupation_code="ELEC",
            occupation_name="電工", unit_price=Decimal("25600"),
            valid_from=date(2026, 3, 1), data_scope="tenant",
        )
        set_current_company(company_a)
        # public のみなら OK
        check_export_safety(LaborRate.objects.filter(data_scope="public"))
        # tenant 含むなら例外
        with pytest.raises(DataScopeViolation):
            check_export_safety(LaborRate.objects.all())
        set_current_company(None)


# ---------------------------------------------------------------------------
# S6: WageFloor
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestWageFloor:
    def test_wage_floor_creation(self, company_a):
        wf = WageFloor.unscoped.create(
            company=company_a, municipality="厚木市",
            occupation_code="ELEC", occupation_name="電工",
            hourly_floor=Decimal("2130"),
            valid_from=date(2025, 10, 1),
        )
        assert wf.hourly_floor == Decimal("2130")
        assert wf.worker_type == "regular"

    def test_trainee_floor(self, company_a):
        wf = WageFloor.unscoped.create(
            company=company_a, municipality="厚木市",
            occupation_name="見習い",
            hourly_floor=Decimal("1162"),
            worker_type="trainee",
            valid_from=date(2025, 10, 1),
        )
        assert wf.worker_type == "trainee"


class TestLaborImportParser:
    """都道府県マッチングテスト（DB不要）。"""

    def test_normalize_prefecture(self):
        from apps.estimation.services.labor_import import _normalize_prefecture
        assert _normalize_prefecture("神奈川県") == "神奈川県"
        assert _normalize_prefecture("神奈川") == "神奈川県"
        assert _normalize_prefecture("東京都") == "東京都"
        assert _normalize_prefecture("北海道") == "北海道"
        assert _normalize_prefecture("") is None
        assert _normalize_prefecture("存在しない") is None
