"""機械が拾えなかった組を、人が選んでまとめる（ADR-0086）。

確かめること:

1. 候補に出ていない2つでも、画面から選んでまとめられる
2. まとめたあとの名前を、どれとも違う名前に揃えられる
3. まとめた現場は現場一覧に出ない。詳細を開けば行き先が分かる
4. 手で選んだ統合も取り消せる（付け替えた行を記録する）
5. 同じ現場・統合済みの現場・他社の現場は選べない
"""
import datetime

import pytest

from apps.masters.models import WorkType
from apps.reports.models import DailyReport
from apps.sites.merge import candidate_for, undo_merge
from apps.sites.models import Site, SiteMergeCandidate
from apps.sites.name_match import similarity
from apps.workers.models import Worker

MANUAL_URL = "/sites/merge/manual/"
DAY = datetime.date(2026, 9, 10)


def _site(company, code, name, **kwargs):
    return Site.unscoped.create(company=company, code=code, name=name, **kwargs)


@pytest.fixture
def festival(company_a):
    """本番にある3つの表記ゆれ。字面が離れていて機械では拾えない組を含む。"""
    return {
        "atsugi_ayu": _site(company_a, "S101", "厚木あゆ祭り"),
        "ayu": _site(company_a, "S102", "あゆ祭り"),
        "atsugi_matsuri": _site(company_a, "S103", "厚木鮎まつり"),
    }


@pytest.fixture
def report_setup(company_a):
    work_type = WorkType.unscoped.create(company=company_a, code="W01", name="電気工事")
    worker = Worker.unscoped.create(company=company_a, name="電工太郎")
    return work_type, worker


def _report(company, site, setup, day=DAY):
    work_type, worker = setup
    return DailyReport.unscoped.create(
        company=company, site=site, work_type=work_type, worker=worker,
        report_date=day, work_hours=8,
    )


# ---------------------------------------------------------------------------
# なぜ手で選ぶ必要があるか
# ---------------------------------------------------------------------------

def test_字面の離れた組は文字だけでは候補にならない():
    """ローカルAIに繋がらない環境では、この組は候補にすら出ない。"""
    from apps.sites.merge_candidates import NAME_THRESHOLD

    assert similarity("高橋住宅", "高橋アパート") < NAME_THRESHOLD
    assert similarity("厚木鮎まつり", "あゆ祭り") < NAME_THRESHOLD


# ---------------------------------------------------------------------------
# 手で選んでまとめる
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestManualMerge:
    def test_候補に無い2つをまとめられる(self, client, company_a, user_a, festival, report_setup):
        keep, drop = festival["atsugi_ayu"], festival["atsugi_matsuri"]
        _report(company_a, drop, report_setup)
        client.force_login(user_a)

        res = client.post(MANUAL_URL, {"primary": keep.pk, "duplicate": drop.pk})

        assert res.status_code == 302
        drop.refresh_from_db()
        assert drop.merged_into_id == keep.pk
        assert DailyReport.unscoped.get(company=company_a).site_id == keep.pk

    def test_まとめたあとの名前を揃えられる(self, client, company_a, user_a, festival):
        keep, drop = festival["atsugi_ayu"], festival["ayu"]
        client.force_login(user_a)

        client.post(MANUAL_URL, {
            "primary": keep.pk, "duplicate": drop.pk, "new_name": "厚木鮎祭り",
        })

        keep.refresh_from_db()
        assert keep.name == "厚木鮎祭り"

    def test_名前が空なら残す現場の名前はそのまま(self, client, company_a, user_a, festival):
        keep, drop = festival["atsugi_ayu"], festival["ayu"]
        client.force_login(user_a)

        client.post(MANUAL_URL, {"primary": keep.pk, "duplicate": drop.pk, "new_name": ""})

        keep.refresh_from_db()
        assert keep.name == "厚木あゆ祭り"

    def test_3つを2回に分けてまとめられる(self, client, company_a, user_a, festival, report_setup):
        keep = festival["atsugi_ayu"]
        client.force_login(user_a)
        for site, day in (
            (festival["ayu"], DAY), (festival["atsugi_matsuri"], DAY + datetime.timedelta(days=1)),
        ):
            _report(company_a, site, report_setup, day=day)

        client.post(MANUAL_URL, {"primary": keep.pk, "duplicate": festival["ayu"].pk})
        client.post(MANUAL_URL, {
            "primary": keep.pk, "duplicate": festival["atsugi_matsuri"].pk,
            "new_name": "厚木鮎祭り",
        })

        keep.refresh_from_db()
        assert keep.name == "厚木鮎祭り"
        assert DailyReport.unscoped.filter(company=company_a, site=keep).count() == 2
        assert Site.unscoped.filter(company=company_a, merged_into=keep).count() == 2

    def test_手で選んだ統合も取り消せる(self, client, company_a, user_a, festival, report_setup):
        keep, drop = festival["atsugi_ayu"], festival["ayu"]
        _report(company_a, drop, report_setup)
        client.force_login(user_a)

        client.post(MANUAL_URL, {"primary": keep.pk, "duplicate": drop.pk})
        candidate = SiteMergeCandidate.unscoped.get(company=company_a)
        assert candidate.moved_rows  # 取り消しに使う記録が残っている

        undo_merge(candidate, user=user_a)

        drop.refresh_from_db()
        assert drop.merged_into_id is None
        assert DailyReport.unscoped.get(company=company_a).site_id == drop.pk


