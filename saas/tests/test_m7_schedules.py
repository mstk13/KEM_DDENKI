"""工期管理アプリ — テナント分離テスト。"""

import datetime

import pytest

from apps.core.tenant_context import set_current_company
from apps.schedules.models import Assignment, Milestone, Phase
from apps.schedules.services import get_comparison_gantt_data
from apps.sites.models import Site
from apps.workers.models import Worker


@pytest.mark.django_db
class TestPhaseIsolation:
    def test_phase_isolation(self, company_a, company_b, user_a):
        set_current_company(company_a)
        site = Site.objects.create(
            code="S001", name="現場A", company=company_a, created_by=user_a,
        )
        Phase.objects.create(
            site=site, name="基礎工事", company=company_a, created_by=user_a,
        )
        assert Phase.objects.count() == 1

        set_current_company(company_b)
        assert Phase.objects.count() == 0

        set_current_company(None)

    def test_phase_cascade_delete(self, company_a, user_a):
        set_current_company(company_a)
        site = Site.objects.create(
            code="S001", name="現場A", company=company_a, created_by=user_a,
        )
        Phase.objects.create(
            site=site, name="基礎工事", company=company_a,
        )
        site.delete()
        assert Phase.unscoped.count() == 0

        set_current_company(None)


@pytest.mark.django_db
class TestMilestoneIsolation:
    def test_milestone_isolation(self, company_a, company_b, user_a):
        set_current_company(company_a)
        site = Site.objects.create(
            code="S001", name="現場A", company=company_a, created_by=user_a,
        )
        Milestone.objects.create(
            site=site, name="中間検査", company=company_a, created_by=user_a,
        )
        assert Milestone.objects.count() == 1

        set_current_company(company_b)
        assert Milestone.objects.count() == 0

        set_current_company(None)

    def test_milestone_cascade_delete(self, company_a, user_a):
        set_current_company(company_a)
        site = Site.objects.create(
            code="S001", name="現場A", company=company_a, created_by=user_a,
        )
        Milestone.objects.create(
            site=site, name="中間検査", company=company_a,
        )
        site.delete()
        assert Milestone.unscoped.count() == 0

        set_current_company(None)


@pytest.mark.django_db
class TestAssignmentIsolation:
    def test_assignment_isolation(self, company_a, company_b, user_a):
        set_current_company(company_a)
        site = Site.objects.create(
            code="S001", name="現場A", company=company_a, created_by=user_a,
        )
        worker = Worker.objects.create(
            name="田中太郎", company=company_a, created_by=user_a,
        )
        Assignment.objects.create(
            worker=worker,
            site=site,
            start_date=datetime.date(2026, 8, 1),
            company=company_a,
            created_by=user_a,
        )
        assert Assignment.objects.count() == 1

        set_current_company(company_b)
        assert Assignment.objects.count() == 0

        set_current_company(None)

    def test_assignment_cascade_delete_site(self, company_a, user_a):
        set_current_company(company_a)
        site = Site.objects.create(
            code="S001", name="現場A", company=company_a, created_by=user_a,
        )
        worker = Worker.objects.create(
            name="田中太郎", company=company_a,
        )
        Assignment.objects.create(
            worker=worker,
            site=site,
            start_date=datetime.date(2026, 8, 1),
            company=company_a,
        )
        site.delete()
        assert Assignment.unscoped.count() == 0

        set_current_company(None)

    def test_assignment_cascade_delete_worker(self, company_a, user_a):
        set_current_company(company_a)
        site = Site.objects.create(
            code="S001", name="現場A", company=company_a, created_by=user_a,
        )
        worker = Worker.objects.create(
            name="田中太郎", company=company_a,
        )
        Assignment.objects.create(
            worker=worker,
            site=site,
            start_date=datetime.date(2026, 8, 1),
            company=company_a,
        )
        worker.delete()
        assert Assignment.unscoped.count() == 0

        set_current_company(None)


