"""M5 テスト: 人材管理の越境テスト。"""

import pytest

from apps.core.tenant_context import set_current_company
from apps.workers.models import JobTitle, Position, Worker, WorkerEvaluation


@pytest.mark.django_db
class TestWorkerIsolation:
    def test_job_title_isolation(self, company_a, company_b):
        JobTitle.unscoped.create(company=company_a, name="電工")
        JobTitle.unscoped.create(company=company_b, name="内装工")

        set_current_company(company_a)
        assert JobTitle.objects.count() == 1
        assert JobTitle.objects.first().name == "電工"

        set_current_company(company_b)
        assert JobTitle.objects.count() == 1
        assert JobTitle.objects.first().name == "内装工"

        set_current_company(None)

    def test_position_isolation(self, company_a, company_b):
        Position.unscoped.create(company=company_a, name="職長", rank=1)
        Position.unscoped.create(company=company_b, name="主任", rank=2)

        set_current_company(company_a)
        assert Position.objects.count() == 1
        assert Position.objects.first().name == "職長"

        set_current_company(company_b)
        assert Position.objects.count() == 1
        assert Position.objects.first().name == "主任"

        set_current_company(None)

    def test_worker_isolation(self, company_a, company_b):
        Worker.unscoped.create(company=company_a, name="田中太郎", hourly_cost=3000)
        Worker.unscoped.create(company=company_b, name="佐藤花子", hourly_cost=2500)

        set_current_company(company_a)
        assert Worker.objects.count() == 1
        assert Worker.objects.first().name == "田中太郎"

        set_current_company(company_b)
        assert Worker.objects.count() == 1
        assert Worker.objects.first().name == "佐藤花子"

        set_current_company(None)

    def test_evaluation_isolation(self, company_a, company_b, user_a):
        w_a = Worker.unscoped.create(company=company_a, name="田中太郎", hourly_cost=3000)
        w_b = Worker.unscoped.create(company=company_b, name="佐藤花子", hourly_cost=2500)

        WorkerEvaluation.unscoped.create(
            company=company_a, worker=w_a, evaluated_by=user_a,
            period="2026-Q2", score=4, comment="Good",
        )
        WorkerEvaluation.unscoped.create(
            company=company_b, worker=w_b,
            period="2026-Q2", score=3,
        )

        set_current_company(company_a)
        assert WorkerEvaluation.objects.count() == 1
        assert WorkerEvaluation.objects.first().score == 4

        set_current_company(company_b)
        assert WorkerEvaluation.objects.count() == 1
        assert WorkerEvaluation.objects.first().score == 3

        set_current_company(None)

    def test_position_ordering(self, company_a):
        Position.unscoped.create(company=company_a, name="ジュニア", rank=5)
        Position.unscoped.create(company=company_a, name="職長", rank=1)
        Position.unscoped.create(company=company_a, name="シニア", rank=3)

        set_current_company(company_a)
        positions = list(Position.objects.values_list("name", flat=True))
        assert positions == ["職長", "シニア", "ジュニア"]

        set_current_company(None)
