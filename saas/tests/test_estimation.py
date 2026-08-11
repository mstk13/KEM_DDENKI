"""積算アプリのテスト。

- テナント越境テスト（EstimationItem, ItemAlias, Orderer, OrdererDataSource）
- 正規化テスト（純粋関数、DB不要）
- マッチングテスト
"""

from decimal import Decimal

import pytest

from apps.core.tenant_context import set_current_company
from apps.estimation.models import (
    EstimationItem,
    EstimationStandard,
    ItemAlias,
    LaborRate,
    Orderer,
    OrdererDataSource,
    OverheadRule,
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
        with pytest.raises(Exception):
            EstimationItem.unscoped.create(
                company=company_a, code="W001", canonical_name="test2",
                category="wire", unit="m",
            )

    def test_status_default(self, company_a):
        item = EstimationItem.unscoped.create(
            company=company_a, code="W002", canonical_name="test",
            category="wire", unit="m",
        )
        assert item.status == EstimationItem.Status.DRAFT

    def test_standard_price_is_decimal(self, company_a):
        item = EstimationItem.unscoped.create(
            company=company_a, code="W003", canonical_name="test",
            category="wire", unit="m", standard_price=Decimal("1500"),
        )
        assert item.standard_price == Decimal("1500")
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
            company=company_b,
            source_type="orderer_boq", raw_name="CV 3×14",
            normalized_name="cv 3c 14sq",
        )

        set_current_company(company_a)
        assert ItemAlias.objects.count() == 1
        assert ItemAlias.objects.first().raw_name == "CV 3×38"

        set_current_company(company_b)
        assert ItemAlias.objects.count() == 1
        assert ItemAlias.objects.first().raw_name == "CV 3×14"

        set_current_company(None)


@pytest.mark.django_db
class TestOrdererIsolation:
    def test_orderer_isolation(self, company_a, company_b):
        Orderer.unscoped.create(
            company=company_a, name="国土交通省関東地方整備局",
            kind="national", system_type="eizen",
        )
        Orderer.unscoped.create(
            company=company_b, name="神奈川県",
            kind="prefecture", system_type="eizen",
        )

        set_current_company(company_a)
        assert Orderer.objects.count() == 1
        assert Orderer.objects.first().name == "国土交通省関東地方整備局"

        set_current_company(company_b)
        assert Orderer.objects.count() == 1
        assert Orderer.objects.first().name == "神奈川県"

        set_current_company(None)


# ---------------------------------------------------------------------------
# 正規化テスト（DB不要）
# ---------------------------------------------------------------------------


