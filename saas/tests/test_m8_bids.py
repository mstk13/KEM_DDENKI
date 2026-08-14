"""入札案件管理アプリ — テナント分離テスト。"""

import datetime
from decimal import Decimal

import pytest

from apps.bids.forms import ScrapeTargetForm
from apps.bids.models import (
    BidCost,
    BidProject,
    Qualification,
    ScrapeTarget,
    is_excluded_category,
)
from apps.bids.qualification import (
    category_candidates,
    check_qualifications_for_projects,
    normalize_category,
    normalize_grade,
    normalize_issuer,
)
from apps.bids.scraper import (
    _absolute_url,
    _clean_location,
    _extract_prefecture,
    _map_cells_to_record,
    _normalize_header,
)
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
        # 1カラムに入っている発注機関と担当部は分けて持つ
        assert rec["client"] == "国土交通省関東地方整備局"
        assert rec["agency_dept"] == "東京第二営繕事務所"
        assert rec["category"] == "電気設備工事"
        assert rec["bid_method"] == "一般競争入札"
        assert rec["announced_on"] == "2026-08-07"

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

    def test_location_drops_empty_destination(self):
        # 1地点しかない案件でも「至：」の行が付いてくる
        assert _clean_location("自：京都府京都市下京区 至：") == "京都府京都市下京区"
        assert _clean_location(
            "自：長野県飯田市南信濃八重河内から静岡県浜松市天竜区水窪町 至："
        ) == "長野県飯田市南信濃八重河内から静岡県浜松市天竜区水窪町"
        assert _clean_location("自：東京都千代田区 至：東京都港区") == (
            "自：東京都千代田区 至：東京都港区"
        )
        assert _clean_location("") == ""

    def test_prefecture_is_taken_from_first_occurrence(self):
        # 実物は「自：長野県長野県飯田市…から静岡県浜松市…」のように
        # 都道府県が重複したり複数県にまたがったりする
        assert _extract_prefecture(
            "自：長野県長野県飯田市南信濃八重河内から静岡県浜松市天竜区水窪町 至："
        ) == "長野県"
        assert _extract_prefecture("自：東京都千代田区霞が関１－１－１") == "東京都"
        assert _extract_prefecture("") == ""


class TestExcludedCategories:
    """土木・舗装系は取得対象外。ただし電気設備・機械設備を含むものは残す。

    i-ppi の工事区分は発注機関ごとの自由記述で、
    「建築一式工事（電気設備工事、機械設備工事含む。）」のように
    1つの文字列に複数種別が入る。完全一致では判定できない。
    """

    def test_excludes_civil_and_pavement(self):
        assert is_excluded_category("一般土木工事")
        assert is_excluded_category("アスファルト舗装工事")
        assert is_excluded_category("セメント・コンクリート舗装工事")
        assert is_excluded_category("建築工事及び土木工事")

    def test_keeps_building_work_that_includes_our_trades(self):
        # 2026-08-14 に i-ppi の実データで確認した表記
        assert not is_excluded_category("建築一式工事（電気設備工事、機械設備工事含む。）")

    def test_keeps_our_own_trades(self):
        assert not is_excluded_category("電気設備工事")
        assert not is_excluded_category("建築工事")
        assert not is_excluded_category("")

    def test_choices_and_import_filter_agree(self):
        # 選べるのに1件も保存されない条件を作らない
        for value, _ in ScrapeTarget.KOJI_KBN_CHOICES:
            assert not is_excluded_category(value), value
        for value, _ in ScrapeTarget.KOJI_GYOSYU_CHOICES:
            assert not is_excluded_category(value), value

    def test_excluded_values_are_not_selectable(self):
        kbn = [v for v, _ in ScrapeTarget.KOJI_KBN_CHOICES]
        for value in ("一般土木工事", "アスファルト舗装工事", "セメント・コンクリート舗装工事"):
            assert value in ScrapeTarget.KOJI_KBN_ALL  # i-ppi 側には存在する
            assert value not in kbn


