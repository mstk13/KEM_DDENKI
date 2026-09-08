"""資格を満たす案件だけ取り込む: 公告の資格要件の抽出・統一資格の判定・取り込み時の見送り。"""

import datetime

import pytest

from apps.bids.announcement import (
    extract_mod_works_categories,
    extract_sections,
    extract_unified_requirement,
)
from apps.bids.models import BidProject, Qualification, ScrapeTarget
from apps.bids.qualification import check_project

UNIFIED_GOODS = (
    "８ 競争参加資格\n"
    "（3） 令和０７・０８・０９年度の防衛省競争参加資格（全省庁統一資格）「物品の販売」のＤ等\n"
    "級以上の競争参加資格を有する者、又は当該競争参加資格を有していない者にあっては、"
)
UNIFIED_SERVICE = (
    "８ 競争参加資格\n"
    "（3） 令和０７・０８・０９年度の防衛省競争参加資格（全省庁統一資格）"
    "「役務の提供等」のＤ等級\n以上の競争参加資格を有する者"
)
UNIFIED_BUYBACK = (
    "７ 競争参加資格\n"
    "（３）令和０７・０８・０９年度の防衛省競争参加資格（全省庁統一資格）「物品の買受け」のＣ等級以上の競\n"
    "争参加資格を有する者"
)
UNIFIED_LISTED = (
    "（3）令和０７・０８・０９年度の防衛省競争参加資格（全省庁統一資格）「役務の提供等」の"
    "Ｂ，Ｃ又はＤ等級の競争参加資格を有する者、又は当該競争参加資格を有していない者にあっては"
)
MOD_WORKS = (
    "２ 競争参加資格\n"
    "(2) 防衛省における令和７・８年度一般競争（指名競争）参加資格（以下「防衛省競争\n"
    "参加資格」という。）のうち、「建築一式工事」又は「管工事」で級別の格付けを受\n"
    "け、南関東防衛局に競争参加を希望していること\n"
    "(4) 防衛省競争参加資格の「建築一式工事」又は「管工事」に係る等級（資格審査結果\n"
    "通知書の記３の等級・総合審査数値欄の等級）がＣ・Ｄ等級以上であること。"
)


class TestExtractRequirement:
    def test_unified_goods_with_line_break_in_grade(self):
        assert extract_unified_requirement(UNIFIED_GOODS) == {
            "kind": "物品の販売", "grade": "D", "grades": "",
        }

    def test_unified_service_and_buyback(self):
        assert extract_unified_requirement(UNIFIED_SERVICE) == {
            "kind": "役務の提供等", "grade": "D", "grades": "",
        }
        assert extract_unified_requirement(UNIFIED_BUYBACK) == {
            "kind": "物品の買受け", "grade": "C", "grades": "",
        }

    def test_unified_listed_grades(self):
        """「Ｂ，Ｃ又はＤ等級」は下限ではなく列挙として読む。"""
        assert extract_unified_requirement(UNIFIED_LISTED) == {
            "kind": "役務の提供等", "grade": "", "grades": "BCD",
        }
        sections = extract_sections(UNIFIED_LISTED)
        assert sections["required_grade"] == ""
        assert sections["required_grades"] == "BCD"

    def test_mod_works_lists_categories(self):
        assert extract_mod_works_categories(MOD_WORKS) == ["建築一式工事", "管工事"]
        assert extract_mod_works_categories(UNIFIED_GOODS) == []

    def test_sections_carry_issuer_type_and_category(self):
        goods = extract_sections(UNIFIED_GOODS)
        assert goods["required_issuer_type"] == "全省庁統一資格"
        assert goods["required_category"] == "物品の販売"
        assert goods["required_grade"] == "D"

        works = extract_sections(MOD_WORKS)
        assert works["required_issuer_type"] == "防衛省"
        assert works["required_category"] == "建築一式工事／管工事"
        assert works["required_grade"] == "D"
        # 「Ｃ・Ｄ等級以上」は下限。列挙として二重に持たない
        assert works["required_grades"] == ""


def _unified(company, kind, grade, valid_until=datetime.date(2028, 3, 31)):
    return Qualification.unscoped.create(
        company=company, issuer="全省庁統一資格", category=kind, grade=grade,
        total_score=62, valid_until=valid_until,
    )


def _project(company, **kw):
    base = {
        "title": "テスト案件", "client": "海上自衛隊 横須賀基地", "category": "物品・役務",
    }
    base.update(kw)
    return BidProject(company=company, **base)


