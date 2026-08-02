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
