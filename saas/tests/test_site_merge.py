"""同じ現場が別名で登録されたときの名寄せ（ADR-0084）。

- 文字が似ていなくても、意味が近ければ候補に出す（高橋住宅 / 高橋アパート）
- 統合は人が決める。押すと日報などの紐づけを付け替える
- 付け替えてぶつかる行は動かさず、報告に出す
- 統合は取り消せる
"""

import datetime
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.costs.models import BudgetItem
from apps.masters.models import CostCategory, Customer, WorkType
from apps.reports.models import DailyReport
from apps.sites.merge import merge_sites, undo_merge
from apps.sites.merge_candidates import find_candidates
from apps.sites.models import Site, SiteMergeCandidate
from apps.workers.models import Worker

DAY = datetime.date(2026, 9, 10)


def _site(company, code, name, **kwargs):
    return Site.unscoped.create(company=company, code=code, name=name, **kwargs)


@pytest.fixture
def pair(company_a):
    return (
        _site(company_a, "S001", "高橋住宅"),
        _site(company_a, "S002", "高橋アパート"),
    )


@pytest.fixture
def report_setup(company_a, user_a):
    work_type = WorkType.unscoped.create(company=company_a, code="W01", name="電気工事")
    worker = Worker.unscoped.create(company=company_a, name="電工太郎")
    return work_type, worker


def _report(company, site, work_type, worker, day=DAY):
    return DailyReport.unscoped.create(
        company=company, site=site, work_type=work_type, worker=worker,
        report_date=day, work_hours=8,
    )


@pytest.mark.django_db
class TestFindCandidates:
    def test_文字が似ていれば候補にする(self, company_a):
        _site(company_a, "S001", "鮎まつり")
        _site(company_a, "S002", "厚木鮎まつり")

        find_candidates(company_a, judge=False)

        candidate = SiteMergeCandidate.unscoped.get()
        assert {candidate.primary.name, candidate.duplicate.name} == {
            "鮎まつり", "厚木鮎まつり",
        }
        assert candidate.state == SiteMergeCandidate.State.PENDING

    def test_文字が似ていなくても意味が近ければ候補にする(self, company_a, pair):
        # 埋め込みは「高橋住宅」と「高橋アパート」を近いと答える想定
        vectors = [[1.0, 0.0], [0.99, 0.14]]
        with patch("apps.estimation.services.embedding.is_configured", return_value=True), \
             patch("apps.estimation.services.embedding.embed_texts", return_value=vectors):
            find_candidates(company_a, judge=False)

        candidate = SiteMergeCandidate.unscoped.get()
        assert candidate.vector_score >= 0.8
        assert candidate.name_score < 0.72

    def test_似ていない現場は候補にしない(self, company_a):
        _site(company_a, "S001", "厚木市役所改修")
        _site(company_a, "S002", "海老名駅前ビル新築")

        find_candidates(company_a, judge=False)

        assert not SiteMergeCandidate.unscoped.exists()

    def test_別物と決めた組は作り直さない(self, company_a):
        first = _site(company_a, "S001", "鮎まつり")
        second = _site(company_a, "S002", "厚木鮎まつり")
        SiteMergeCandidate.unscoped.create(
            company=company_a, primary=first, duplicate=second,
            state=SiteMergeCandidate.State.IGNORED,
        )

        find_candidates(company_a, judge=False)

        assert SiteMergeCandidate.unscoped.count() == 1
        assert SiteMergeCandidate.unscoped.get().state == SiteMergeCandidate.State.IGNORED

    def test_AIの判定と理由を残す(self, company_a):
        _site(company_a, "S001", "鮎まつり")
        _site(company_a, "S002", "厚木鮎まつり")
        answer = {"parsed": {"same": True, "reason": "同じ催事の電気設備工事です。"}}
        with patch("apps.ai.services.local_llm.is_configured", return_value=True), \
             patch("apps.ai.services.local_llm.chat_json", return_value=answer):
            find_candidates(company_a)

        candidate = SiteMergeCandidate.unscoped.get()
        assert candidate.verdict == SiteMergeCandidate.Verdict.SAME
        assert "同じ催事" in candidate.reason

    def test_AIが止まっていても候補は出る(self, company_a):
        _site(company_a, "S001", "鮎まつり")
        _site(company_a, "S002", "厚木鮎まつり")

        with patch("apps.ai.services.local_llm.is_configured", return_value=False):
            find_candidates(company_a)

        candidate = SiteMergeCandidate.unscoped.get()
        assert candidate.verdict == SiteMergeCandidate.Verdict.UNKNOWN


