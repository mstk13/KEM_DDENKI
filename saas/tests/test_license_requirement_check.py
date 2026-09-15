"""公告の建設業許可・営業所の所在地の要件を、自社の建設業許可と照らす（ADR-0065）。

- 公告に書かれていなければ照らさない。書かれていれば必ず照らす
- 足りなければ資格不足にし、判定結果と参加要件の該当項目の右側に理由を出す
- 取り込み時（資格を満たす案件だけ取り込む）も同じ判定で見送り、理由を残す
"""

import datetime

import pytest

from apps.bids.announcement import extract_license_requirement
from apps.bids.models import BidProject, ConstructionLicense, Qualification, SkippedBid
from apps.bids.qualification import check_project, trades_for_category

TODAY = datetime.date(2026, 9, 15)

YOKOTA = (
    "８ 競争参加資格\n"
    "(10) 防衛省競争参加資格の「電気工事」に係る等級がＡ等級であること。\n"
    "(11) 北関東防衛局の管轄区域(東京都、茨城県、栃木県、群馬県、埼玉県、千葉県、\n"
    "新潟県及び長野県)内に建設業法の許可(当該工事に対応する建設業種)に基づ\n"
    "く本店、支店又は営業所が所在すること。"
)
SPECIAL_ELECTRIC = "(3) 電気工事業に係る特定建設業の許可を受けていること。"
SPECIAL_TELECOM = "(3) 電気通信工事業に係る特定建設業の許可を受けていること。"
GENERAL_TELECOM = (
    "(4) 建設業法第３条第１項の規定による電気通信工事業の許可を受けていること。"
)
PIPE = "(4) 管工事業の許可を受けていること。"
KANAGAWA = "(2) 神奈川県内に本店又は支店を有する者であること。"
NOT_OWN = (
    "(5) 下請契約の相手方は建設業法の許可を受けた者とすること。\n"
    "(6) 建設業法第28条の規定による営業停止処分を受けていないこと。\n"
    "(7) 電気設備工事Ａ等級に認定されている者であること。"
)
YOKOTA_REASON = (
    "北関東防衛局の管轄区域（東京都、茨城県、栃木県、群馬県、埼玉県、千葉県、新潟県、長野県）"
    "に建設業許可に基づく本店・支店・営業所が必要ですが、"
    "自社は神奈川県知事の許可のため、営業所は神奈川県だけです。"
)


def _licenses(company, valid_until=datetime.date(2030, 4, 20), **extra):
    common = {
        "grantor_type": ConstructionLicense.GrantorType.GOVERNOR,
        "authority": "神奈川県知事",
        "valid_from": datetime.date(2025, 4, 21),
        "valid_until": valid_until,
        "renewal_deadline": None,
    }
    common.update(extra)
    return [
        ConstructionLicense.unscoped.create(
            company=company, trade="電気工事業",
            license_class=ConstructionLicense.LicenseClass.SPECIAL,
            license_number="許可（特-7）第5170号", **common,
        ),
        ConstructionLicense.unscoped.create(
            company=company, trade="電気通信工事業",
            license_class=ConstructionLicense.LicenseClass.GENERAL,
            license_number="許可（般-7）第5170号", **common,
        ),
    ]


def _mod_qualification(company, valid_until=datetime.date(2099, 3, 31)):
    return Qualification.unscoped.create(
        company=company, issuer="防衛省", category="電気工事", grade="A",
        total_score=884, valid_until=valid_until,
    )


def _project(company, requirements, **kw):
    base = {
        "title": "横田飛行場（２６）電気設備改修工事", "client": "防衛省北関東防衛局",
        "category": "電気工事", "required_issuer_type": "防衛省",
        "required_category": "電気工事", "requirements": requirements,
    }
    base.update(kw)
    return BidProject(company=company, **base)