@pytest.mark.django_db
class TestComparisonGantt:
    """工期比較ガントのデータ生成。"""

    def _site(self, company, user, code, name, start, end, status="in_progress"):
        return Site.objects.create(
            code=code,
            name=name,
            company=company,
            created_by=user,
            status=status,
            start_date=start,
            end_date=end,
        )

    def test_site_mode_lists_one_bar_per_site(self, company_a, user_a):
        set_current_company(company_a)
        self._site(
            company_a, user_a, "S001", "現場A",
            datetime.date(2026, 8, 1), datetime.date(2026, 8, 31),
        )
        site_b = self._site(
            company_a, user_a, "S002", "現場B",
            datetime.date(2026, 9, 1), datetime.date(2026, 9, 30),
        )
        Phase.objects.create(
            site=site_b, name="配線工事", company=company_a,
            start_date=datetime.date(2026, 9, 1),
            end_date=datetime.date(2026, 9, 10),
        )

        data = get_comparison_gantt_data(company_a, mode="site")

        assert [t["name"] for t in data["tasks"]] == ["現場A", "現場B"]
        # 現場単位では工程バーを出さない
        assert all(t["id"].startswith("site-") for t in data["tasks"])
        # 工期は両端を含めて数える
        assert [x["days"] for x in data["legend"]] == [31, 30]

        set_current_company(None)

    def test_phase_mode_prefixes_site_name(self, company_a, user_a):
        set_current_company(company_a)
        site = self._site(
            company_a, user_a, "S001", "現場A",
            datetime.date(2026, 8, 1), datetime.date(2026, 8, 31),
        )
        Phase.objects.create(
            site=site, name="配線工事", company=company_a,
            start_date=datetime.date(2026, 8, 1),
            end_date=datetime.date(2026, 8, 10),
        )
        # 日付未設定の工程はガントに出せない
        Phase.objects.create(site=site, name="未定工事", company=company_a)

        data = get_comparison_gantt_data(company_a, mode="phase")

        names = [t["name"] for t in data["tasks"]]
        assert names == ["現場A", "現場A / 配線工事"]

        set_current_company(None)

    def test_same_site_phases_share_color(self, company_a, user_a):
        set_current_company(company_a)
        site = self._site(
            company_a, user_a, "S001", "現場A",
            datetime.date(2026, 8, 1), datetime.date(2026, 8, 31),
        )
        for name in ("配線工事", "内装工事"):
            Phase.objects.create(
                site=site, name=name, company=company_a,
                start_date=datetime.date(2026, 8, 1),
                end_date=datetime.date(2026, 8, 10),
            )

        data = get_comparison_gantt_data(company_a, mode="phase")

        colors = {t["custom_class"].split()[0] for t in data["tasks"]}
        assert colors == {"gantt-site-0"}

        set_current_company(None)

    def test_span_falls_back_to_phase_dates(self, company_a, user_a):
        """現場に工期が未設定でも、工程の日付から工期を補って比較できる。"""
        set_current_company(company_a)
        site = self._site(company_a, user_a, "S001", "現場A", None, None)
        Phase.objects.create(
            site=site, name="配線工事", company=company_a,
            start_date=datetime.date(2026, 8, 5),
            end_date=datetime.date(2026, 8, 10),
        )
        Phase.objects.create(
            site=site, name="内装工事", company=company_a,
            start_date=datetime.date(2026, 8, 8),
            end_date=datetime.date(2026, 8, 20),
        )

        data = get_comparison_gantt_data(company_a, mode="site")

        assert data["tasks"][0]["start"] == "2026-08-05"
        assert data["tasks"][0]["end"] == "2026-08-20"

        set_current_company(None)

    def test_site_ids_filter(self, company_a, user_a):
        set_current_company(company_a)
        site_a = self._site(
            company_a, user_a, "S001", "現場A",
            datetime.date(2026, 8, 1), datetime.date(2026, 8, 31),
        )
        self._site(
            company_a, user_a, "S002", "現場B",
            datetime.date(2026, 9, 1), datetime.date(2026, 9, 30),
        )

        data = get_comparison_gantt_data(company_a, site_ids=[str(site_a.pk)])

        assert [t["name"] for t in data["tasks"]] == ["現場A"]

        set_current_company(None)

    def test_selected_sites_ignore_status(self, company_a, user_a):
        """明示的に選ばれた現場は、完工していても比較対象に含める。"""
        set_current_company(company_a)
        done = self._site(
            company_a, user_a, "S001", "完工現場",
            datetime.date(2026, 8, 1), datetime.date(2026, 8, 31),
            status="completed",
        )

        default_data = get_comparison_gantt_data(company_a)
        picked_data = get_comparison_gantt_data(company_a, site_ids=[done.pk])

        assert default_data["tasks"] == []
        assert [t["name"] for t in picked_data["tasks"]] == ["完工現場"]

        set_current_company(None)

    def test_does_not_leak_across_tenants(self, company_a, company_b, user_a, user_b):
        set_current_company(company_a)
        self._site(
            company_a, user_a, "S001", "A社現場",
            datetime.date(2026, 8, 1), datetime.date(2026, 8, 31),
        )
        set_current_company(company_b)
        self._site(
            company_b, user_b, "S001", "B社現場",
            datetime.date(2026, 8, 1), datetime.date(2026, 8, 31),
        )
        set_current_company(None)

        data = get_comparison_gantt_data(company_a)

        assert [t["name"] for t in data["tasks"]] == ["A社現場"]