@pytest.mark.django_db
class TestMerge:
    def test_紐づけを付け替えて統合済みにする(self, company_a, pair, report_setup):
        keep, drop = pair
        work_type, worker = report_setup
        _report(company_a, drop, work_type, worker)
        # CostCategory は全社共通のマスタ（テナントに属さない）
        cost_category = CostCategory.objects.create(code="M", name="材料費")
        BudgetItem.unscoped.create(
            company=company_a, site=drop, work_type=work_type,
            cost_category=cost_category, name="電線",
        )

        result = merge_sites(keep, drop)

        assert result["moved"]["reports.DailyReport"] == 1
        assert DailyReport.unscoped.get().site_id == keep.pk
        assert BudgetItem.unscoped.get().site_id == keep.pk
        drop.refresh_from_db()
        assert drop.merged_into_id == keep.pk
        assert drop.merged_at is not None

    def test_ぶつかる行は動かさずに報告する(self, company_a, pair, report_setup):
        keep, drop = pair
        work_type, worker = report_setup
        _report(company_a, keep, work_type, worker)
        _report(company_a, drop, work_type, worker)

        result = merge_sites(keep, drop)

        assert ("reports.DailyReport", 1) in result["conflicts"]
        assert DailyReport.unscoped.filter(site=drop).count() == 1

    def test_同じ現場や他社とは統合できない(self, company_a, company_b, pair):
        keep, drop = pair
        other = _site(company_b, "S001", "高橋住宅")

        with pytest.raises(ValueError):
            merge_sites(keep, keep)
        with pytest.raises(ValueError):
            merge_sites(keep, other)

    def test_統合を取り消せる(self, company_a, pair, report_setup):
        keep, drop = pair
        work_type, worker = report_setup
        _report(company_a, drop, work_type, worker)
        candidate = SiteMergeCandidate.unscoped.create(
            company=company_a, primary=keep, duplicate=drop,
        )
        merge_sites(keep, drop, candidate=candidate)

        undo_merge(candidate)

        assert DailyReport.unscoped.get().site_id == drop.pk
        drop.refresh_from_db()
        assert drop.merged_into is None
        candidate.refresh_from_db()
        assert candidate.state == SiteMergeCandidate.State.PENDING


@pytest.mark.django_db
class TestScreen:
    def test_候補の一覧が出る(self, client, company_a, user_a, pair):
        keep, drop = pair
        SiteMergeCandidate.unscoped.create(
            company=company_a, primary=keep, duplicate=drop,
            name_score=0.4, vector_score=0.91,
            verdict=SiteMergeCandidate.Verdict.SAME, reason="同じ建物の呼び方違いです。",
        )
        client.force_login(user_a)

        html = client.get(reverse("sites:merge_list")).content.decode()

        assert "高橋住宅" in html
        assert "高橋アパート" in html
        assert "同じ建物の呼び方違いです。" in html

    def test_まとめるを押すと統合する(self, client, company_a, user_a, pair, report_setup):
        keep, drop = pair
        work_type, worker = report_setup
        _report(company_a, drop, work_type, worker)
        candidate = SiteMergeCandidate.unscoped.create(
            company=company_a, primary=keep, duplicate=drop,
        )
        client.force_login(user_a)

        res = client.post(
            reverse("sites:merge_apply", args=[candidate.pk]), {"keep": "primary"},
        )

        assert res.status_code == 302
        assert DailyReport.unscoped.get().site_id == keep.pk
        candidate.refresh_from_db()
        assert candidate.state == SiteMergeCandidate.State.MERGED
        assert candidate.decided_by == user_a

    def test_どちらを残すかを選べる(self, client, company_a, user_a, pair, report_setup):
        keep, drop = pair
        work_type, worker = report_setup
        _report(company_a, keep, work_type, worker)
        candidate = SiteMergeCandidate.unscoped.create(
            company=company_a, primary=keep, duplicate=drop,
        )
        client.force_login(user_a)

        client.post(
            reverse("sites:merge_apply", args=[candidate.pk]), {"keep": "duplicate"},
        )

        assert DailyReport.unscoped.get().site_id == drop.pk
        keep.refresh_from_db()
        assert keep.merged_into_id == drop.pk

    def test_別の現場として覚える(self, client, company_a, user_a, pair):
        keep, drop = pair
        candidate = SiteMergeCandidate.unscoped.create(
            company=company_a, primary=keep, duplicate=drop,
        )
        client.force_login(user_a)

        client.post(reverse("sites:merge_ignore", args=[candidate.pk]))

        candidate.refresh_from_db()
        assert candidate.state == SiteMergeCandidate.State.IGNORED

    def test_他社の候補は触れない(self, client, company_a, company_b, user_b, pair):
        keep, drop = pair
        candidate = SiteMergeCandidate.unscoped.create(
            company=company_a, primary=keep, duplicate=drop,
        )
        client.force_login(user_b)

        res = client.post(reverse("sites:merge_apply", args=[candidate.pk]))

        assert res.status_code == 404
        candidate.refresh_from_db()
        assert candidate.state == SiteMergeCandidate.State.PENDING


@pytest.mark.django_db
class TestCustomerHint:
    def test_発注先が同じなら手がかりに出す(self, company_a):
        customer = Customer.unscoped.create(company=company_a, code="C1", name="厚木市")
        _site(company_a, "S001", "鮎まつり", customer=customer)
        _site(company_a, "S002", "厚木鮎まつり", customer=customer)

        find_candidates(company_a, judge=False)

        assert "発注先が同じ" in SiteMergeCandidate.unscoped.get().hints
