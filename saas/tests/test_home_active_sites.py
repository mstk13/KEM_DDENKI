"""ホーム「施工中の現場と今週の工程」（ADR-0032）。

固定したいのは3点:

1. 施工中の現場だけを、自社の分だけ出す（他社・他の状態の現場は出さない）
2. 「今週」は基準日を含む月曜〜日曜。週をまたいで続く工程は出し、翌週だけの工程は出さない
3. 受注金額は原価を見られる人にだけ出す。見られない人にはコンテキストにも載せない
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.tenant_context import set_current_company
from apps.schedules.models import Milestone, Phase
from apps.schedules.services import get_active_sites_with_week_schedule, week_bounds
from apps.sites.models import Site

# 2026-09-10 は木曜日。その週は 09-07（月）〜 09-13（日）。
REF = date(2026, 9, 10)
MONDAY = date(2026, 9, 7)
SUNDAY = date(2026, 9, 13)


def _site(company, code, name, status=Site.Status.IN_PROGRESS, **kwargs):
    return Site.unscoped.create(
        company=company, code=code, name=name, status=status, **kwargs,
    )


def _phase(site, name, start, end, progress=0):
    return Phase.unscoped.create(
        company=site.company, site=site, name=name,
        start_date=start, end_date=end, progress=progress,
    )


def _milestone(site, name, target):
    return Milestone.unscoped.create(
        company=site.company, site=site, name=name, target_date=target,
    )


def _entry(result, site):
    return next(s for s in result["sites"] if s["site_id"] == site.pk)


def _names(items):
    return [i.name for i in items]


@pytest.fixture
def cost_user(company_a, django_user_model):
    """社員番号が G で始まるユーザー。原価の read 権限を持つ。"""
    return django_user_model.objects.create_user(
        username="g_user",
        password="testpass123",
        company=company_a,
        employee_no="G001",
    )


@pytest.fixture
def plain_client(client, company_a, user_a):
    set_current_company(company_a)
    client.force_login(user_a)
    yield client
    set_current_company(None)


@pytest.fixture
def cost_client(client, company_a, cost_user):
    set_current_company(company_a)
    client.force_login(cost_user)
    yield client
    set_current_company(None)


# ---------------------------------------------------------------------------
# 週の境界
# ---------------------------------------------------------------------------

class TestWeekBounds:
    def test_week_runs_from_monday_to_sunday(self):
        assert week_bounds(REF) == (MONDAY, SUNDAY)

    def test_monday_and_sunday_belong_to_the_same_week(self):
        assert week_bounds(MONDAY) == (MONDAY, SUNDAY)
        assert week_bounds(SUNDAY) == (MONDAY, SUNDAY)


# ---------------------------------------------------------------------------
# サービス
# ---------------------------------------------------------------------------

class TestActiveSitesService:
    def test_only_in_progress_sites_of_the_company(self, company_a, company_b):
        _site(company_a, "S1", "A施工中")
        _site(company_a, "S2", "A受注済", status=Site.Status.ORDERED)
        _site(company_a, "S3", "A完工", status=Site.Status.COMPLETED)
        _site(company_b, "S1", "B施工中")

        result = get_active_sites_with_week_schedule(company_a, REF)

        assert [s["name"] for s in result["sites"]] == ["A施工中"]
        assert (result["week_start"], result["week_end"]) == (MONDAY, SUNDAY)

    def test_phase_continuing_from_previous_week_is_included(self, company_a):
        site = _site(company_a, "S1", "現場")
        _phase(site, "先週から", date(2026, 9, 1), date(2026, 9, 8))

        entry = _entry(get_active_sites_with_week_schedule(company_a, REF), site)

        assert _names(entry["phases"]) == ["先週から"]

    def test_phase_entirely_next_week_is_excluded(self, company_a):
        site = _site(company_a, "S1", "現場")
        _phase(site, "来週", date(2026, 9, 14), date(2026, 9, 18))

        entry = _entry(get_active_sites_with_week_schedule(company_a, REF), site)

        assert entry["phases"] == []

    def test_phase_touching_the_week_edges(self, company_a):
        """月曜に終わる工程・日曜に始まる工程は今週に含み、前の日曜に終わる工程は含まない。"""
        site = _site(company_a, "S1", "現場")
        _phase(site, "月曜まで", date(2026, 9, 1), MONDAY)
        _phase(site, "日曜から", SUNDAY, date(2026, 9, 20))
        _phase(site, "先週で終了", date(2026, 9, 1), date(2026, 9, 6))

        entry = _entry(get_active_sites_with_week_schedule(company_a, REF), site)

        assert _names(entry["phases"]) == ["月曜まで", "日曜から"]

    def test_phase_without_dates_is_excluded(self, company_a):
        site = _site(company_a, "S1", "現場")
        _phase(site, "日付なし", None, None)
        _phase(site, "終了日なし", MONDAY, None)

        entry = _entry(get_active_sites_with_week_schedule(company_a, REF), site)

        assert entry["phases"] == []

    def test_milestone_on_sunday_is_included_but_next_monday_is_not(self, company_a):
        site = _site(company_a, "S1", "現場")
        _milestone(site, "前の日曜", date(2026, 9, 6))
        _milestone(site, "月曜", MONDAY)
        _milestone(site, "日曜", SUNDAY)
        _milestone(site, "翌月曜", date(2026, 9, 14))

        entry = _entry(get_active_sites_with_week_schedule(company_a, REF), site)

        assert _names(entry["milestones"]) == ["月曜", "日曜"]

    def test_schedule_is_not_mixed_between_sites(self, company_a):
        first = _site(company_a, "S1", "現場1")
        second = _site(company_a, "S2", "現場2")
        _phase(first, "現場1の工程", MONDAY, SUNDAY)
        _milestone(second, "現場2の期日", REF)

        result = get_active_sites_with_week_schedule(company_a, REF)

        assert _names(_entry(result, first)["phases"]) == ["現場1の工程"]
        assert _entry(result, first)["milestones"] == []
        assert _entry(result, second)["phases"] == []
        assert _names(_entry(result, second)["milestones"]) == ["現場2の期日"]

    def test_sites_are_ordered_by_nearest_end_date_then_name(self, company_a):
        _site(company_a, "S1", "B現場", end_date=date(2026, 9, 30))
        _site(company_a, "S2", "D現場")  # 工期終了なしは最後
        _site(company_a, "S3", "A現場", end_date=date(2026, 9, 30))
        _site(company_a, "S4", "C現場", end_date=date(2026, 9, 20))

        result = get_active_sites_with_week_schedule(company_a, REF)

        assert [s["name"] for s in result["sites"]] == ["C現場", "A現場", "B現場", "D現場"]

    def test_limit(self, company_a):
        for i in range(3):
            _site(company_a, f"S{i}", f"現場{i}")

        result = get_active_sites_with_week_schedule(company_a, REF, limit=2)

        assert len(result["sites"]) == 2

    def test_amount_is_left_out_unless_requested(self, company_a):
        _site(company_a, "S1", "現場", contract_amount=5000000)

        hidden = get_active_sites_with_week_schedule(company_a, REF)
        shown = get_active_sites_with_week_schedule(company_a, REF, include_amounts=True)

        assert "contract_amount" not in hidden["sites"][0]
        assert shown["sites"][0]["contract_amount"] == Decimal("5000000")

    def test_query_count_does_not_grow_with_sites(
        self, company_a, django_assert_num_queries,
    ):
        """現場・工程・マイルストーンの3クエリで済む（現場ごとに引かない）。"""
        for i in range(5):
            site = _site(company_a, f"S{i}", f"現場{i}")
            _phase(site, "工程", MONDAY, SUNDAY)
            _milestone(site, "期日", REF)

        with django_assert_num_queries(3):
            result = get_active_sites_with_week_schedule(company_a, REF)

        assert len(result["sites"]) == 5

    def test_reference_date_defaults_to_local_today(self, company_a):
        result = get_active_sites_with_week_schedule(company_a)

        assert result["week_start"] == week_bounds(timezone.localdate())[0]


# ---------------------------------------------------------------------------
# ホーム画面
# ---------------------------------------------------------------------------

class TestHomeView:
    def test_section_shows_this_weeks_schedule(self, plain_client, company_a):
        week_start, week_end = week_bounds(timezone.localdate())
        site = _site(company_a, "S1", "A社ビル新築")
        _phase(site, "幹線配管", week_start, week_end, progress=40)
        _milestone(site, "受電検査", week_end)

        res = plain_client.get(reverse("dashboard"))
        body = res.content.decode("utf-8")

        assert res.status_code == 200
        assert "<h2>施工中の現場と今週の工程</h2>" in body
        assert "A社ビル新築" in body
        assert "幹線配管" in body
        assert "40%" in body
        assert "受電検査" in body
        assert reverse("sites:detail", args=[site.pk]) in body
        assert reverse("schedules:detail", args=[site.pk]) in body

    def test_site_with_nothing_this_week_says_so(self, plain_client, company_a):
        _site(company_a, "S1", "予定なし現場")

        body = plain_client.get(reverse("dashboard")).content.decode("utf-8")

        assert "予定なし現場" in body
        assert "今週の工程・マイルストーンはありません" in body

    def test_no_sites_shows_empty_state(self, plain_client):
        body = plain_client.get(reverse("dashboard")).content.decode("utf-8")

        assert "施工中の現場はありません" in body

    def test_amount_is_hidden_for_a_plain_user(self, plain_client, company_a):
        _site(company_a, "S1", "A社ビル新築", contract_amount=5000000)

        res = plain_client.get(reverse("dashboard"))
        body = res.content.decode("utf-8")

        assert "受注金額" not in body
        assert "5,000,000" not in body
        assert "5000000" not in body
        assert res.context["can_view_costs"] is False
        assert all("contract_amount" not in s for s in res.context["site_schedules"])

    def test_amount_is_shown_for_a_user_with_cost_access(self, cost_client, company_a):
        _site(company_a, "S1", "A社ビル新築", contract_amount=5000000)

        res = cost_client.get(reverse("dashboard"))
        body = res.content.decode("utf-8")

        assert res.context["can_view_costs"] is True
        assert "受注金額" in body
        assert "5,000,000 円" in body

    def test_other_company_site_is_not_shown(self, plain_client, company_a, company_b):
        week_start, week_end = week_bounds(timezone.localdate())
        other = _site(company_b, "S1", "B社の現場")
        _phase(other, "B社の工程", week_start, week_end)
        _site(company_a, "S1", "A社の現場")

        body = plain_client.get(reverse("dashboard")).content.decode("utf-8")

        assert "A社の現場" in body
        assert "B社の現場" not in body
        assert "B社の工程" not in body

    def test_over_the_limit_points_to_the_site_list(self, plain_client, company_a):
        for i in range(11):
            _site(company_a, f"S{i:02d}", f"現場{i:02d}")

        res = plain_client.get(reverse("dashboard"))
        body = res.content.decode("utf-8")

        assert len(res.context["site_schedules"]) == 10
        assert res.context["more_sites"] == 1
        assert "ほか 1 件の施工中の現場があります" in body
        assert "すべて見る" in body

    def test_existing_widgets_are_kept(self, plain_client):
        body = plain_client.get(reverse("dashboard")).content.decode("utf-8")

        for label in ("本日の日報", "承認待ち日報", "作業員数"):
            assert label in body