@pytest.mark.django_db
class TestScrapeImport:
    """取り込みは案件概要を保存し、対象外の工事種別を捨てる。"""

    def _target(self, company_a, user_a):
        return ScrapeTarget.unscoped.create(
            company=company_a, created_by=user_a,
            name="i-ppi", site_key="ippi", days_back=30,
        )

    def _run(self, monkeypatch, records, target, company_a):
        from apps.bids import scraper, services

        monkeypatch.setattr(scraper, "scrape_ippi", lambda t: records)
        return services.run_scrape(target, company_a)

    def test_detail_fields_are_saved(self, monkeypatch, company_a, user_a):
        target = self._target(company_a, user_a)
        record = {
            "title": "令和８年度　三遠南信青崩峠トンネル照明設備工事",
            "client": "国土交通省中部地方整備局",
            "agency_dept": "飯田国道事務所",
            "region": "長野県",
            "location": "自：長野県飯田市南信濃八重河内から静岡県浜松市天竜区水窪町",
            "category": "電気設備工事",
            "bid_method": "一般競争入札（同時提出型）",
            "design_no": "2026857140010004",
            "electronic_bid": "対象",
            "announced_on": "2026-08-05",
            "deadline": "2026-08-24",
            "opening_on": "2026-10-07",
            "budget": 0,
            "source_url": "https://www.moj.go.jp/shisetsu/keiri/shisetsu01_00695.html",
            "summary": "発注機関\t国土交通省中部地方整備局",
        }
        result = self._run(monkeypatch, [record], target, company_a)

        assert result["new"] == 1
        project = BidProject.unscoped.get(company=company_a)
        assert project.client == "国土交通省中部地方整備局"
        assert project.agency_dept == "飯田国道事務所"
        assert project.location.startswith("自：長野県飯田市")
        assert project.bid_method == "一般競争入札（同時提出型）"
        assert project.design_no == "2026857140010004"
        assert project.electronic_bid == "対象"
        assert project.announced_on == datetime.date(2026, 8, 5)
        assert project.deadline == datetime.date(2026, 8, 24)
        assert project.opening_on == datetime.date(2026, 10, 7)
        assert project.source_url.endswith("shisetsu01_00695.html")
        assert project.summary

    def test_excluded_category_is_not_imported(self, monkeypatch, company_a, user_a):
        target = self._target(company_a, user_a)
        keep = "建築一式工事（電気設備工事、機械設備工事含む。）"
        records = [
            {"title": "県道舗装工事", "category": "アスファルト舗装工事"},
            {"title": "庁舎改修工事", "category": keep},
        ]
        result = self._run(monkeypatch, records, target, company_a)

        assert result["new"] == 1
        assert result["excluded"] == 1
        titles = list(
            BidProject.unscoped.filter(company=company_a).values_list("title", flat=True)
        )
        assert titles == ["庁舎改修工事"]
        target.refresh_from_db()
        assert "対象外1件" in target.last_result

    def test_existing_project_is_filled_in_not_skipped(
        self, monkeypatch, company_a, user_a,
    ):
        """取得項目を増やしたとき、取り込み済みの案件も後から埋まる。

        重複でスキップし続けると、既存案件は永久に空のままになる。
        """
        # 旧コードで取り込んだ案件（発注機関と担当部が1カラムに入っている）
        old = BidProject.unscoped.create(
            company=company_a, created_by=user_a,
            title="Ｒ８下京税務署電気設備工事",
            client="国土交通省近畿地方整備局 ／ 営繕部",
            category="電気設備工事",
            status=BidProject.Status.CONSIDERING,
        )
        target = self._target(company_a, user_a)
        record = {
            "title": "Ｒ８下京税務署電気設備工事",
            "client": "国土交通省近畿地方整備局",
            "agency_dept": "営繕部",
            "location": "京都府京都市下京区",
            "category": "電気設備工事",
            "bid_method": "一般競争入札（標準型）",
            "announced_on": "2026-08-04",
            "opening_on": "2026-10-28",
            "source_url": "https://example.go.jp/kokoku/1",
            "summary": "発注機関\t国土交通省近畿地方整備局",
        }
        result = self._run(monkeypatch, [record], target, company_a)

        assert result["new"] == 0
        assert result["updated"] == 1
        assert BidProject.unscoped.filter(company=company_a).count() == 1

        old.refresh_from_db()
        assert old.client == "国土交通省近畿地方整備局"
        assert old.agency_dept == "営繕部"
        assert old.location == "京都府京都市下京区"
        assert old.announced_on == datetime.date(2026, 8, 4)
        assert old.opening_on == datetime.date(2026, 10, 28)
        assert old.source_url == "https://example.go.jp/kokoku/1"
        # 画面で動かした状態は保持する
        assert old.status == BidProject.Status.CONSIDERING

    def test_edited_values_are_not_overwritten(self, monkeypatch, company_a, user_a):
        existing = BidProject.unscoped.create(
            company=company_a, created_by=user_a,
            title="Ｒ８下京税務署電気設備工事",
            client="国土交通省近畿地方整備局",
            location="現地確認済み：京都市下京区○○町",
            deadline=datetime.date(2026, 8, 20),
        )
        target = self._target(company_a, user_a)
        record = {
            "title": "Ｒ８下京税務署電気設備工事",
            "client": "国土交通省近畿地方整備局",
            "location": "京都府京都市下京区",
            "deadline": "2026-08-31",
            "bid_method": "一般競争入札（標準型）",
        }
        self._run(monkeypatch, [record], target, company_a)

        existing.refresh_from_db()
        assert existing.location == "現地確認済み：京都市下京区○○町"
        assert existing.deadline == datetime.date(2026, 8, 20)
        # 空いていた項目は埋まる
        assert existing.bid_method == "一般競争入札（標準型）"

    def test_nothing_to_fill_counts_as_skipped(self, monkeypatch, company_a, user_a):
        BidProject.unscoped.create(
            company=company_a, created_by=user_a,
            title="Ｒ８下京税務署電気設備工事",
            client="国土交通省近畿地方整備局",
            category="電気設備工事",
        )
        target = self._target(company_a, user_a)
        record = {
            "title": "Ｒ８下京税務署電気設備工事",
            "client": "国土交通省近畿地方整備局",
            "category": "電気設備工事",
        }
        result = self._run(monkeypatch, [record], target, company_a)

        assert result == {
            "new": 0, "updated": 0, "skipped": 1, "excluded": 0, "errors": [],
        }