@pytest.mark.django_db
class TestUnifiedQualificationCheck:
    def test_goods_grade_c_meets_floor_d(self, company_a):
        quals = [_unified(company_a, "物品の販売", "C")]
        project = _project(
            company_a, required_issuer_type="全省庁統一資格",
            required_category="物品の販売", required_grade="D",
        )
        verdict = check_project(project, quals)
        assert verdict["eligible"] is True
        assert "D等級以上 → 自社 C 等級" in verdict["reason"]

    def test_grade_below_floor_is_ineligible(self, company_a):
        quals = [_unified(company_a, "物品の販売", "D")]
        project = _project(
            company_a, required_issuer_type="全省庁統一資格",
            required_category="物品の販売", required_grade="C",
        )
        assert check_project(project, quals)["eligible"] is False

    def test_listed_grades_membership(self, company_a):
        quals = [_unified(company_a, "役務の提供等", "C")]
        listed = _project(
            company_a, required_issuer_type="全省庁統一資格",
            required_category="役務の提供等", required_grades="BCD",
        )
        verdict = check_project(listed, quals)
        assert verdict["eligible"] is True
        assert "B等級・C等級・D等級 → 自社 C 等級" in verdict["reason"]

        only_ab = _project(
            company_a, required_issuer_type="全省庁統一資格",
            required_category="役務の提供等", required_grades="AB",
        )
        assert check_project(only_ab, quals)["eligible"] is False

    def test_missing_kind_is_ineligible(self, company_a):
        quals = [_unified(company_a, "物品の販売", "C")]
        project = _project(
            company_a, required_issuer_type="全省庁統一資格",
            required_category="役務の提供等", required_grade="D",
        )
        verdict = check_project(project, quals)
        assert verdict["eligible"] is False
        assert "役務の提供等" in verdict["reason"]

    def test_expired_is_ineligible(self, company_a):
        quals = [_unified(company_a, "物品の販売", "C", valid_until=datetime.date(2020, 3, 31))]
        project = _project(
            company_a, required_issuer_type="全省庁統一資格",
            required_category="物品の販売", required_grade="D",
        )
        assert check_project(project, quals)["eligible"] is False

    def test_mod_works_uses_issuer_from_announcement(self, company_a):
        """案件側の発注機関は「海上自衛隊 横須賀基地」でも、公告が防衛省の資格を求めるなら
        防衛省の工事資格で判定する。電気工事しか無ければ建築・管工事は参加できない。"""
        quals = [
            Qualification.unscoped.create(
                company=company_a, issuer="防衛省", category="電気工事", grade="A",
                valid_until=datetime.date(2027, 3, 31),
            ),
        ]
        project = _project(
            company_a, required_issuer_type="防衛省",
            required_category="建築一式工事／管工事", required_grade="D",
        )
        assert check_project(project, quals)["eligible"] is False

        electric = _project(
            company_a, required_issuer_type="防衛省",
            required_category="電気工事", required_grade="D",
        )
        assert check_project(electric, quals)["eligible"] is True


@pytest.mark.django_db
class TestOnlyEligibleScrape:
    def _target(self, company_a, user_a, only_eligible=True):
        return ScrapeTarget.unscoped.create(
            company=company_a, created_by=user_a, name="海自 横須賀基地",
            site_key="msdf_yokosuka", region="神奈川県", only_eligible=only_eligible,
        )

    def _run(self, monkeypatch, records, announcements, target, company_a):
        from apps.bids import announcement, services
        from apps.bids.scrapers import mod_base

        monkeypatch.setattr(mod_base, "scrape_mod_base", lambda t: records)

        def fake_extract(url):
            base = {
                "work_outline": "", "requirements": "", "required_grade": "",
                "required_grades": "", "required_score": None,
                "required_issuer_type": "", "required_category": "",
                "headings": [], "garbled": False,
            }
            base.update(announcements.get(url, {}))
            return base

        monkeypatch.setattr(announcement, "extract_from_url", fake_extract)
        return services.run_scrape(target, company_a)

    def _records(self):
        return [
            {"title": "トナーカートリッジ以下内訳", "client": "海上自衛隊 横須賀基地",
             "category": "物品・役務", "source_url": "https://x/goods.pdf"},
            {"title": "音響設備修繕／横須賀地方総監部", "client": "海上自衛隊 横須賀基地",
             "category": "物品・役務", "source_url": "https://x/service.pdf"},
            {"title": "隊舎空調設備更新（工事）", "client": "海上自衛隊 横須賀基地",
             "category": "物品・役務", "source_url": "https://x/works.pdf"},
            {"title": "読めない公告", "client": "海上自衛隊 横須賀基地",
             "category": "物品・役務", "source_url": "https://x/garbled.pdf"},
        ]

    def _announcements(self):
        return {
            "https://x/goods.pdf": {
                "required_issuer_type": "全省庁統一資格",
                "required_category": "物品の販売", "required_grade": "D",
            },
            "https://x/service.pdf": {
                "required_issuer_type": "全省庁統一資格",
                "required_category": "役務の提供等", "required_grade": "D",
            },
            "https://x/works.pdf": {
                "required_issuer_type": "防衛省",
                "required_category": "建築一式工事／管工事", "required_grade": "D",
            },
            "https://x/garbled.pdf": {"garbled": True},
        }

    def test_registers_only_eligible(self, monkeypatch, company_a, user_a):
        _unified(company_a, "物品の販売", "C")
        Qualification.unscoped.create(
            company=company_a, issuer="防衛省", category="電気工事", grade="A",
            valid_until=datetime.date(2027, 3, 31),
        )
        target = self._target(company_a, user_a)
        result = self._run(
            monkeypatch, self._records(), self._announcements(), target, company_a,
        )
        assert result["new"] == 1
        assert result["ineligible"] == 2  # 役務（資格なし）・工事（建築/管）
        assert result["unknown"] == 1  # 読めない公告
        titles = list(
            BidProject.unscoped.filter(company=company_a).values_list("title", flat=True)
        )
        assert titles == ["トナーカートリッジ以下内訳"]

        project = BidProject.unscoped.get(company=company_a)
        assert project.required_issuer_type == "全省庁統一資格"
        assert project.required_category == "物品の販売"
        assert project.required_grade == "D"
        # 「物品・役務」の大枠は公告の種類で置き換わる
        assert project.category == "物品の販売"

        target.refresh_from_db()
        assert "資格不足2件" in target.last_result
        assert "判定不能1件" in target.last_result

    def test_without_option_registers_everything(self, monkeypatch, company_a, user_a):
        target = self._target(company_a, user_a, only_eligible=False)
        result = self._run(
            monkeypatch, self._records(), self._announcements(), target, company_a,
        )
        assert result["new"] == 4
        assert result["ineligible"] == 0
        assert result["unknown"] == 0