# ---------------------------------------------------------------------------
# 入力の確かめ
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestValidation:
    def test_同じ現場は選べない(self, client, company_a, user_a, festival):
        site = festival["ayu"]
        client.force_login(user_a)

        client.post(MANUAL_URL, {"primary": site.pk, "duplicate": site.pk})

        site.refresh_from_db()
        assert site.merged_into_id is None

    def test_片方が空なら何も起きない(self, client, company_a, user_a, festival):
        client.force_login(user_a)

        client.post(MANUAL_URL, {"primary": festival["ayu"].pk, "duplicate": ""})

        assert not Site.unscoped.filter(company=company_a).exclude(
            merged_into__isnull=True,
        ).exists()

    def test_統合済みの現場は選べない(self, client, company_a, user_a, festival):
        keep, drop, third = (
            festival["atsugi_ayu"], festival["ayu"], festival["atsugi_matsuri"],
        )
        client.force_login(user_a)
        client.post(MANUAL_URL, {"primary": keep.pk, "duplicate": drop.pk})

        client.post(MANUAL_URL, {"primary": third.pk, "duplicate": drop.pk})

        drop.refresh_from_db()
        assert drop.merged_into_id == keep.pk

    def test_ログインしていなければ使えない(self, client, company_a, festival):
        res = client.post(MANUAL_URL, {
            "primary": festival["atsugi_ayu"].pk, "duplicate": festival["ayu"].pk,
        })

        assert res.status_code == 302
        assert "/login/" in res["Location"]
        festival["ayu"].refresh_from_db()
        assert festival["ayu"].merged_into_id is None


# ---------------------------------------------------------------------------
# 現場一覧と詳細
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSiteList:
    def test_まとめた現場は一覧に出ない(self, client, company_a, user_a, festival):
        keep, drop = festival["atsugi_ayu"], festival["ayu"]
        client.force_login(user_a)
        client.post(MANUAL_URL, {"primary": keep.pk, "duplicate": drop.pk})

        html = client.get("/sites/").content.decode()

        assert "厚木あゆ祭り" in html
        assert "あゆ祭り</" not in html.replace("厚木あゆ祭り</", "")

    def test_まとめた現場の詳細に行き先が出る(self, client, company_a, user_a, festival):
        keep, drop = festival["atsugi_ayu"], festival["ayu"]
        client.force_login(user_a)
        client.post(MANUAL_URL, {"primary": keep.pk, "duplicate": drop.pk})

        html = client.get(f"/sites/{drop.pk}/").content.decode()

        assert "にまとめました" in html
        assert "厚木あゆ祭り" in html

    def test_名寄せ画面に選べる現場が並ぶ(self, client, company_a, user_a, festival):
        client.force_login(user_a)

        html = client.get("/sites/merge/").content.decode()

        assert "手で選んでまとめる" in html
        assert 'name="primary"' in html
        assert "厚木鮎まつり" in html


# ---------------------------------------------------------------------------
# 候補の行
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCandidateRow:
    def test_手で選んだ組にも候補の行を作る(self, company_a, festival, user_a):
        keep, drop = festival["atsugi_ayu"], festival["ayu"]

        candidate = candidate_for(company_a, keep, drop, user=user_a)

        assert candidate.pk is not None
        assert candidate.hints == "人が選んだ組"

    def test_向きが逆でも同じ行を使い回す(self, company_a, festival, user_a):
        keep, drop = festival["atsugi_ayu"], festival["ayu"]
        first = SiteMergeCandidate.unscoped.create(
            company=company_a, primary=drop, duplicate=keep, name_score=0.9,
        )

        again = candidate_for(company_a, keep, drop, user=user_a)

        assert again.pk == first.pk
        assert SiteMergeCandidate.unscoped.filter(company=company_a).count() == 1


# ---------------------------------------------------------------------------
# テナント越境
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTenantIsolation:
    def test_他社の現場は選べない(self, client, company_a, company_b, user_a, festival):
        other = _site(company_b, "B001", "あゆ祭り")
        client.force_login(user_a)

        client.post(MANUAL_URL, {"primary": festival["atsugi_ayu"].pk, "duplicate": other.pk})

        other.refresh_from_db()
        assert other.merged_into_id is None

    def test_他社の現場は名寄せ画面に並ばない(
        self, client, company_a, company_b, user_a, festival,
    ):
        _site(company_b, "B001", "他社の現場")
        client.force_login(user_a)

        html = client.get("/sites/merge/").content.decode()

        assert "他社の現場" not in html