class TestExtractLicenseRequirement:
    def test_横田の所在地の要件(self):
        req = extract_license_requirement(YOKOTA)

        assert req["license_class"] == "general"
        assert req["trades"] == []
        assert req["prefectures"] == [
            "東京都", "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "新潟県", "長野県",
        ]
        assert req["area_name"] == "北関東防衛局"
        assert "営業所が所在すること" in req["office_text"]

    def test_特定建設業の許可と業種(self):
        req = extract_license_requirement(SPECIAL_ELECTRIC)
        assert (req["license_class"], req["trades"]) == ("special", ["電気工事業"])
        assert req["prefectures"] == []

    def test_建設業法の規定による許可と業種(self):
        req = extract_license_requirement(GENERAL_TELECOM)
        assert (req["license_class"], req["trades"]) == ("general", ["電気通信工事業"])

    def test_営業所の所在地だけの要件(self):
        req = extract_license_requirement(KANAGAWA)
        assert (req["license_class"], req["prefectures"]) == ("", ["神奈川県"])

    def test_自社の許可の要件でない文は拾わない(self):
        req = extract_license_requirement(NOT_OWN)
        assert req["license_class"] == ""
        assert req["trades"] == []
        assert req["prefectures"] == []

    def test_工事種別から許可の業種を決める(self):
        assert trades_for_category("電気設備工事") == ["電気工事業"]
        assert trades_for_category("電気通信設備工事") == ["電気通信工事業"]
        assert trades_for_category("建築一式工事／管工事") == ["建築工事業", "管工事業"]
        assert trades_for_category("") == []


@pytest.mark.django_db
class TestLicenseRequirementCheck:
    def test_管轄区域に営業所が無ければ資格不足(self, company_a):
        quals = [_mod_qualification(company_a)]
        project = _project(company_a, YOKOTA, required_grades="A")

        verdict = check_project(project, quals, today=TODAY, licenses=_licenses(company_a))

        assert verdict["eligible"] is False
        assert verdict["failed_on"] == "location"
        assert verdict["reason"] == YOKOTA_REASON

    def test_特定が要るのに一般なら資格不足(self, company_a):
        project = _project(
            company_a, SPECIAL_TELECOM, category="電気通信", required_category="電気通信",
        )

        verdict = check_project(project, [], today=TODAY, licenses=_licenses(company_a))

        assert verdict["eligible"] is False
        assert verdict["failed_on"] == "license"
        assert verdict["reason"] == (
            "電気通信工事業の特定建設業の許可が必要ですが、自社の電気通信工事業は"
            "一般建設業の許可です（神奈川県知事 許可（般-7）第5170号）。"
        )

    def test_特定の電気工事業なら満たし根拠を出す(self, company_a):
        quals = [_mod_qualification(company_a)]
        project = _project(company_a, SPECIAL_ELECTRIC)

        verdict = check_project(project, quals, today=TODAY, licenses=_licenses(company_a))

        assert verdict["eligible"] is True
        assert (
            "特定建設業の許可（電気工事業） → 自社 電気工事業 特定 "
            "神奈川県知事 許可（特-7）第5170号"
            in verdict["checked"]
        )
        assert "公告の要件を満たします" in verdict["reason"]

    def test_一般で足りる電気通信工事業は満たす(self, company_a):
        quals = [
            Qualification.unscoped.create(
                company=company_a, issuer="防衛省", category="電気通信", grade="C",
                valid_until=datetime.date(2099, 3, 31),
            ),
        ]
        project = _project(
            company_a, GENERAL_TELECOM, category="電気通信", required_category="電気通信",
        )

        verdict = check_project(project, quals, today=TODAY, licenses=_licenses(company_a))

        assert verdict["eligible"] is True

    def test_許可の無い業種なら資格不足(self, company_a):
        project = _project(company_a, PIPE, category="管工事", required_category="管工事")

        verdict = check_project(project, [], today=TODAY, licenses=_licenses(company_a))

        assert verdict["eligible"] is False
        assert verdict["reason"] == (
            "管工事業の建設業の許可が必要ですが、"
            "自社の建設業許可は 電気工事業・電気通信工事業 だけです。"
        )

    def test_有効期間が切れていれば資格不足(self, company_a):
        licenses = _licenses(company_a, valid_until=datetime.date(2026, 9, 1))
        project = _project(company_a, SPECIAL_ELECTRIC)

        verdict = check_project(project, [], today=TODAY, licenses=licenses)

        assert verdict["eligible"] is False
        assert "2026-09-01 に有効期間が切れています" in verdict["reason"]

    def test_公告に書かれていなければ照らさない(self, company_a):
        quals = [_mod_qualification(company_a)]
        project = _project(company_a, NOT_OWN)

        with_licenses = check_project(
            project, quals, today=TODAY, licenses=_licenses(company_a),
        )
        without = check_project(project, quals, today=TODAY, licenses=[])

        assert with_licenses["eligible"] is True
        assert with_licenses["reason"] == without["reason"]
        assert with_licenses["license_requirement"]["license_class"] == ""

    def test_許可が未登録なら要確認(self, company_a):
        project = _project(company_a, YOKOTA)

        verdict = check_project(project, [_mod_qualification(company_a)], today=TODAY, licenses=[])

        assert verdict["eligible"] is None
        assert "自社の建設業許可が未登録" in verdict["reason"]

    def test_所在地の要件を満たせば根拠を出す(self, company_a):
        quals = [_mod_qualification(company_a)]
        project = _project(company_a, KANAGAWA)

        verdict = check_project(project, quals, today=TODAY, licenses=_licenses(company_a))

        assert verdict["eligible"] is True
        assert "営業所の所在地 神奈川県 → 自社 神奈川県" in verdict["checked"]

    def test_大臣許可なら所在地は公告で確認(self, company_a):
        licenses = _licenses(
            company_a, grantor_type=ConstructionLicense.GrantorType.MINISTER,
            authority="国土交通大臣",
        )
        project = _project(company_a, YOKOTA)

        verdict = check_project(
            project, [_mod_qualification(company_a)], today=TODAY, licenses=licenses,
        )

        assert verdict["eligible"] is True
        assert any("国土交通大臣許可のため公告で確認" in c for c in verdict["checked"])