class TestQualificationMatching:
    """発注機関・業種区分の表記ゆれを吸収して判定する。

    表記は 2026-08-14 に資格マスタ（96件）と i-ppi の実データで確認したもの。
    """

    def test_issuer_normalization_absorbs_parentheses(self):
        # 資格側「国土交通省(関東地方整備局)」／案件側「国土交通省関東地方整備局」
        assert normalize_issuer("国土交通省(関東地方整備局)") == "国土交通省関東地方整備局"
        assert normalize_issuer("内閣府(沖縄総合事務局)") == "内閣府沖縄総合事務局"

    def test_grade_normalization(self):
        assert normalize_grade("Ｄ") == "D"
        assert normalize_grade("b") == "B"
        # 等級欄に「○」だけが入っている行がある
        assert normalize_grade("○") == ""
        assert normalize_grade("") == ""

    def test_electric_categories_are_grouped(self):
        for category in ("電気設備工事", "電気工事", "電気"):
            assert "電気設備" in category_candidates(category)

    def test_telecom_is_not_confused_with_electric(self):
        # 「電気通信」は電気工事の資格では代替できない
        assert category_candidates("通信設備工事") == ("電気通信", "通信設備")
        assert "電気工事" not in category_candidates("通信設備工事")

    def test_category_normalization_drops_trailing_koji(self):
        # 「電気工事」「電気設備」「電気」は同じもの。「電気通信」は別物。
        assert normalize_category("電気工事") == "電気"
        assert normalize_category("電気設備工事") == "電気設備"
        assert normalize_category("電気通信") == "電気通信"
        # 部分一致にすると「電気」が「電気通信」に含まれて誤判定になる
        assert normalize_category("電気") != normalize_category("電気通信")

    def test_combined_category_matches_our_trade(self):
        candidates = category_candidates("建築一式工事（電気設備工事、機械設備工事含む。）")
        assert "電気設備" in candidates