class TestNormalization:
    """正規化モジュールの単体テスト。Django DB を使わない。"""

    def test_width_normalization(self):
        assert normalize_width("ＣＶＴ") == "CVT"
        assert normalize_width("１４ｓｑ") == "14sq"

    @pytest.mark.parametrize("input_text,expected", [
        ("38sq", "38sq"),
        ("38㎟", "38sq"),
        ("38mm2", "38sq"),
        ("38mm²", "38sq"),
        ("38SQ", "38sq"),
        ("38スケア", "38sq"),
        ("2.0sq", "2.0sq"),
    ])
    def test_normalize_sq(self, input_text, expected):
        assert normalize_sq(input_text) == expected

    @pytest.mark.parametrize("input_text,expected", [
        ("3心", "3C"),
        ("3芯", "3C"),
        ("3C", "3C"),
        ("3c", "3C"),
    ])
    def test_normalize_cores(self, input_text, expected):
        assert normalize_cores(input_text) == expected

    @pytest.mark.parametrize("input_text,expected", [
        ("φ25", "D25"),
        ("Φ25", "D25"),
        ("径25", "D25"),
    ])
    def test_normalize_diameter(self, input_text, expected):
        assert normalize_diameter(input_text) == expected

    @pytest.mark.parametrize("input_text,expected", [
        ("600V", "600V"),
        ("600v", "600V"),
        ("600ボルト", "600V"),
    ])
    def test_normalize_voltage(self, input_text, expected):
        assert normalize_voltage(input_text) == expected

    def test_full_pipeline(self):
        result = normalize("６００Ｖ　ＣＶ　３心　３８㎟")
        assert result == "600v cv 3c 38sq"

    def test_full_pipeline_with_multiply(self):
        result = normalize("CV 3×38sq")
        assert "x" in result
        assert "38sq" in result

    def test_empty_string(self):
        assert normalize("") == ""

    def test_extract_spec_cv_cable(self):
        spec = extract_spec("600v cv 3c 38sq")
        assert spec["voltage"] == "600V"
        assert spec["type"] == "CV"
        assert spec["cores"] == 3
        assert spec["size"] == "38sq"

    def test_extract_spec_conduit(self):
        spec = extract_spec("D25")
        assert spec["diameter"] == "D25"

    def test_extract_spec_no_match(self):
        spec = extract_spec("普通の文字列")
        assert spec == {}


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

        alias = match_item(
            raw_name="CV ３×３８",
            source_type="orderer_boq",
            source_key="W001",
            company=company_a,
        )
        assert alias.estimation_item is not None
        assert alias.confidence == Decimal("100")
        assert alias.matched_by == ItemAlias.MatchMethod.EXACT_CODE

    def test_match_by_normalized_name(self, company_a):
        from apps.estimation.services.matching import match_item

        EstimationItem.unscoped.create(
            company=company_a, code="W002",
            canonical_name="600V CV 3心 38㎟",
            category="wire", unit="m",
        )

        alias = match_item(
            raw_name="600V CV 3芯 38sq",
            source_type="orderer_boq",
            source_key="",
            company=company_a,
        )
        assert alias.estimation_item is not None
        assert alias.confidence == Decimal("90")
        assert alias.matched_by == ItemAlias.MatchMethod.NORMALIZED

    def test_match_by_spec(self, company_a):
        from apps.estimation.services.matching import match_item

        EstimationItem.unscoped.create(
            company=company_a, code="W003",
            canonical_name="600V CV 3C 14sq",
            category="wire", unit="m",
            spec={"voltage": "600V", "type": "CV", "cores": 3, "size": "14sq"},
        )

        alias = match_item(
            raw_name="CV 14sq 3心",
            source_type="orderer_boq",
            source_key="",
            company=company_a,
        )
        assert alias.estimation_item is not None
        assert alias.confidence == Decimal("70")
        assert alias.matched_by == ItemAlias.MatchMethod.SPEC_MATCH

    def test_no_match_creates_pending(self, company_a):
        from apps.estimation.services.matching import match_item

        alias = match_item(
            raw_name="存在しない品目ABC",
            source_type="orderer_boq",
            source_key="",
            company=company_a,
        )
        assert alias.estimation_item is None
        assert alias.confidence == Decimal("0")
        assert alias.status == ItemAlias.Status.PENDING

    def test_bulk_match(self, company_a):
        from apps.estimation.services.matching import bulk_match

        EstimationItem.unscoped.create(
            company=company_a, code="W001", canonical_name="600V CV 3C 38sq",
            category="wire", unit="m",
        )

        items = [
            {"raw_name": "テスト品目", "source_type": "orderer_boq", "source_key": "W001"},
            {"raw_name": "不明品目", "source_type": "orderer_boq"},
        ]
        results = bulk_match(items, company_a)
        assert len(results) == 2
        assert results[0].estimation_item is not None
        assert results[1].estimation_item is None


# ---------------------------------------------------------------------------
# データソーステスト
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOrdererDataSource:
    def test_datasource_isolation(self, company_a, company_b):
        orderer_a = Orderer.unscoped.create(
            company=company_a, name="国交省関東", kind="national",
        )
        orderer_b = Orderer.unscoped.create(
            company=company_b, name="神奈川県", kind="prefecture",
        )
        OrdererDataSource.unscoped.create(
            company=company_a, orderer=orderer_a,
            category="labor_rate", scope="common",
            name="公共工事設計労務単価",
        )
        OrdererDataSource.unscoped.create(
            company=company_b, orderer=orderer_b,
            category="unit_price", scope="orderer_own",
            name="神奈川県設計単価表",
        )

        set_current_company(company_a)
        assert OrdererDataSource.objects.count() == 1
        assert OrdererDataSource.objects.first().name == "公共工事設計労務単価"

        set_current_company(company_b)
        assert OrdererDataSource.objects.count() == 1
        assert OrdererDataSource.objects.first().name == "神奈川県設計単価表"

        set_current_company(None)

    def test_unique_per_orderer_category(self, company_a):
        orderer = Orderer.unscoped.create(
            company=company_a, name="テスト機関", kind="national",
        )
        OrdererDataSource.unscoped.create(
            company=company_a, orderer=orderer,
            category="labor_rate", scope="common",
            name="労務単価",
        )
        with pytest.raises(Exception):
            OrdererDataSource.unscoped.create(
                company=company_a, orderer=orderer,
                category="labor_rate", scope="orderer_own",
                name="労務単価（重複テスト）",
            )

    def test_cascade_delete_orderer(self, company_a):
        orderer = Orderer.unscoped.create(
            company=company_a, name="削除テスト", kind="national",
        )
        OrdererDataSource.unscoped.create(
            company=company_a, orderer=orderer,
            category="work_rate", scope="common", name="歩掛",
        )
        orderer.delete()
        assert OrdererDataSource.unscoped.filter(company=company_a).count() == 0

    def test_scope_choices(self, company_a):
        orderer = Orderer.unscoped.create(
            company=company_a, name="スコープテスト", kind="national",
        )
        ds = OrdererDataSource.unscoped.create(
            company=company_a, orderer=orderer,
            category="overhead", scope="partial",
            name="共通費率（一部独自）",
            diff_summary="諸経費率が国基準より2%高い",
        )
        assert ds.scope == "partial"
        assert ds.diff_summary == "諸経費率が国基準より2%高い"


