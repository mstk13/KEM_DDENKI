"""入札案件管理アプリ — テナント分離テスト。"""

import datetime
from decimal import Decimal

import pytest

from apps.bids.models import BidCost, BidProject, Qualification
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