@pytest.mark.django_db
class TestSkippedBidRecording:
    """見送った案件は理由付きで残り、画面から確認できる。"""

    def _setup(self, company_a, user_a):
        _unified(company_a, "物品の販売", "C")
        Qualification.unscoped.create(
            company=company_a, issuer="防衛省", category="電気工事", grade="A",
            valid_until=datetime.date(2027, 3, 31),
        )
        return TestOnlyEligibleScrape()._target(company_a, user_a)

    def test_records_reason_for_ineligible_and_unknown(self, monkeypatch, company_a, user_a):
        from apps.bids.models import SkippedBid

        helper = TestOnlyEligibleScrape()
        target = self._setup(company_a, user_a)
        helper._run(monkeypatch, helper._records(), helper._announcements(), target, company_a)

        skipped = {s.title: s for s in SkippedBid.unscoped.filter(company=company_a)}
        assert set(skipped) == {
            "音響設備修繕／横須賀地方総監部", "隊舎空調設備更新（工事）", "読めない公告",
        }

        service = skipped["音響設備修繕／横須賀地方総監部"]
        assert service.verdict == SkippedBid.Verdict.INELIGIBLE
        assert "役務の提供等" in service.reason
        assert service.required_issuer_type == "全省庁統一資格"
        assert service.target == target

        works = skipped["隊舎空調設備更新（工事）"]
        assert works.verdict == SkippedBid.Verdict.INELIGIBLE
        assert "建築一式工事／管工事" in works.reason

        unknown = skipped["読めない公告"]
        assert unknown.verdict == SkippedBid.Verdict.UNKNOWN
        assert "判定できません" in unknown.reason

    def test_record_is_removed_once_eligible(self, monkeypatch, company_a, user_a):
        """資格を追加して次の取り込みで通ったら、見送りの記録は消える。"""
        from apps.bids.models import SkippedBid

        helper = TestOnlyEligibleScrape()
        target = self._setup(company_a, user_a)
        helper._run(monkeypatch, helper._records(), helper._announcements(), target, company_a)
        assert SkippedBid.unscoped.filter(
            company=company_a, title="音響設備修繕／横須賀地方総監部",
        ).exists()

        _unified(company_a, "役務の提供等", "C")
        result = helper._run(
            monkeypatch, helper._records(), helper._announcements(), target, company_a,
        )
        assert result["new"] == 1
        assert not SkippedBid.unscoped.filter(
            company=company_a, title="音響設備修繕／横須賀地方総監部",
        ).exists()

    def test_list_page_shows_reason(self, monkeypatch, client, company_a, user_a):
        helper = TestOnlyEligibleScrape()
        target = self._setup(company_a, user_a)
        helper._run(monkeypatch, helper._records(), helper._announcements(), target, company_a)

        client.force_login(user_a)
        response = client.get("/bids/skipped/")
        assert response.status_code == 200
        html = response.content.decode()
        assert "隊舎空調設備更新（工事）" in html
        assert "建築一式工事／管工事" in html
        assert 'data-reason-toggle="' in html

        response = client.get("/bids/skipped/?verdict=unknown")
        html = response.content.decode()
        assert "読めない公告" in html
        assert "隊舎空調設備更新（工事）" not in html

    def test_other_tenant_cannot_see_or_delete(
        self, monkeypatch, client, company_a, user_a, user_b,
    ):
        from apps.bids.models import SkippedBid

        helper = TestOnlyEligibleScrape()
        target = self._setup(company_a, user_a)
        helper._run(monkeypatch, helper._records(), helper._announcements(), target, company_a)
        obj = SkippedBid.unscoped.filter(company=company_a).first()

        client.force_login(user_b)
        assert "隊舎空調設備更新" not in client.get("/bids/skipped/").content.decode()
        assert client.post(f"/bids/skipped/{obj.pk}/delete/").status_code == 404
        assert SkippedBid.unscoped.filter(pk=obj.pk).exists()