@pytest.mark.django_db
class TestProjectDetail:
    def test_判定結果と参加要件の該当項目に理由を出す(self, client, company_a, user_a):
        _mod_qualification(company_a)
        _licenses(company_a, valid_until=datetime.date(2099, 4, 20))
        project = BidProject.unscoped.create(
            company=company_a, created_by=user_a, title="横田飛行場（２６）電気設備改修工事",
            client="防衛省北関東防衛局", category="電気工事", required_issuer_type="防衛省",
            required_category="電気工事", required_grades="A", requirements=YOKOTA,
        )
        client.force_login(user_a)

        html = client.get(f"/bids/{project.pk}/").content.decode()

        assert "資格不足" in html
        rows = html.split("<tr>")
        office_row = next(r for r in rows if "営業所が所在すること" in r)
        grade_row = next(r for r in rows if "Ａ等級であること" in r)
        assert "shortfall-note" in office_row
        assert "営業所は神奈川県だけです" in office_row
        assert "shortfall-note" not in grade_row
        assert "北関東防衛局の管轄区域: 東京都、茨城県、栃木県" in html
        assert "当該工事に対応する業種" in html


@pytest.mark.django_db
class TestOnlyEligibleScrape:
    def test_所在地の要件で見送り理由を残す(self, monkeypatch, company_a, user_a):
        from tests.test_bids_eligible_scrape import TestOnlyEligibleScrape as Helper

        _mod_qualification(company_a)
        _licenses(company_a, valid_until=datetime.date(2099, 4, 20))
        helper = Helper()
        target = helper._target(company_a, user_a)
        records = [
            {"title": "横田飛行場（２６）電気設備改修工事", "client": "航空自衛隊 横田基地",
             "category": "電気工事", "source_url": "https://x/yokota.pdf"},
            {"title": "入間基地照明設備改修", "client": "航空自衛隊 入間基地",
             "category": "電気工事", "source_url": "https://x/iruma.pdf"},
        ]
        common = {
            "required_issuer_type": "防衛省", "required_category": "電気工事",
            "required_grades": "A",
        }
        announcements = {
            "https://x/yokota.pdf": {**common, "requirements": YOKOTA},
            "https://x/iruma.pdf": {**common, "requirements": NOT_OWN},
        }

        result = helper._run(monkeypatch, records, announcements, target, company_a)

        assert (result["new"], result["ineligible"]) == (1, 1)
        assert list(
            BidProject.unscoped.filter(company=company_a).values_list("title", flat=True)
        ) == ["入間基地照明設備改修"]
        skipped = SkippedBid.unscoped.get(company=company_a)
        assert skipped.verdict == SkippedBid.Verdict.INELIGIBLE
        assert skipped.reason == YOKOTA_REASON
