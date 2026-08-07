"""AI分析基盤のモデル。

全AI呼び出しのログとユーザーフィードバックを記録する。
将来のファインチューニング用データセットとしても活用する。
"""

from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class AILog(TenantModel):
    """AI呼び出しログ。入出力・モデル・コストを記録する。

    CostTransaction と同様に追記のみ（不変）。
    将来のファインチューニング用データセットの基盤となる。
    """

    class TaskType(models.TextChoices):
        COST_FORECAST = "cost_forecast", "コスト予測"
        COST_OPTIMIZATION = "cost_optimization", "コスト最適化提案"
        SCHEDULE_SUGGEST = "schedule_suggest", "工程提案"
        SCHEDULE_RISK = "schedule_risk", "工程リスク分析"
        GENERAL_ANALYSIS = "general_analysis", "汎用分析"

    class ModelType(models.TextChoices):
        CLAUDE_HAIKU = "claude-haiku", "Claude Haiku"
        CLAUDE_SONNET = "claude-sonnet", "Claude Sonnet"
        LGBM = "lgbm", "LightGBM"
        CUSTOM = "custom", "カスタムモデル"

    class Status(models.TextChoices):
        SUCCESS = "success", "成功"
        ERROR = "error", "エラー"
        TIMEOUT = "timeout", "タイムアウト"

    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_logs",
        verbose_name="対象現場",
    )
    task_type = models.CharField(
        "タスク種別",
        max_length=30,
        choices=TaskType.choices,
    )
    model_used = models.CharField(
        "使用モデル",
        max_length=50,
        choices=ModelType.choices,
    )
    model_version = models.CharField(
        "モデルバージョン",
        max_length=100,
        blank=True,
        help_text="例: claude-haiku-4-5-20251001, lgbm_cost_v3",
    )
    input_data = models.JSONField(
        "入力データ",
        help_text="構造化された入力データ（プロンプト構築前）",
    )
    prompt = models.TextField(
        "プロンプト",
        blank=True,
        help_text="LLMに送信した実際のプロンプト（ML系は空）",
    )
    response = models.TextField(
        "レスポンス",
        help_text="AIの応答（生テキスト or JSON文字列）",
    )
    response_parsed = models.JSONField(
        "パース済みレスポンス",
        null=True,
        blank=True,
        help_text="構造化された出力（パース成功時）",
    )
    status = models.CharField(
        "ステータス",
        max_length=10,
        choices=Status.choices,
        default=Status.SUCCESS,
    )
    error_message = models.TextField(
        "エラーメッセージ",
        blank=True,
    )
    latency_ms = models.IntegerField(
        "レイテンシ(ms)",
        help_text="推論にかかった時間",
    )
    input_tokens = models.IntegerField(
        "入力トークン数",
        null=True,
        blank=True,
    )
    output_tokens = models.IntegerField(
        "出力トークン数",
        null=True,
        blank=True,
    )
    cost_usd = models.DecimalField(
        "API費用(USD)",
        max_digits=8,
        decimal_places=6,
        null=True,
        blank=True,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_logs",
        verbose_name="実行ユーザー",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "AI実行ログ"
        verbose_name_plural = "AI実行ログ"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["company", "task_type", "created_at"],
                name="idx_ailog_task_date",
            ),
            models.Index(
                fields=["company", "site", "task_type"],
                name="idx_ailog_site_task",
            ),
        ]

    def __str__(self):
        return (
            f"{self.created_at:%Y-%m-%d %H:%M} "
            f"{self.get_task_type_display()} "
            f"({self.get_model_used_display()})"
        )


class AIFeedback(TenantModel):
    """AI出力に対するユーザーフィードバック。

    学習データの品質を決定する重要なテーブル。
    rating が高いログを将来のファインチューニングに優先的に使用する。
    """

    ai_log = models.OneToOneField(
        AILog,
        on_delete=models.CASCADE,
        related_name="feedback",
        verbose_name="対象ログ",
    )
    rating = models.SmallIntegerField(
        "評価",
        help_text="1=悪い 2=やや悪い 3=普通 4=良い 5=とても良い",
    )
    is_adopted = models.BooleanField(
        "提案を採用したか",
        default=False,
        help_text="AIの提案を実際に業務に反映したか",
    )
    comment = models.TextField(
        "コメント",
        blank=True,
        help_text="どこが良かった/悪かったか",
    )
    rated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_feedbacks",
        verbose_name="評価者",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "AIフィードバック"
        verbose_name_plural = "AIフィードバック"

    def __str__(self):
        return f"{'★' * self.rating} {self.ai_log}"
