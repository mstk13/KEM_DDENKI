"""現場名の重複に、登録する前に気づけるようにする（ADR-0077）。

確かめること:

- 表記のゆれ（全角スペース・半角カナ・頭の注記・「工事」の有無）を越えて似た現場を拾う
- 関係のない現場は拾わない
- 候補は出すだけで、同じ名前でも登録は通る（別年度の同名工事があるため）
- 他社の現場は拾わない（テナント越境）
"""
import datetime

import pytest

from apps.sites.models import Site
from apps.sites.name_match import (
    find_similar_sites,
    normalize_site_name,
    similarity,
)

BASE = "七沢自然ふれあいセンター改修工事"


def _site(company, name, **kwargs):
    fields = {"status": Site.Status.ESTIMATING}
    fields.update(kwargs)
    code = fields.pop("code", None) or f"S{abs(hash(name)) % 100000}"
    return Site.unscoped.create(company=company, code=code, name=name, **fields)


class TestNormalize:
    def test_全角スペースと半角カナを均す(self):
        assert normalize_site_name("七沢自然ふれあい　ｾﾝﾀｰ") == normalize_site_name(
            "七沢自然ふれあいセンター",
        )

    def test_括弧の注記を落とす(self):
        assert normalize_site_name("（仮）厚木市庁舎") == normalize_site_name("厚木市庁舎")

    def test_工事の有無で変わらない(self):
        assert normalize_site_name("厚木市庁舎改修工事") == normalize_site_name("厚木市庁舎改修")

    def test_空文字は空文字のまま(self):
        assert normalize_site_name("") == ""
        assert normalize_site_name(None) == ""


class TestSimilarity:
    @pytest.mark.parametrize("other", [
        "七沢自然ふれあいセンター　改修工事",      # 全角スペース
        "七沢自然ふれあいｾﾝﾀｰ改修工事",           # 半角カナ
        "（仮）七沢自然ふれあいセンター改修工事",   # 頭の注記
        "七沢自然ふれあいセンター改修",            # 「工事」なし
        "七沢自然ふれあいセンター改修工事（その2）",  # 後ろに枝番
    ])
    def test_表記のゆれは同じ現場とみなす(self, other):
        assert similarity(BASE, other) >= 0.72

    @pytest.mark.parametrize("other", [
        "厚木市立小鮎小学校電気設備工事",
        "本厚木駅前ビル改修工事",
        "",
    ])
    def test_関係のない現場は拾わない(self, other):
        assert similarity(BASE, other) < 0.72

    def test_短い名前の部分一致は当てにしない(self):
        # 「A棟」がすべての現場に当たってしまうと候補の意味がない
        assert similarity("A棟", "A棟改修に伴う電気設備工事一式") < 1.0


@pytest.mark.django_db
class TestFindSimilarSites:
    def test_似た現場を似ている順に返す(self, company_a):
        exact = _site(company_a, "七沢自然ふれあいセンター　改修工事")
        loose = _site(company_a, "七沢自然ふれあいセンター改修")
        _site(company_a, "本厚木駅前ビル改修工事")

        found = [site for site, _score in find_similar_sites(company_a, BASE)]

        assert exact in found
        assert loose in found
        assert len(found) == 2

    def test_自分自身は候補に出さない(self, company_a):
        site = _site(company_a, BASE)

        found = find_similar_sites(company_a, BASE, exclude_pk=site.pk)

        assert found == []

    def test_名前が空なら何も返さない(self, company_a):
        _site(company_a, BASE)

        assert find_similar_sites(company_a, "") == []
        assert find_similar_sites(company_a, "　") == []

    def test_他社の現場は拾わない(self, company_a, company_b):
        _site(company_b, BASE)

        assert find_similar_sites(company_a, BASE) == []


@pytest.mark.django_db
class TestSuggestionsView:
    def test_似た現場を返す(self, client, company_a, user_a):
        site = _site(
            company_a, "七沢自然ふれあいセンター　改修工事", code="S-100",
            status=Site.Status.ORDERED,
            start_date=datetime.date(2026, 5, 22),
            end_date=datetime.date(2027, 6, 30),
        )
        client.force_login(user_a)

        res = client.get("/sites/name-suggestions/", {"name": BASE})

        assert res.status_code == 200
        sites = res.json()["sites"]
        assert len(sites) == 1
        assert sites[0]["pk"] == site.pk
        assert sites[0]["code"] == "S-100"
        assert sites[0]["status"] == "受注済"
        assert sites[0]["period"] == "2026/05〜2027/06"
        assert sites[0]["url"] == f"/sites/{site.pk}/"

    def test_工期が片方しか無くても出せる(self, client, company_a, user_a):
        _site(company_a, BASE, start_date=datetime.date(2026, 5, 22))
        client.force_login(user_a)

        res = client.get("/sites/name-suggestions/", {"name": BASE})

        assert res.json()["sites"][0]["period"] == "2026/05"

    def test_編集中の現場は除ける(self, client, company_a, user_a):
        site = _site(company_a, BASE)
        client.force_login(user_a)

        res = client.get(
            "/sites/name-suggestions/", {"name": BASE, "exclude": str(site.pk)},
        )

        assert res.json()["sites"] == []

    def test_他社の現場は返さない(self, client, company_a, company_b, user_a):
        _site(company_b, BASE)
        client.force_login(user_a)

        res = client.get("/sites/name-suggestions/", {"name": BASE})

        assert res.json()["sites"] == []

    def test_ログインしていないと使えない(self, client, company_a):
        _site(company_a, BASE)

        res = client.get("/sites/name-suggestions/", {"name": BASE})

        assert res.status_code == 302


@pytest.mark.django_db
class TestSiteForm:
    def test_登録画面に現場名の候補が並ぶ(self, client, company_a, user_a):
        _site(company_a, BASE)
        client.force_login(user_a)

        html = client.get("/sites/new/").content.decode()

        assert 'id="site-name-options"' in html
        assert f'<option value="{BASE}">' in html
        assert 'list="site-name-options"' in html

    def test_編集画面の候補に自分自身は出ない(self, client, company_a, user_a):
        site = _site(company_a, BASE)
        other = _site(company_a, "本厚木駅前ビル改修工事")
        client.force_login(user_a)

        html = client.get(f"/sites/{site.pk}/edit/").content.decode()

        options = html.split('id="site-name-options"')[1].split("</datalist>")[0]
        assert other.name in options
        assert BASE not in options

    def test_似た名前でも登録は通る(self, client, company_a, user_a):
        """候補は気づかせるためのもので、登録を止めない。

        同じ建物の別年度の工事が同じ名前になることは正当にある。
        """
        _site(company_a, BASE)
        client.force_login(user_a)

        res = client.post("/sites/new/", {
            "code": "S-2027", "name": BASE, "status": Site.Status.ESTIMATING,
            "contract_amount": "0", "payment_terms": "",
            "estimate_valid_until": "", "start_date": "", "end_date": "",
            "manager": "", "estimator": "", "customer_name": "",
            "address": "", "note": "", "extracted_details": "",
        })

        assert res.status_code == 302
        assert Site.unscoped.filter(company=company_a, name=BASE).count() == 2
