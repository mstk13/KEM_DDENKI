from decimal import Decimal

from django.conf import settings
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

    class Weather(models.TextChoices):
        SUNNY = "sunny", "晴"
        CLOUDY = "cloudy", "曇"
        RAINY = "rainy", "雨"
        SNOWY = "snowy", "雪"
        OTHER = "other", "その他"

    class ReportType(models.TextChoices):
        MANAGEMENT = "management", "管理"
        OFFICE = "office", "事務"
        ELECTRICIAN = "electrician", "電工"
        IT = "it", "IT"

    report_type = models.CharField(
        "種別",
        max_length=20,
        choices=ReportType.choices,
        default=ReportType.ELECTRICIAN,
    )
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
    weather = models.CharField(
        "天候",
        max_length=10,
        choices=Weather.choices,
        blank=True,
    )
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
    work_description = models.TextField("作業内容", blank=True)

    # 時間管理
    start_time = models.TimeField("開始時間", null=True, blank=True)
    end_time = models.TimeField("終了時間", null=True, blank=True)
    work_hours = models.DecimalField(
        "作業時間",
        max_digits=5,
        decimal_places=2,
    )
    regular_hours = models.DecimalField(
        "通常時間",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    overtime_hours = models.DecimalField(
        "残業時間",
        max_digits=5,
        decimal_places=2,
        default=0,
    )

    # 協力会社対応
    is_partner_worker = models.BooleanField("協力会社の作業員", default=False)
    partner = models.ForeignKey(
        "masters.Supplier",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="daily_reports",
        verbose_name="協力会社",
    )

    memo = models.TextField("その他", blank=True)
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    # 承認情報
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_reports",
        verbose_name="承認者",
    )
    approved_at = models.DateTimeField("承認日時", null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "日報"
        verbose_name_plural = "日報"
        unique_together = [("site", "worker", "report_date", "work_type")]

    def __str__(self):
        return f"{self.report_date} {self.worker} @ {self.site}"

    def calculate_hours(self):
        """開始・終了時間から通常時間と残業時間を自動計算する。

        基準: 8時間を超えた分が残業。
        """
        if not self.start_time or not self.end_time:
            return

        from datetime import datetime, timedelta

        start_dt = datetime.combine(self.report_date, self.start_time)
        end_dt = datetime.combine(self.report_date, self.end_time)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)

        # 休憩1時間を差し引き（8時間以上の場合）
        total_minutes = (end_dt - start_dt).total_seconds() / 60
        if total_minutes > 480:  # 8時間超
            total_minutes -= 60  # 休憩1時間

        total_hours = Decimal(str(round(total_minutes / 60, 2)))
        regular_limit = Decimal("8.00")

        self.work_hours = total_hours
        if total_hours > regular_limit:
            self.regular_hours = regular_limit
            self.overtime_hours = total_hours - regular_limit
        else:
            self.regular_hours = total_hours
            self.overtime_hours = Decimal("0.00")

    def save(self, *args, **kwargs):
        if self.start_time and self.end_time:
            self.calculate_hours()
        super().save(*args, **kwargs)


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
        null=True,
        blank=True,
        related_name="daily_report_usage",
        verbose_name="材料（マスタ）",
    )
    material_name = models.CharField(
        "材料名（自由入力）",
        max_length=200,
        blank=True,
        help_text="マスタ外の材料の場合に使用",
    )
    quantity_used = models.DecimalField(
        "使用数量",
        max_digits=10,
        decimal_places=2,
    )
    unit = models.CharField("単位", max_length=20, blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "日報使用材料"
        verbose_name_plural = "日報使用材料"

    def __str__(self):
        name = self.material.name if self.material else self.material_name
        return f"{self.daily_report} - {name}"


class SafetyTemplate(TenantModel):
    """安全書類ひな型。現場ごとにKY活動記録等のテンプレートを管理。"""

    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="safety_templates",
        verbose_name="現場",
    )
    name = models.CharField(
        "書類名",
        max_length=200,
        help_text="例: KY活動記録、TBM記録",
    )
    template_file = models.FileField(
        "ひな型ファイル",
        upload_to="safety_templates/%Y/%m/",
        blank=True,
    )
    is_daily_required = models.BooleanField(
        "毎日必須",
        default=True,
        help_text="毎日全作業員の記入が必要か",
    )

    class Meta:
        verbose_name = "安全書類ひな型"
        verbose_name_plural = "安全書類ひな型"
        unique_together = [("site", "name")]

    def __str__(self):
        return f"{self.site.name} - {self.name}"


class SafetyRecord(TenantModel):
    """安全書類の記入チェック。

    毎日、全作業員がKY等の必要書類を記入しているかを管理する。
    未記入者にはアラートを出す。
    """

    template = models.ForeignKey(
        SafetyTemplate,
        on_delete=models.CASCADE,
        related_name="records",
        verbose_name="ひな型",
    )
    worker = models.ForeignKey(
        "workers.Worker",
        on_delete=models.CASCADE,
        related_name="safety_records",
        verbose_name="作業員",
    )
    record_date = models.DateField("記入日")
    completed = models.BooleanField("記入済み", default=False)
    completed_at = models.DateTimeField("記入完了日時", null=True, blank=True)
    alerted = models.BooleanField("アラート送信済み", default=False)

    class Meta:
        verbose_name = "安全書類記入チェック"
        verbose_name_plural = "安全書類記入チェック"
        unique_together = [("template", "worker", "record_date")]
        indexes = [
            models.Index(fields=["record_date", "completed"]),
        ]

    def __str__(self):
        status = "✅" if self.completed else "⚠"
        return f"{status} {self.worker.name} - {self.template.name} ({self.record_date})"
