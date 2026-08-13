"""入札案件管理アプリ — テナント分離テスト。"""

import datetime
from decimal import Decimal

import pytest

from apps.bids.forms import ScrapeTargetForm
from apps.bids.models import BidCost, BidProject, Qualification, ScrapeTarget
from apps.bids.scraper import _absolute_url, _map_cells_to_record, _normalize_header
from apps.core.tenant_context import set_current_company


@pytest.mark.django_db
class TestBidProjectIsolation:
    def test_project_isolation(self, company_a, company_b, user_a):
        set_current_company(company_a)
        BidProject.objects.create(
            title="案件A", company=company_a, created_by=user_a,
        )
        assert BidProject.objects.count() == 1

        set_current_company(company_b)
        assert BidProject.objects.count() == 0

        set_current_company(None)

    def test_project_budget_is_decimal(self, company_a, user_a):
        set_current_company(company_a)
        p = BidProject.objects.create(
            title="案件B",
            budget=Decimal("12345678"),
            company=company_a,
            created_by=user_a,
        )
        p.refresh_from_db()
        assert isinstance(p.budget, Decimal)
        assert p.budget == Decimal("12345678")

        set_current_company(None)

    def test_project_default_status(self, company_a, user_a):
        set_current_company(company_a)
        p = BidProject.objects.create(
            title="案件C", company=company_a, created_by=user_a,
        )
        assert p.status == BidProject.Status.NEW

        set_current_company(None)


@pytest.mark.django_db
class TestBidCostIsolation:
    def test_cost_isolation(self, company_a, company_b, user_a):
        set_current_company(company_a)
        project = BidProject.objects.create(
            title="案件A", company=company_a, created_by=user_a,
        )
        BidCost.objects.create(
            project=project,
            estimate_amount=Decimal("1000000"),
            actual_cost=Decimal("900000"),
            company=company_a,
            created_by=user_a,
        )
        assert BidCost.objects.count() == 1

        set_current_company(company_b)
        assert BidCost.objects.count() == 0

        set_current_company(None)

    def test_cost_cascade_delete(self, company_a, user_a):
        set_current_company(company_a)
        project = BidProject.objects.create(
            title="案件A", company=company_a, created_by=user_a,
        )
        BidCost.objects.create(
            project=project,
            estimate_amount=Decimal("500000"),
            company=company_a,
        )
        project.delete()
        assert BidCost.unscoped.count() == 0

        set_current_company(None)


@pytest.mark.django_db
class TestQualificationIsolation:
    def test_qualification_isolation(self, company_a, company_b, user_a):
        set_current_company(company_a)
        Qualification.objects.create(
            issuer="国土交通省",
            category="土木",
            grade="A",
            company=company_a,
            created_by=user_a,
        )
        assert Qualification.objects.count() == 1

        set_current_company(company_b)
        assert Qualification.objects.count() == 0

        set_current_company(None)

    def test_qualification_expiry_fields(self, company_a, user_a):
        set_current_company(company_a)
        q = Qualification.objects.create(
            issuer="東京都",
            valid_from=datetime.date(2025, 4, 1),
            valid_until=datetime.date(2027, 3, 31),
            company=company_a,
            created_by=user_a,
        )
        q.refresh_from_db()
        assert q.valid_from == datetime.date(2025, 4, 1)
        assert q.valid_until == datetime.date(2027, 3, 31)

        set_current_company(None)


@pytest.mark.django_db
class TestScrapeTargetIsolation:
    def test_scrape_target_isolation(self, company_a, company_b, user_a):
        set_current_company(company_a)
        ScrapeTarget.objects.create(
            name="関東の電気設備工事",
            koji_kbn="電気設備工事",
            company=company_a,
            created_by=user_a,
        )
        assert ScrapeTarget.objects.count() == 1

        set_current_company(company_b)
        assert ScrapeTarget.objects.count() == 0

        set_current_company(None)


class TestScrapeTargetChoices:
    """検索条件の選択肢は i-ppi.jp の表記と1文字も違ってはいけない。

    scraper が select_option(label=...) でそのまま渡すため、
    ずれると黙って条件が効かないまま検索される。
    """

    def test_region_matches_ippi_districts(self):
        values = [v for v, _ in ScrapeTarget.REGION_CHOICES]
        # i-ppi では九州と沖縄が1項目にまとまっている
        assert "九州・沖縄" in values
        assert "九州" not in values
        assert "沖縄" not in values

    def test_koji_kbn_and_gyosyu_are_separate_systems(self):
        kbn = [v for v, _ in ScrapeTarget.KOJI_KBN_CHOICES]
        gyosyu = [v for v, _ in ScrapeTarget.KOJI_GYOSYU_CHOICES]
        # 「電気」を含む選択肢は2つの体系に分かれている
        assert "電気設備工事" in kbn
        assert "電気設備工事" not in gyosyu
        assert "電気工事" in gyosyu
        assert "電気工事" not in kbn

    def test_form_rejects_value_outside_choices(self):
        form = ScrapeTargetForm(
            data={"name": "テスト", "koji_kbn": "電気", "days_back": 30}
        )
        assert not form.is_valid()
        assert "koji_kbn" in form.errors

    def test_form_accepts_real_labels(self):
        form = ScrapeTargetForm(
            data={
                "name": "テスト",
                "region": "関東",
                "koji_kbn": "電気設備工事",
                "koji_gyosyu": "電気工事",
                "days_back": 30,
                "scrape_interval_hours": 24,
            }
        )
        assert form.is_valid(), form.errors


class TestResultParsing:
    # 2026-08-11 に i-ppi の検索結果から実際に取得したヘッダー
    REAL_HEADERS = [
        "No",
        "発注機関／担当部・事務所",
        "工事名",
        "入札契約方式",
        "工事区分",
        "公告日",
    ]

    def test_normalize_header_strips_sort_marks(self):
        assert _normalize_header("発注機関／担当部・事務所\n△▽") == "発注機関／担当部・事務所"
        assert _normalize_header("公告日\n△▼") == "公告日"

    def test_maps_real_columns(self):
        cells = [
            "1",
            "国土交通省関東地方整備局 ／ 東京第二営繕事務所",
            "千葉労災特別介護施設（２６）電気設備改修その他工事",
            "一般競争入札",
            "電気設備工事",
            "2026/08/07",
        ]
        rec = _map_cells_to_record(self.REAL_HEADERS, cells, "")
        assert rec["title"] == "千葉労災特別介護施設（２６）電気設備改修その他工事"
        assert rec["client"] == "国土交通省関東地方整備局 ／ 東京第二営繕事務所"
        assert rec["category"] == "電気設備工事"

    def test_javascript_link_is_not_stored_as_url(self):
        # 一覧の案件リンクはポストバックで、行の位置しか持たない。
        # URL として保存すると実行のたびに別の案件が同じ値を持ち重複判定が壊れる。
        assert _absolute_url("javascript:__doPostBack('dgrSearchList','$0')") == ""
        assert _absolute_url("") == ""
        assert _absolute_url(None) == ""

    def test_relative_link_becomes_absolute(self):
        assert _absolute_url("/IPPI/Detail.aspx?id=1") == (
            "https://www.i-ppi.jp/IPPI/Detail.aspx?id=1"
        )
        assert _absolute_url("https://example.com/x") == "https://example.com/x"
