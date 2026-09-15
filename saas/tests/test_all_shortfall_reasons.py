"""資格不足の理由は1つ目で止めず、不足する要件をすべて出す（ADR-0066）。

- 判定結果に不足の理由をすべて並べる。確かめられなかった要件は「要確認」として添える
- 参加要件の表では、それぞれの理由をその話をしている項目の右側に出す
- 取り込み時に見送った案件の理由にも、すべて残す
"""

import datetime

import pytest

from apps.bids.models import BidProject, ConstructionLicense, Qualification, SkippedBid
from apps.bids.qualification import check_project

TODAY = datetime.date(2026, 9, 15)
FAR = datetime.date(2099, 3, 31)

REQUIREMENTS = (
    "(1) 予算決算及び会計令第70条及び第71条の規定に該当しない者であること。\n"
    "(2) 電気工事業に係る特定建設業の許可を受けていること。\n"
    "(3) 電気設備工事Ａ等級に認定されている者であること。\n"
    "(4) 経営事項評価数値が2,000点以上であること。\n"
    "(5) 静岡県内に本店又は支店を有すること。"
)
LICENSE_REASON = (
    "電気工事業の特定建設業の許可が必要ですが、自社の電気工事業は"
    "一般建設業の許可です（神奈川県知事 許可（般-7）第5170号）。"
)
LOCATION_REASON = (
    "静岡県に建設業許可に基づく本店・支店・営業所が必要ですが、"
    "自社は神奈川県知事の許可のため、営業所は神奈川県だけです。"
)


def _general_electric_license(company, valid_until=FAR):
    return ConstructionLicense.unscoped.create(
        company=company, trade="電気工事業",
        license_class=ConstructionLicense.LicenseClass.GENERAL,
        grantor_type=ConstructionLicense.GrantorType.GOVERNOR, authority="神奈川県知事",
        license_number="許可（般-7）第5170号",
        valid_from=datetime.date(2025, 4, 21), valid_until=valid_until,
    )


def _chubu_qualification(company, valid_until=FAR, grade="B"):
    return Qualification.unscoped.create(
        company=company, issuer="国土交通省(中部地方整備局)", category="電気設備",
        grade=grade, total_score=1957, valid_until=valid_until,
    )


def _project_kwargs(**kw):
    base = {
        "title": "青崩峠トンネル照明設備工事", "client": "国土交通省中部地方整備局",
        "category": "電気設備工事", "required_grades": "A", "required_score": 2000,
        "requirements": REQUIREMENTS,
    }
    base.update(kw)
    return base


@pytest.mark.django_db
class TestAllShortfalls:
    def test_不足する要件をすべて理由に並べる(self, company_a):
        quals = [_chubu_qualification(company_a)]
        licenses = [_general_electric_license(company_a)]
        project = BidProject(company=company_a, **_project_kwargs())

        verdict = check_project(project, quals, today=TODAY, licenses=licenses)

        assert verdict["eligible"] is False
        assert [s["failed_on"] for s in verdict["shortfalls"]] == [
            "license", "location", "grades", "score",
        ]
        assert verdict["failed_on"] == "license"
        assert verdict["reason_lines"] == [
            LICENSE_REASON,
            LOCATION_REASON,
            "A等級の認定が必要ですが、自社は B 等級です"
            "（国土交通省(中部地方整備局)／電気設備 / B等級 / 総合点1957 / 期限2099-03-31）。",
            "2000点以上が必要ですが、自社は 1957 点です"
            "（国土交通省(中部地方整備局)／電気設備 / B等級 / 総合点1957 / 期限2099-03-31）。",
        ]
        assert verdict["reason"] == "\n".join(verdict["reason_lines"])

    def test_期限切れでも等級の不足を続けて確かめる(self, company_a):
        expired = _chubu_qualification(company_a, valid_until=datetime.date(2026, 3, 31))
        project = BidProject(
            company=company_a, **_project_kwargs(required_score=None, requirements=""),
        )

        verdict = check_project(project, [expired], today=TODAY, licenses=[])

        assert [s["failed_on"] for s in verdict["shortfalls"]] == ["expired", "grades"]
        assert verdict["matched"] == expired
        assert "2026-03-31 に有効期限が切れています" in verdict["reason_lines"][0]

    def test_統一資格も期限切れと等級の不足を両方出す(self, company_a):
        unified = Qualification.unscoped.create(
            company=company_a, issuer="全省庁統一資格", category="物品の販売", grade="D",
            total_score=62, valid_until=datetime.date(2025, 3, 31),
        )
        project = BidProject(
            company=company_a, title="トナー", client="海上自衛隊 横須賀基地",
            required_issuer_type="全省庁統一資格", required_category="物品の販売",
            required_grade="C",
        )

        verdict = check_project(project, [unified], today=TODAY)

        assert [s["failed_on"] for s in verdict["shortfalls"]] == ["expired", "grade"]

    def test_確かめられなかった要件は要確認として添える(self, company_a):
        licenses = [_general_electric_license(company_a)]
        project = BidProject(company=company_a, **_project_kwargs())

        verdict = check_project(project, [], today=TODAY, licenses=licenses)

        assert verdict["eligible"] is False
        assert verdict["reason_lines"] == [
            LICENSE_REASON,
            LOCATION_REASON,
            "要確認: 入札参加資格が未登録です。資格マスタに登録すると自動判定できます。",
        ]

    def test_不足が1つなら理由はこれまでどおり1文(self, company_a):
        quals = [_chubu_qualification(company_a, grade="A")]
        project = BidProject(
            company=company_a, **_project_kwargs(required_score=None, requirements=""),
        )

        verdict = check_project(project, quals, today=TODAY, licenses=[])

        assert verdict["eligible"] is True

        quals[0].grade = "B"
        verdict = check_project(project, quals, today=TODAY, licenses=[])

        assert verdict["eligible"] is False
        assert len(verdict["reason_lines"]) == 1
        assert "\n" not in verdict["reason"]


