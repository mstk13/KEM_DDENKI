"""工期管理アプリ — テナント分離テスト。"""

import datetime

import pytest

from apps.core.tenant_context import set_current_company
from apps.schedules.models import Assignment, Milestone, Phase
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
