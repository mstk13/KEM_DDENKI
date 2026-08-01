from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class JobTitle(TenantModel):
    """職種区分。テナントごとに定義。

    例: 電工 / 配管工 / CADオペ / 事務
    """

    name = models.CharField("職種名", max_length=100)
    is_active = models.BooleanField("有効", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "職種"
        verbose_name_plural = "職種"
        unique_together = [("company", "name")]

    def __str__(self):
        return self.name


class Position(TenantModel):
    """役職。テナントごとに定義。rank は序列（昇順）。

    例: 職長(1) / 主任(2) / シニア(3) / ミドル(4) / ジュニア(5)
    評価項目の出し分け等に利用する。
    """

    name = models.CharField("役職名", max_length=100)
    rank = models.IntegerField("序列", default=0, help_text="昇順。数字が小さいほど上位")
    is_active = models.BooleanField("有効", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "役職"
        verbose_name_plural = "役職"
        unique_together = [("company", "name")]
        ordering = ["rank"]

    def __str__(self):
        return self.name


class Worker(TenantModel):
    """作業員。日報・原価計算の主体。

    hourly_cost は労務費原価の算出単価。履歴が必要なため simple-history 付き。
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="worker_profile",
        verbose_name="ユーザーアカウント",
    )
    name = models.CharField("氏名", max_length=100)
    job_title = models.ForeignKey(
        JobTitle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workers",
        verbose_name="職種",
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workers",
        verbose_name="役職",
    )
    skill_tags = models.JSONField(
        "スキルタグ",
        default=list,
        blank=True,
    )
    hourly_cost = models.DecimalField(
        "時間単価",
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="労務費CostTransactionの算出単価",
    )
    hire_date = models.DateField("入社日", null=True, blank=True)
    is_active = models.BooleanField("有効", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "作業員"
        verbose_name_plural = "作業員"

    @property
    def monthly_salary(self):
        """月収目安（8h × 21日）。"""
        return self.hourly_cost * 168

    def __str__(self):
        return self.name


class WorkerEvaluation(TenantModel):
    """人材評価。日報実績と連動。"""

    worker = models.ForeignKey(
        Worker,
        on_delete=models.CASCADE,
        related_name="evaluations",
        verbose_name="作業員",
    )
    evaluated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="evaluations_given",
        verbose_name="評価者",
    )
    period = models.CharField("評価期間", max_length=50, help_text="例: 2026-Q1")
    score = models.IntegerField("評点", null=True, blank=True)
    comment = models.TextField("コメント", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "人材評価"
        verbose_name_plural = "人材評価"

    def __str__(self):
        return f"{self.worker} - {self.period}"
