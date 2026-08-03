from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class Phase(TenantModel):
    """工程フェーズ。現場ごとのガントチャート的な工程管理。"""

    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="phases",
        verbose_name="現場",
    )
    name = models.CharField("工程名", max_length=200)
    start_date = models.DateField("開始日", null=True, blank=True)
    end_date = models.DateField("終了日", null=True, blank=True)
    progress = models.IntegerField(
        "進捗(%)",
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    sort_order = models.IntegerField("表示順", default=0)
    color = models.CharField("色", max_length=7, default="#3b82f6")
    memo = models.TextField("メモ", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "工程フェーズ"
        verbose_name_plural = "工程フェーズ"
        ordering = ["sort_order"]

    def __str__(self):
        return f"{self.site} - {self.name}"


class Milestone(TenantModel):
    """マイルストーン。現場ごとの重要な期日。"""

    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="milestones",
        verbose_name="現場",
    )
    name = models.CharField("マイルストーン名", max_length=200)
    target_date = models.DateField("目標日", null=True, blank=True)
    completed = models.BooleanField("完了", default=False)
    memo = models.TextField("メモ", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "マイルストーン"
        verbose_name_plural = "マイルストーン"
        ordering = ["target_date"]

    def __str__(self):
        return f"{self.site} - {self.name}"


class Assignment(TenantModel):
    """配置。作業員の現場への配置期間。"""

    worker = models.ForeignKey(
        "workers.Worker",
        on_delete=models.CASCADE,
        related_name="assignments",
        verbose_name="作業員",
    )
    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="assignments",
        verbose_name="現場",
    )
    start_date = models.DateField("開始日")
    end_date = models.DateField("終了日", null=True, blank=True)
    memo = models.TextField("メモ", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "配置"
        verbose_name_plural = "配置"
        ordering = ["start_date"]

    def __str__(self):
        return f"{self.worker} @ {self.site}"


class PhaseTemplate(TenantModel):
    """工程テンプレート。よくある工事パターンをテンプレート化して再利用する。"""

    name = models.CharField("テンプレート名", max_length=200)
    description = models.TextField("説明", blank=True)

    class Meta:
        verbose_name = "工程テンプレート"
        verbose_name_plural = "工程テンプレート"

    def __str__(self):
        return self.name


class PhaseTemplateItem(TenantModel):
    """工程テンプレート明細。開始日からのオフセット（日数）で定義。"""

    template = models.ForeignKey(
        PhaseTemplate,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="テンプレート",
    )
    name = models.CharField("工程名", max_length=200)
    offset_days_start = models.IntegerField("開始日オフセット（日）", default=0)
    offset_days_end = models.IntegerField("終了日オフセット（日）", default=7)
    sort_order = models.IntegerField("表示順", default=0)
    color = models.CharField("色", max_length=7, default="#3b82f6")

    class Meta:
        verbose_name = "テンプレート工程"
        verbose_name_plural = "テンプレート工程"
        ordering = ["sort_order"]

    def __str__(self):
        return f"{self.template.name} - {self.name}"
