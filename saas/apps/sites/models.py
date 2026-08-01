from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class Site(TenantModel):
    """現場。全業務データの起点。案件=現場を1:1とする。"""

    class Status(models.TextChoices):
        ESTIMATING = "estimating", "見積中"
        ORDERED = "ordered", "受注済"
        IN_PROGRESS = "in_progress", "施工中"
        COMPLETED = "completed", "完工"
        BILLED = "billed", "請求済"
        CANCELLED = "cancelled", "中止"

    code = models.CharField("現場コード", max_length=50)
    name = models.CharField("現場名", max_length=200)
    customer = models.ForeignKey(
        "masters.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sites",
        verbose_name="得意先",
    )
    work_types = models.ManyToManyField(
        "masters.WorkType",
        blank=True,
        related_name="sites",
        verbose_name="工種",
    )
    address = models.TextField("住所", blank=True)
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.ESTIMATING,
    )
    contract_amount = models.DecimalField(
        "受注金額",
        max_digits=14,
        decimal_places=0,
        default=0,
    )
    start_date = models.DateField("工期開始", null=True, blank=True)
    end_date = models.DateField("工期終了", null=True, blank=True)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_sites",
        verbose_name="現場担当者",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "現場"
        verbose_name_plural = "現場"
        unique_together = [("company", "code")]

    def __str__(self):
        return self.name


class Process(TenantModel):
    """工程。現場ごとの計画工程と実績。"""

    class Status(models.TextChoices):
        PLANNED = "planned", "計画"
        IN_PROGRESS = "in_progress", "進行中"
        COMPLETED = "completed", "完了"
        DELAYED = "delayed", "遅延"

    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="processes",
        verbose_name="現場",
    )
    work_type = models.ForeignKey(
        "masters.WorkType",
        on_delete=models.CASCADE,
        related_name="processes",
        verbose_name="工種",
    )
    name = models.CharField("工程名", max_length=200)
    planned_start = models.DateField("計画開始日", null=True, blank=True)
    planned_end = models.DateField("計画終了日", null=True, blank=True)
    actual_start = models.DateField("実績開始日", null=True, blank=True)
    actual_end = models.DateField("実績終了日", null=True, blank=True)
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.PLANNED,
    )
    display_order = models.IntegerField("表示順", default=0)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "工程"
        verbose_name_plural = "工程"
        ordering = ["display_order"]

    def __str__(self):
        return f"{self.site} - {self.name}"
