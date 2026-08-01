from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class DailyReport(TenantModel):
    """日報。実績のハブ。

    承認時に CostTransaction（労務費）を自動生成する。
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "下書き"
        SUBMITTED = "submitted", "提出済"
        APPROVED = "approved", "承認済"

    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="daily_reports",
        verbose_name="現場",
    )
    worker = models.ForeignKey(
        "workers.Worker",
        on_delete=models.CASCADE,
        related_name="daily_reports",
        verbose_name="作業員",
    )
    report_date = models.DateField("日付")
    process = models.ForeignKey(
        "sites.Process",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="daily_reports",
        verbose_name="工程",
    )
    work_type = models.ForeignKey(
        "masters.WorkType",
        on_delete=models.CASCADE,
        related_name="daily_reports",
        verbose_name="工種",
    )
    work_hours = models.DecimalField(
        "作業時間",
        max_digits=5,
        decimal_places=2,
    )
    memo = models.TextField("メモ", blank=True)
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "日報"
        verbose_name_plural = "日報"
        unique_together = [("site", "worker", "report_date", "work_type")]

    def __str__(self):
        return f"{self.report_date} {self.worker} @ {self.site}"


class DailyReportMaterial(TenantModel):
    """日報に紐づく使用材料。"""

    daily_report = models.ForeignKey(
        DailyReport,
        on_delete=models.CASCADE,
        related_name="materials_used",
        verbose_name="日報",
    )
    material = models.ForeignKey(
        "materials.Material",
        on_delete=models.CASCADE,
        related_name="daily_report_usage",
        verbose_name="材料",
    )
    quantity_used = models.DecimalField(
        "使用数量",
        max_digits=10,
        decimal_places=2,
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "日報使用材料"
        verbose_name_plural = "日報使用材料"

    def __str__(self):
        return f"{self.daily_report} - {self.material}"