@pytest.mark.django_db
class TestQualificationCheck:
    def _qual(self, company_a, user_a, **kwargs):
        defaults = {
            "issuer": "国土交通省(関東地方整備局)",
            "category": "電気設備",
            "grade": "B",
            "keisin_score": 871,
            "total_score": 2054,
            "valid_until": datetime.date(2027, 3, 31),
        }
        defaults.update(kwargs)
        return Qualification.unscoped.create(
            company=company_a, created_by=user_a, **defaults,
        )

    def _project(self, company_a, user_a, **kwargs):
        defaults = {
            "title": "Ｒ７武蔵高圧ケーブル改修工事",
            "client": "国土交通省関東地方整備局",
            "category": "電気設備工事",
        }
        defaults.update(kwargs)
        return BidProject.unscoped.create(
            company=company_a, created_by=user_a, **defaults,
        )

    def _check(self, project, company_a):
        return check_qualifications_for_projects([project], company_a)[project.pk]

    def test_matches_across_notation_difference(self, company_a, user_a):
        qual = self._qual(company_a, user_a)
        check = self._check(self._project(company_a, user_a), company_a)
        assert check["eligible"] is True
        assert check["matched"] == qual
        assert "B等級" in check["reason"]
        assert "総合点2054" in check["reason"]

    def test_ministry_qualification_covers_regional_bureau(self, company_a, user_a):
        # 案件は「防衛省北関東防衛局」、資格は「防衛省」だけ
        self._qual(company_a, user_a, issuer="防衛省", category="電気工事", grade="A")
        project = self._project(
            company_a, user_a, client="防衛省北関東防衛局", category="電気設備工事",
        )
        assert self._check(project, company_a)["eligible"] is True

    def test_regional_qualification_wins_over_ministry(self, company_a, user_a):
        self._qual(company_a, user_a, issuer="国土交通省", category="電気工事", grade="A")
        regional = self._qual(company_a, user_a)  # 関東地方整備局／電気設備／B
        check = self._check(self._project(company_a, user_a), company_a)
        assert check["matched"] == regional

    def test_wrong_trade_is_not_eligible(self, company_a, user_a):
        self._qual(company_a, user_a, category="橋梁補修", grade="")
        check = self._check(self._project(company_a, user_a), company_a)
        assert check["eligible"] is False
        assert "業種区分" in check["reason"]

    def test_telecom_qualification_does_not_cover_electric_work(
        self, company_a, user_a,
    ):
        self._qual(company_a, user_a, category="電気通信", grade="C")
        check = self._check(self._project(company_a, user_a), company_a)
        assert check["eligible"] is False

    def test_expired_qualification_is_reported(self, company_a, user_a):
        self._qual(company_a, user_a, valid_until=datetime.date(2026, 3, 31))
        check = self._check(self._project(company_a, user_a), company_a)
        assert check["eligible"] is False
        assert "有効期限" in check["reason"]

    def test_unknown_issuer_is_not_judged(self, company_a, user_a):
        self._qual(company_a, user_a)
        project = self._project(company_a, user_a, client="横浜市")
        check = self._check(project, company_a)
        assert check["eligible"] is None
        assert check["issuer_known"] is False

    def test_grade_requirement_below_ours(self, company_a, user_a):
        self._qual(company_a, user_a, grade="C")
        project = self._project(company_a, user_a, required_grade="A")
        check = self._check(project, company_a)
        assert check["eligible"] is False
        assert "A等級以上が必要" in check["reason"]

    def test_grade_requirement_met(self, company_a, user_a):
        self._qual(company_a, user_a, grade="A")
        project = self._project(company_a, user_a, required_grade="B")
        assert self._check(project, company_a)["eligible"] is True

    def test_unified_qualification_is_not_an_issuer(self, company_a, user_a):
        # 全省庁統一資格は物品・役務の資格。工事の発注機関としては使わない
        self._qual(
            company_a, user_a, issuer="全省庁統一資格", category="役務の提供等", grade="C",
        )
        project = self._project(company_a, user_a, client="全省庁統一資格")
        assert self._check(project, company_a)["eligible"] is None

    def test_isolation_across_companies(self, company_a, company_b, user_a, user_b):
        self._qual(company_a, user_a)
        project_b = BidProject.unscoped.create(
            company=company_b, created_by=user_b,
            title="他社の案件", client="国土交通省関東地方整備局",
            category="電気設備工事",
        )
        check = check_qualifications_for_projects([project_b], company_b)[project_b.pk]
        assert check["eligible"] is None