@pytest.mark.django_db
class TestRelatedQualifications:
    """見送り案件の画面で、公告が求める資格の隣に並べる自社資格。"""

    def test_unified_lists_all_kinds_and_marks_required(self, company_a):
        from apps.bids.qualification import related_qualifications

        quals = [_unified(company_a, "物品の販売", "C"), _unified(company_a, "役務の提供等", "C")]
        ours = related_qualifications("全省庁統一資格", "物品の製造", quals)
        assert ours["issuer_label"] == "全省庁統一資格"
        assert [r["qual"].category for r in ours["rows"]] == ["役務の提供等", "物品の販売"]
        assert not any(r["hit"] for r in ours["rows"])

        ours = related_qualifications("全省庁統一資格", "物品の販売", quals)
        assert ours["rows"][0]["qual"].category == "物品の販売"
        assert ours["rows"][0]["hit"] is True

    def test_mod_lists_issuer_qualifications(self, company_a):
        from apps.bids.qualification import related_qualifications

        quals = [
            Qualification.unscoped.create(
                company=company_a, issuer="防衛省", category="電気工事", grade="A",
            ),
            Qualification.unscoped.create(
                company=company_a, issuer="国土交通省", category="電気工事", grade="A",
            ),
            _unified(company_a, "物品の販売", "C"),
        ]
        ours = related_qualifications("防衛省", "建築一式工事／管工事", quals)
        assert [r["qual"].issuer for r in ours["rows"]] == ["防衛省"]
        assert ours["rows"][0]["hit"] is False

        ours = related_qualifications("防衛省", "電気工事", quals)
        assert ours["rows"][0]["hit"] is True

    def test_page_shows_our_qualifications(self, monkeypatch, client, company_a, user_a):
        helper = TestOnlyEligibleScrape()
        target = TestSkippedBidRecording()._setup(company_a, user_a)
        helper._run(monkeypatch, helper._records(), helper._announcements(), target, company_a)

        client.force_login(user_a)
        html = client.get("/bids/skipped/").content.decode()
        assert "弊社の登録資格" in html
        # 工事の見送りには防衛省の電気工事、役務の見送りには統一資格の物品の販売が並ぶ
        assert "電気工事" in html
        assert "物品の販売" in html


@pytest.mark.django_db
class TestProjectDetailShortfall:
    """案件詳細の参加資格判定に、資格不足の理由と弊社の登録資格を出す。"""

    def test_ineligible_shows_shortfall_and_our_qualifications(self, client, company_a, user_a):
        Qualification.unscoped.create(
            company=company_a, issuer="防衛省", category="電気工事", grade="A",
            total_score=884, valid_until=datetime.date(2027, 3, 31),
        )
        project = BidProject.unscoped.create(
            company=company_a, created_by=user_a,
            title="朝霞外 建築改修工事", client="防衛省北関東防衛局", category="建築",
        )
        client.force_login(user_a)
        html = client.get(f"/bids/{project.pk}/").content.decode()
        assert "不足している資格" in html
        assert "建築 に対応する業種区分" in html
        assert "弊社の登録資格" in html
        assert "電気工事" in html

    def test_eligible_hides_shortfall(self, client, company_a, user_a):
        Qualification.unscoped.create(
            company=company_a, issuer="防衛省", category="電気工事", grade="A",
            valid_until=datetime.date(2027, 3, 31),
        )
        project = BidProject.unscoped.create(
            company=company_a, created_by=user_a,
            title="朝霞外 照明設備更新電気工事", client="防衛省北関東防衛局", category="電気",
        )
        client.force_login(user_a)
        html = client.get(f"/bids/{project.pk}/").content.decode()
        assert "不足している資格" not in html
        assert "確認が必要な点" not in html
