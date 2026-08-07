from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class DevProject(TenantModel):
    """開発プロジェクト。"""

    class Status(models.TextChoices):
        PLANNING = "planning", "計画中"
        IN_PROGRESS = "in_progress", "進行中"
        COMPLETED = "completed", "完了"
        SUSPENDED = "suspended", "中断"

    name = models.CharField("プロジェクト名", max_length=200)
    description = models.TextField("説明", blank=True)
    status = models.CharField(
        "ステータス",
        max_length=20,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dev_projects",
        verbose_name="責任者",
    )
    start_date = models.DateField("開始日", null=True, blank=True)
    due_date = models.DateField("期限", null=True, blank=True)
    discord_webhook_url = models.URLField(
        "Discord Webhook URL",
        max_length=500,
        blank=True,
        help_text="設定するとタスク割当時にDiscordへ通知されます",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "開発プロジェクト"
        verbose_name_plural = "開発プロジェクト"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class DevTask(TenantModel):
    """開発タスク（チケット）。"""

    class Status(models.TextChoices):
        OPEN = "open", "未着手"
        IN_PROGRESS = "in_progress", "作業中"
        REVIEW = "review", "レビュー中"
        DONE = "done", "完了"
        CLOSED = "closed", "クローズ"

    class Priority(models.TextChoices):
        LOW = "low", "低"
        MEDIUM = "medium", "中"
        HIGH = "high", "高"
        CRITICAL = "critical", "緊急"

    class Category(models.TextChoices):
        FEATURE = "feature", "機能追加"
        BUG = "bug", "バグ修正"
        REFACTOR = "refactor", "リファクタ"
        DOCS = "docs", "ドキュメント"
        TEST = "test", "テスト"
        INFRA = "infra", "インフラ"
        OTHER = "other", "その他"

    project = models.ForeignKey(
        DevProject,
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name="プロジェクト",
    )
    title = models.CharField("タイトル", max_length=300)
    description = models.TextField("詳細", blank=True)
    status = models.CharField(
        "ステータス",
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    priority = models.CharField(
        "優先度",
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    category = models.CharField(
        "カテゴリ",
        max_length=10,
        choices=Category.choices,
        default=Category.FEATURE,
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dev_tasks",
        verbose_name="担当者",
    )
    due_date = models.DateField("期限", null=True, blank=True)
    estimate_hours = models.DecimalField(
        "見積(h)", max_digits=6, decimal_places=1, null=True, blank=True,
    )
    actual_hours = models.DecimalField(
        "実績(h)", max_digits=6, decimal_places=1, null=True, blank=True,
    )
    sort_order = models.IntegerField("表示順", default=0)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "開発タスク"
        verbose_name_plural = "開発タスク"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"#{self.pk} {self.title}"


class DevComment(TenantModel):
    """タスクへのコメント。"""

    task = models.ForeignKey(
        DevTask,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name="タスク",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dev_comments",
        verbose_name="投稿者",
    )
    body = models.TextField("本文")

    history = HistoricalRecords()

    class Meta:
        verbose_name = "コメント"
        verbose_name_plural = "コメント"
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment #{self.pk} on Task #{self.task_id}"


class Meyasubako(TenantModel):
    """目安箱（ユーザーからのフィードバック）。"""

    class Kind(models.TextChoices):
        BUG = "bug", "不具合"
        USABILITY = "usability", "使いにくい"
        FEATURE = "feature", "機能追加"
        OTHER = "other", "その他"

    class Urgency(models.TextChoices):
        URGENT = "urgent", "すぐ対応してほしい"
        NOT_URGENT = "not_urgent", "急がない"

    MODULE_CHOICES = [
        ("dashboard", "ダッシュボード"),
        ("sites", "現場管理"),
        ("reports", "日報管理"),
        ("costs", "原価管理"),
        ("materials", "材料管理"),
        ("bids", "入札管理"),
        ("sales", "営業管理"),
        ("schedules", "工期管理"),
        ("workers", "人材管理"),
        ("devkanri", "開発管理"),
        ("masters", "取引先管理"),
        ("notifications", "通知"),
        ("permissions", "権限管理"),
        ("other", "その他"),
    ]

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="meyasubako_posts",
        verbose_name="報告者",
    )
    reporter_name = models.CharField("報告者名", max_length=100)
    kind = models.CharField(
        "種別",
        max_length=20,
        choices=Kind.choices,
    )
    module = models.CharField(
        "対象モジュール",
        max_length=30,
        choices=MODULE_CHOICES,
    )
    title = models.CharField("タイトル", max_length=200)
    problem = models.TextField("困っていること")
    wish = models.TextField("こうなってほしい", blank=True)
    urgency = models.CharField(
        "緊急度",
        max_length=20,
        choices=Urgency.choices,
        default=Urgency.NOT_URGENT,
    )
    screenshot = models.ImageField(
        "スクリーンショット",
        upload_to="meyasubako/",
        blank=True,
    )
    resolved = models.BooleanField("対応済み", default=False)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "目安箱"
        verbose_name_plural = "目安箱"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_kind_display()}] {self.title}"