@pytest.mark.django_db
class TestProjectDetailView:
    def test_detail_shows_case_information(self, client, company_a, user_a):
        project = BidProject.unscoped.create(
            company=company_a, created_by=user_a,
            title="Ｒ８下京税務署電気設備工事",
            client="国土交通省近畿地方整備局",
            agency_dept="営繕部",
            location="自：京都府京都市下京区",
            category="電気設備工事",
            bid_method="一般競争入札（標準型）",
            electronic_bid="対象",
            announced_on=datetime.date(2026, 8, 4),
            opening_on=datetime.date(2026, 9, 10),
            source_url="https://example.go.jp/kokoku/1",
        )
        client.force_login(user_a)
        html = client.get(f"/bids/{project.pk}/").content.decode()

        assert "国土交通省近畿地方整備局" in html
        assert "営繕部" in html
        assert "京都市下京区" in html
        assert "一般競争入札（標準型）" in html
        assert "https://example.go.jp/kokoku/1" in html

    def test_detail_shows_qualification_verdict(self, client, company_a, user_a):
        Qualification.unscoped.create(
            company=company_a, created_by=user_a,
            issuer="国土交通省(近畿地方整備局)", category="電気設備", grade="B",
            keisin_score=871, total_score=1957,
            valid_until=datetime.date(2027, 3, 31),
        )
        project = BidProject.unscoped.create(
            company=company_a, created_by=user_a,
            title="Ｒ８下京税務署電気設備工事",
            client="国土交通省近畿地方整備局",
            category="電気設備工事",
            work_outline="受変電設備一式の更新。工期は令和9年3月まで。",
            requirements="同種工事の施工実績があること。監理技術者を専任で配置すること。",
        )
        client.force_login(user_a)
        html = client.get(f"/bids/{project.pk}/").content.decode()

        assert "参加可能" in html
        assert "国土交通省(近畿地方整備局)" in html
        assert "1957" in html
        assert "受変電設備一式の更新" in html
        assert "監理技術者を専任で配置" in html

    def test_list_shows_qualification_badge(self, client, company_a, user_a):
        Qualification.unscoped.create(
            company=company_a, created_by=user_a,
            issuer="防衛省", category="電気工事", grade="A",
            valid_until=datetime.date(2027, 3, 31),
        )
        BidProject.unscoped.create(
            company=company_a, created_by=user_a,
            title="入間（８）厚生棟改修電気工事",
            client="防衛省北関東防衛局", category="電気設備工事",
        )
        client.force_login(user_a)
        html = client.get("/bids/").content.decode()
        assert "参加可" in html

    def test_edit_form_keeps_scraped_fields(self, client, company_a, user_a):
        """編集画面に出ていない項目は保存時に空になる。全項目を描画しておく。"""
        project = BidProject.unscoped.create(
            company=company_a, created_by=user_a,
            title="Ｒ８下京税務署電気設備工事",
            client="国土交通省近畿地方整備局",
            agency_dept="営繕部",
            location="自：京都府京都市下京区",
            category="電気設備工事",
            bid_method="一般競争入札（標準型）",
            design_no="2026857140010004",
            electronic_bid="対象",
            announced_on=datetime.date(2026, 8, 4),
            opening_on=datetime.date(2026, 9, 10),
        )
        client.force_login(user_a)
        url = f"/bids/{project.pk}/edit/"
        response = client.get(url)
        html = response.content.decode()
        form = response.context["form"]

        # 描画されていない項目は POST に乗らず、保存時に空で上書きされる
        for name in form.fields:
            assert f'name="{name}"' in html, name

        # 画面に出ている値をそのまま返す（実際の編集操作と同じ）
        data = {k: (v if v is not None else "") for k, v in form.initial.items()}
        data["title"] = "Ｒ８下京税務署電気設備工事（変更）"
        data["cost-estimate_amount"] = 0
        data["cost-actual_cost"] = 0

        response = client.post(url, data)
        assert response.status_code == 302

        project.refresh_from_db()
        assert project.title == "Ｒ８下京税務署電気設備工事（変更）"
        assert project.agency_dept == "営繕部"
        assert project.location == "自：京都府京都市下京区"
        assert project.bid_method == "一般競争入札（標準型）"
        assert project.design_no == "2026857140010004"
        assert project.electronic_bid == "対象"
        assert project.announced_on == datetime.date(2026, 8, 4)
        assert project.opening_on == datetime.date(2026, 9, 10)
