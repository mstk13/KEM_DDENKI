"""M3 テスト: 原価・予実管理の越境テスト + 自動仕訳。"""

from decimal import Decimal

import pytest

from apps.core.tenant_context import set_current_company
from apps.costs.models import BudgetItem, CostTransaction
from apps.costs.services import create_labor_cost_from_report, create_reversal
from apps.masters.models import CostCategory, WorkType
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import Worker


@pytest.fixture
def cost_categories(db):
    """建設業4原価区分。"""
    cats = {}
    for code, name, order in [
        ("material", "材料費", 1),
        ("labor", "労務費", 2),
        ("outsourcing", "外注費", 3),
        ("expense", "経費", 4),
    ]:
        cats[code], _ = CostCategory.objects.get_or_create(
            code=code, defaults={"name": name, "display_order": order},
        )
    return cats


@pytest.fixture
def setup_a(company_a, cost_categories):
    wt = WorkType.unscoped.create(company=company_a, code="E01", name="電気幹線")
    site = Site.unscoped.create(
        company=company_a, code="S001", name="A社ビル",
        contract_amount=5000000, status=Site.Status.IN_PROGRESS,
    )
    worker = Worker.unscoped.create(
        company=company_a, name="田中太郎", hourly_cost=3000,
    )
    return {"wt": wt, "site": site, "worker": worker, "cats": cost_categories}


# ---------------------------------------------------------------------------
# 越境テスト
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCostIsolation:
    def test_budget_item_isolation(self, company_a, company_b, cost_categories):
        wt_a = WorkType.unscoped.create(company=company_a, code="E01", name="電気")
        wt_b = WorkType.unscoped.create(company=company_b, code="N01", name="内装")
        site_a = Site.unscoped.create(company=company_a, code="S01", name="A現場")
        site_b = Site.unscoped.create(company=company_b, code="S01", name="B現場")

        BudgetItem.unscoped.create(
            company=company_a, site=site_a, work_type=wt_a,
            cost_category=cost_categories["labor"], name="労務費",
            amount=1000000,
        )
        BudgetItem.unscoped.create(
            company=company_b, site=site_b, work_type=wt_b,
            cost_category=cost_categories["labor"], name="労務費",
            amount=800000,
        )

        set_current_company(company_a)
        assert BudgetItem.objects.count() == 1
        assert BudgetItem.objects.first().amount == 1000000

        set_current_company(company_b)
        assert BudgetItem.objects.count() == 1
        assert BudgetItem.objects.first().amount == 800000

        set_current_company(None)

    def test_cost_transaction_isolation(self, company_a, company_b, cost_categories):
        wt_a = WorkType.unscoped.create(company=company_a, code="E01", name="電気")
        wt_b = WorkType.unscoped.create(company=company_b, code="N01", name="内装")
        site_a = Site.unscoped.create(company=company_a, code="S01", name="A現場")
        site_b = Site.unscoped.create(company=company_b, code="S01", name="B現場")

        CostTransaction.unscoped.create(
            company=company_a, site=site_a, work_type=wt_a,
            cost_category=cost_categories["labor"], amount=24000,
            transaction_date="2026-08-01",
            source_type=CostTransaction.SourceType.DAILY_REPORT,
        )
        CostTransaction.unscoped.create(
            company=company_b, site=site_b, work_type=wt_b,
            cost_category=cost_categories["labor"], amount=20000,
            transaction_date="2026-08-01",
            source_type=CostTransaction.SourceType.DAILY_REPORT,
        )

        set_current_company(company_a)
        assert CostTransaction.objects.count() == 1
        assert CostTransaction.objects.first().amount == 24000

        set_current_company(company_b)
        assert CostTransaction.objects.count() == 1
        assert CostTransaction.objects.first().amount == 20000

        set_current_company(None)


# ---------------------------------------------------------------------------
# 自動仕訳テスト
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAutoJournal:
    def test_labor_cost_from_daily_report(self, setup_a):
        """日報承認時に労務費CostTransactionが正しく生成されることを検証。"""
        d = setup_a
        report = DailyReport.unscoped.create(
            company=d["worker"].company,
            site=d["site"],
            worker=d["worker"],
            report_date="2026-08-01",
            work_type=d["wt"],
            work_hours=Decimal("8.00"),
            status=DailyReport.Status.APPROVED,
        )

        tx = create_labor_cost_from_report(report)

        assert tx.amount == Decimal("24000")  # 8h × 3000円
        assert tx.cost_category.code == "labor"
        assert tx.source_type == CostTransaction.SourceType.DAILY_REPORT
        assert tx.source_id == report.pk
        assert tx.manhours == Decimal("8.00")
        assert tx.site == d["site"]
        assert tx.work_type == d["wt"]

    def test_reversal_creates_negative(self, setup_a):
        """逆仕訳が正しくマイナス金額で生成されることを検証。"""
        d = setup_a
        original = CostTransaction.unscoped.create(
            company=d["site"].company,
            site=d["site"],
            work_type=d["wt"],
            cost_category=d["cats"]["labor"],
            amount=Decimal("24000"),
            transaction_date="2026-08-01",
            source_type=CostTransaction.SourceType.DAILY_REPORT,
            source_id=1,
            manhours=Decimal("8.00"),
        )

        reversal = create_reversal(original)

        assert reversal.amount == Decimal("-24000")
        assert reversal.manhours == Decimal("-8.00")
        assert reversal.source_type == CostTransaction.SourceType.REVERSAL
        assert reversal.source_id == original.pk

    def test_gross_profit_calculation(self, setup_a):
        """粗利 = 受注金額 - Σ CostTransaction.amount の検証。"""
        d = setup_a
        site = d["site"]
        labor = d["cats"]["labor"]
        material = d["cats"]["material"]

        CostTransaction.unscoped.create(
            company=site.company, site=site, work_type=d["wt"],
            cost_category=labor, amount=Decimal("500000"),
            transaction_date="2026-08-01",
            source_type=CostTransaction.SourceType.DAILY_REPORT,
        )
        CostTransaction.unscoped.create(
            company=site.company, site=site, work_type=d["wt"],
            cost_category=material, amount=Decimal("300000"),
            transaction_date="2026-08-01",
            source_type=CostTransaction.SourceType.PO_ITEM,
        )

        from django.db.models import Sum

        set_current_company(site.company)
        total_cost = CostTransaction.objects.filter(site=site).aggregate(
            total=Sum("amount")
        )["total"]
        gross_profit = site.contract_amount - total_cost

        assert total_cost == Decimal("800000")
        assert gross_profit == Decimal("4200000")  # 500万 - 80万

        set_current_company(None)