@pytest.mark.django_db
class TestProjectDetail:
    def test_それぞれの理由を該当する項目の右に出す(self, client, company_a, user_a):
        _chubu_qualification(company_a)
        _general_electric_license(company_a)
        project = BidProject.unscoped.create(
            company=company_a, created_by=user_a, **_project_kwargs(),
        )
        client.force_login(user_a)

        html = client.get(f"/bids/{project.pk}/").content.decode()

        # 判定結果に4つとも並ぶ
        reasons = html.split('class="shortfall-reasons"')[1].split("</ul>")[0]
        assert reasons.count("<li>") == 4
        # 満たした要件が無いときは「読み取れていません」と取り違えない
        assert "満たした要件はありません" in html

        rows = html.split("<tr>")

        def row(word):
            return next(r for r in rows if word in r)

        license_row = row("特定建設業の許可を受けて")
        grade_row = row("Ａ等級に認定")
        score_row = row("2,000点以上")
        office_row = row("静岡県内に本店")
        other_row = row("第70条及び第71条")
        assert "一般建設業の許可です" in license_row
        assert "自社は B 等級です" in grade_row
        assert "自社は 1957 点です" in score_row
        assert "営業所は神奈川県だけです" in office_row
        assert "shortfall-note" not in other_row
        # それぞれの項目には自分の理由だけが付く
        assert "自社は B 等級です" not in license_row
        assert "一般建設業の許可です" not in office_row


@pytest.mark.django_db
class TestSkippedBid:
    def test_見送り案件の理由にもすべて残す(self, monkeypatch, client, company_a, user_a):
        from tests.test_bids_eligible_scrape import TestOnlyEligibleScrape as Helper

        Qualification.unscoped.create(
            company=company_a, issuer="防衛省", category="電気工事", grade="B",
            total_score=884, valid_until=FAR,
        )
        _general_electric_license(company_a)
        helper = Helper()
        target = helper._target(company_a, user_a)
        records = [
            {"title": "横田飛行場（２６）電気設備改修工事", "client": "航空自衛隊 横田基地",
             "category": "電気工事", "source_url": "https://x/yokota.pdf"},
        ]
        announcements = {
            "https://x/yokota.pdf": {
                "required_issuer_type": "防衛省", "required_category": "電気工事",
                "required_grades": "A",
                "requirements": (
                    "(10) 防衛省競争参加資格の「電気工事」に係る等級がＡ等級であること。\n"
                    "(11) 北関東防衛局の管轄区域(東京都、茨城県、栃木県、群馬県、埼玉県、千葉県、"
                    "新潟県及び長野県)内に建設業法の許可(当該工事に対応する建設業種)に基づく"
                    "本店、支店又は営業所が所在すること。"
                ),
            },
        }

        helper._run(monkeypatch, records, announcements, target, company_a)

        skipped = SkippedBid.unscoped.get(company=company_a)
        lines = skipped.reason.split("\n")
        assert len(lines) == 2
        assert "営業所は神奈川県だけです" in lines[0]
        assert "A等級の認定が必要ですが、自社は B 等級です" in lines[1]

        client.force_login(user_a)
        html = client.get("/bids/skipped/").content.decode()
        assert "営業所は神奈川県だけです。<br>A等級の認定が必要ですが" in html
