"""AI分析基盤テスト: モデル・越境テスト・データ収集・プロンプトビルダー。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.ai.models import AIFeedback, AILog
from apps.ai.services.data_collector import (
    collect_schedule_data,
    collect_site_cost_features,
    collect_site_summary,
    find_similar_completed_sites,
)
from apps.ai.services.prompt_builder import (
    build_cost_optimization_prompt,
    build_schedule_suggestion_prompt,
)
from apps.core.tenant_context import set_current_company
from apps.costs.models import BudgetItem, CostTransaction
from apps.masters.models import CostCategory, WorkType
from apps.reports.models import DailyReport
from apps.schedules.models import Phase, PhaseTemplate, PhaseTemplateItem
from apps.sites.models import Process, Site
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
def site_with_data(company_a, user_a, cost_categories):
    """原価・日報・工程データ付きの現場。"""
    wt = WorkType.unscoped.create(company=company_a, code="E01", name="電気幹線")
    today = date.today()

    site = Site.unscoped.create(
        company=company_a,
        code="S001",
        name="テスト現場A",
        contract_amount=Decimal("10000000"),
        status=Site.Status.IN_PROGRESS,
        start_date=today - timedelta(days=60),
        end_date=today + timedelta(days=60),
    )
    site.work_types.add(wt)

    # 予算
    BudgetItem.unscoped.create(
        company=company_a,
        site=site,
        work_type=wt,
        cost_category=cost_categories["labor"],
        name="労務費",
        amount=Decimal("3000000"),
    )
    BudgetItem.unscoped.create(
        company=company_a,
        site=site,
        work_type=wt,
        cost_category=cost_categories["material"],
        name="材料費",
        amount=Decimal("5000000"),
    )

    # 実績
    CostTransaction.unscoped.create(
        company=company_a,
        site=site,
        work_type=wt,
        cost_category=cost_categories["labor"],
        amount=Decimal("1500000"),
        transaction_date=today - timedelta(days=30),
        source_type=CostTransaction.SourceType.DAILY_REPORT,
    )
    CostTransaction.unscoped.create(
        company=company_a,
        site=site,
        work_type=wt,
        cost_category=cost_categories["material"],
        amount=Decimal("2000000"),
        transaction_date=today - timedelta(days=10),
        source_type=CostTransaction.SourceType.PO_ITEM,
    )

    # 工程
    Process.unscoped.create(
        company=company_a,
        site=site,
        work_type=wt,
        name="幹線工事",
        planned_start=today - timedelta(days=60),
        planned_end=today - timedelta(days=20),
        actual_start=today - timedelta(days=60),
        actual_end=today - timedelta(days=15),
        status=Process.Status.COMPLETED,
    )
    Process.unscoped.create(
        company=company_a,
        site=site,
        work_type=wt,
        name="仕上げ工事",
        planned_start=today - timedelta(days=20),
        planned_end=today + timedelta(days=30),
        actual_start=today - timedelta(days=18),
        status=Process.Status.IN_PROGRESS,
    )

    # 日報
    worker = Worker.unscoped.create(
        company=company_a, name="テスト太郎", hourly_cost=Decimal("3000"),
    )
    DailyReport.unscoped.create(
        company=company_a,
        site=site,
        worker=worker,
        report_date=today - timedelta(days=5),
        work_type=wt,
        work_hours=Decimal("8.00"),
        overtime_hours=Decimal("1.50"),
        status=DailyReport.Status.APPROVED,
        created_by=user_a,
    )

    return {
        "site": site,
        "wt": wt,
        "worker": worker,
        "cats": cost_categories,
    }


@pytest.fixture
def completed_site(company_a, cost_categories):
    """完工済みの現場（類似現場検索用）。"""
    wt = WorkType.unscoped.filter(company=company_a, code="E01").first()
    if not wt:
        wt = WorkType.unscoped.create(company=company_a, code="E01", name="電気幹線")
    today = date.today()

    site = Site.unscoped.create(
        company=company_a,
        code="S002",
        name="完工済み現場",
        contract_amount=Decimal("12000000"),
        status=Site.Status.COMPLETED,
        start_date=today - timedelta(days=180),
        end_date=today - timedelta(days=30),
    )
    site.work_types.add(wt)

    BudgetItem.unscoped.create(
        company=company_a,
        site=site,
        work_type=wt,
        cost_category=cost_categories["labor"],
        name="労務費",
        amount=Decimal("4000000"),
    )
    CostTransaction.unscoped.create(
        company=company_a,
        site=site,
        work_type=wt,
        cost_category=cost_categories["labor"],
        amount=Decimal("3800000"),
        transaction_date=today - timedelta(days=60),
        source_type=CostTransaction.SourceType.DAILY_REPORT,
    )

    Process.unscoped.create(
        company=company_a,
        site=site,
        work_type=wt,
        name="幹線工事",
        planned_start=today - timedelta(days=180),
        planned_end=today - timedelta(days=90),
        actual_start=today - timedelta(days=180),
        actual_end=today - timedelta(days=85),
        status=Process.Status.COMPLETED,
    )

    return site


# ---------------------------------------------------------------------------
# AILog / AIFeedback 越境テスト
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAILogIsolation:
    def test_ailog_tenant_isolation(self, company_a, company_b, user_a, user_b):
        """AILogがテナント分離されていることを確認。"""
        log_a = AILog.unscoped.create(
            company=company_a,
            task_type=AILog.TaskType.COST_FORECAST,
            model_used=AILog.ModelType.CLAUDE_HAIKU,
            input_data={"test": "a"},
            prompt="テストA",
            response="結果A",
            status=AILog.Status.SUCCESS,
            latency_ms=100,
            requested_by=user_a,
        )
        AILog.unscoped.create(
            company=company_b,
            task_type=AILog.TaskType.SCHEDULE_SUGGEST,
            model_used=AILog.ModelType.CLAUDE_SONNET,
            input_data={"test": "b"},
            prompt="テストB",
            response="結果B",
            status=AILog.Status.SUCCESS,
            latency_ms=200,
            requested_by=user_b,
        )

        set_current_company(company_a)
        assert AILog.objects.count() == 1
        assert AILog.objects.first().prompt == "テストA"

        set_current_company(company_b)
        assert AILog.objects.count() == 1
        assert AILog.objects.first().prompt == "テストB"

        set_current_company(None)

    def test_aifeedback_creation(self, company_a, user_a):
        """AIFeedbackの作成と紐付けを確認。"""
        log = AILog.unscoped.create(
            company=company_a,
            task_type=AILog.TaskType.COST_OPTIMIZATION,
            model_used=AILog.ModelType.CLAUDE_HAIKU,
            input_data={"site": "テスト"},
            prompt="最適化テスト",
            response='{"risk_level": "low"}',
            status=AILog.Status.SUCCESS,
            latency_ms=500,
            requested_by=user_a,
        )
        feedback = AIFeedback.unscoped.create(
            company=company_a,
            ai_log=log,
            rating=4,
            is_adopted=True,
            comment="提案が参考になった",
            rated_by=user_a,
        )

        assert feedback.ai_log == log
        assert log.feedback == feedback
        assert feedback.rating == 4
        assert feedback.is_adopted is True


# ---------------------------------------------------------------------------
# データ収集テスト
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDataCollector:
    def test_collect_site_cost_features(self, site_with_data):
        """コスト特徴量が正しく収集されることを確認。"""
        site = site_with_data["site"]
        features = collect_site_cost_features(site)

        assert features["contract_amount"] == 10_000_000.0
        assert features["budget_total"] == 8_000_000.0  # 3M + 5M
        assert features["cost_total"] == 3_500_000.0  # 1.5M + 2M
        assert features["duration_days"] == 120
        assert features["worker_count"] == 1
        assert features["process_count"] == 2
        assert 0 < features["consumption_ratio"] < 1
        assert 0 < features["elapsed_ratio"] <= 1

    def test_collect_site_summary(self, site_with_data):
        """現場サマリが必要なキーを全て含むことを確認。"""
        site = site_with_data["site"]
        summary = collect_site_summary(site)

        assert summary["site"]["name"] == "テスト現場A"
        assert summary["site"]["contract_amount"] == 10_000_000.0
        assert len(summary["budget_vs_actual"]) >= 2
        assert "cost_features" in summary
        assert "processes" in summary

    def test_find_similar_completed_sites(self, site_with_data, completed_site):
        """類似完工済み現場が検索されることを確認。"""
        site = site_with_data["site"]
        similar = find_similar_completed_sites(site, limit=5)

        assert len(similar) >= 1
        assert similar[0]["site_name"] == "完工済み現場"
        assert similar[0]["similarity_score"] > 0

    def test_collect_schedule_data(self, site_with_data):
        """工程データが正しく収集されることを確認。"""
        site = site_with_data["site"]
        data = collect_schedule_data(site)

        assert data["site"]["name"] == "テスト現場A"
        assert "current_phases" in data
        assert "templates" in data
        assert "similar_site_processes" in data


# ---------------------------------------------------------------------------
# プロンプトビルダーテスト
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPromptBuilder:
    def test_build_cost_optimization_prompt(self, site_with_data, completed_site):
        """コスト最適化プロンプトが正しく構築されることを確認。"""
        site = site_with_data["site"]
        summary = collect_site_summary(site)
        similar = find_similar_completed_sites(site)

        prompt = build_cost_optimization_prompt(summary, similar)

        assert "テスト現場A" in prompt
        assert "10,000,000" in prompt
        assert "予算vs実績" in prompt
        assert "JSON" in prompt
        assert "risk_level" in prompt

    def test_build_cost_optimization_prompt_with_prediction(
        self, site_with_data, completed_site,
    ):
        """ML予測結果付きのプロンプトが正しく構築されることを確認。"""
        site = site_with_data["site"]
        summary = collect_site_summary(site)
        similar = find_similar_completed_sites(site)
        prediction = {
            "predicted_final_cost": 9_200_000,
            "overrun_probability": 0.35,
        }

        prompt = build_cost_optimization_prompt(summary, similar, prediction)

        assert "9,200,000" in prompt
        assert "35.0%" in prompt

    def test_build_schedule_suggestion_prompt(self, site_with_data):
        """工程提案プロンプトが正しく構築されることを確認。"""
        site = site_with_data["site"]

        # テンプレートを作成
        tmpl = PhaseTemplate.unscoped.create(
            company=site_with_data["site"].company,
            name="電気工事標準",
            description="標準的な電気工事の工程",
        )
        PhaseTemplateItem.unscoped.create(
            company=site_with_data["site"].company,
            template=tmpl,
            name="幹線工事",
            offset_days_start=0,
            offset_days_end=30,
        )

        data = collect_schedule_data(site)
        prompt = build_schedule_suggestion_prompt(data)

        assert "テスト現場A" in prompt
        assert "電気幹線" in prompt
        assert "電気工事標準" in prompt
        assert "JSON" in prompt
        assert "phases" in prompt