# ---------------------------------------------------------------------------
# M2: 労務単価・積算基準・歩掛テスト
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLaborRate:
    def test_labor_rate_isolation(self, company_a, company_b):
        LaborRate.unscoped.create(
            company=company_a, prefecture="神奈川県", trade="電工",
            fiscal_year=2026, amount=Decimal("25600"),
        )
        LaborRate.unscoped.create(
            company=company_b, prefecture="東京都", trade="電工",
            fiscal_year=2026, amount=Decimal("27200"),
        )

        set_current_company(company_a)
        assert LaborRate.objects.count() == 1
        assert LaborRate.objects.first().prefecture == "神奈川県"

        set_current_company(company_b)
        assert LaborRate.objects.count() == 1
        assert LaborRate.objects.first().prefecture == "東京都"

        set_current_company(None)

    def test_unique_constraint(self, company_a):
        LaborRate.unscoped.create(
            company=company_a, prefecture="神奈川県", trade="電工",
            fiscal_year=2026, amount=Decimal("25600"),
        )
        with pytest.raises(Exception):
            LaborRate.unscoped.create(
                company=company_a, prefecture="神奈川県", trade="電工",
                fiscal_year=2026, amount=Decimal("26000"),
            )

    def test_amount_is_decimal(self, company_a):
        rate = LaborRate.unscoped.create(
            company=company_a, prefecture="東京都", trade="普通作業員",
            fiscal_year=2026, amount=Decimal("22800"),
        )
        assert isinstance(rate.amount, Decimal)


@pytest.mark.django_db
class TestEstimationStandard:
    def test_standard_with_work_rates(self, company_a):
        orderer = Orderer.unscoped.create(
            company=company_a, name="国交省", kind="national",
        )
        std = EstimationStandard.unscoped.create(
            company=company_a, orderer=orderer,
            name="公共建築工事積算基準", fiscal_year=2026,
        )
        wr = WorkRate.unscoped.create(
            company=company_a, standard=std,
            work_name="ケーブル配線 CV 38sq以下", unit="m",
            labor=[{"trade": "電工", "qty": 0.12}],
            status="draft", extracted_by="manual",
        )
        assert std.work_rates.count() == 1
        assert wr.labor[0]["trade"] == "電工"

    def test_standard_cascade_delete(self, company_a):
        orderer = Orderer.unscoped.create(
            company=company_a, name="削除テスト", kind="national",
        )
        std = EstimationStandard.unscoped.create(
            company=company_a, orderer=orderer,
            name="テスト基準", fiscal_year=2026,
        )
        WorkRate.unscoped.create(
            company=company_a, standard=std,
            work_name="テスト作業", unit="m",
        )
        OverheadRule.unscoped.create(
            company=company_a, standard=std,
            category="temporary", work_type_label="電気設備",
            formula="rate = 0.1",
        )
        std.delete()
        assert WorkRate.unscoped.filter(company=company_a).count() == 0
        assert OverheadRule.unscoped.filter(company=company_a).count() == 0


@pytest.mark.django_db
class TestWorkRate:
    def test_ai_extracted_status(self, company_a):
        orderer = Orderer.unscoped.create(
            company=company_a, name="テスト", kind="national",
        )
        std = EstimationStandard.unscoped.create(
            company=company_a, orderer=orderer,
            name="テスト基準", fiscal_year=2026,
        )
        wr = WorkRate.unscoped.create(
            company=company_a, standard=std,
            work_name="AI抽出テスト", unit="箇所",
            extracted_by="ai", status="draft",
        )
        assert wr.extracted_by == "ai"
        assert wr.status == "draft"


class TestLaborImportParser:
    """労務単価インポートの都道府県マッチングテスト（DB不要）。"""

    def test_normalize_prefecture(self):
        from apps.estimation.services.labor_import import _normalize_prefecture

        assert _normalize_prefecture("神奈川県") == "神奈川県"
        assert _normalize_prefecture("神奈川") == "神奈川県"
        assert _normalize_prefecture("東京都") == "東京都"
        assert _normalize_prefecture("東京") == "東京都"
        assert _normalize_prefecture("北海道") == "北海道"
        assert _normalize_prefecture("") is None
        assert _normalize_prefecture("存在しない") is None
