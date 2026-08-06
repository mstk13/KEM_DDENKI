from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class AttendReport(TenantModel):
    """勤怠日報ヘッダ。1日1現場の出勤記録をまとめる。"""

    class Status(models.TextChoices):
        UNCONFIRMED = "未確認", "未確認"
        CONFIRMED = "確認済", "確認済"
        APPROVED = "承認済", "承認済"
        REJECTED = "差戻し", "差戻し"

    report_date = models.DateField("日付")
    site_name = models.CharField("現場名", max_length=255, blank=True)
    work_content = models.TextField("作業内容", blank=True)
    note = models.TextField("備考", blank=True)
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.UNCONFIRMED,
    )
    source_text = models.TextField("元テキスト", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "勤怠日報"
        verbose_name_plural = "勤怠日報"
        ordering = ["-report_date"]

    def __str__(self):
        return f"{self.report_date} {self.site_name}"


class AttendEntry(TenantModel):
    """作業員ごとの勤怠エントリ。"""

    report = models.ForeignKey(
        AttendReport,
        on_delete=models.CASCADE,
        related_name="entries",
        verbose_name="勤怠日報",
    )
    worker = models.ForeignKey(
        "workers.Worker",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attend_entries",
        verbose_name="作業員",
    )
    employee_name = models.CharField("氏名", max_length=100)
    start_time = models.CharField("開始時刻", max_length=10, blank=True)
    end_time = models.CharField("終了時刻", max_length=10, blank=True)
    break_minutes = models.IntegerField("休憩(分)", default=60)
    early_minutes = models.IntegerField("早出(分)", default=0)
    normal_minutes = models.IntegerField("所定(分)", default=0)
    overtime_minutes = models.IntegerField("残業(分)", default=0)
    total_minutes = models.IntegerField("合計(分)", default=0)
    note = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "勤怠エントリ"
        verbose_name_plural = "勤怠エントリ"
        ordering = ["employee_name"]

    def __str__(self):
        return f"{self.employee_name} ({self.report.report_date})"


class AttendSettings(TenantModel):
    """勤怠計算用のキーバリュー設定。"""

    key = models.CharField("設定キー", max_length=50)
    value = models.CharField("設定値", max_length=100)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "勤怠設定"
        verbose_name_plural = "勤怠設定"
        unique_together = [("company", "key")]

    def __str__(self):
        return f"{self.key}={self.value}"

    # デフォルト設定キー
    DEFAULTS = {
        "standard_start": "08:00",
        "standard_end": "17:00",
        "early_boundary": "08:00",
        "standard_hours": "8.0",
        "break_minutes": "60",
        "round_minutes": "0",
        "overtime_mode": "clock",
    }

    @classmethod
    def get_settings_dict(cls, company):
        """会社の全設定を辞書で返す。未設定キーはデフォルト値を使用。"""
        saved = dict(
            cls.unscoped.filter(company=company).values_list("key", "value")
        )
        result = dict(cls.DEFAULTS)
        result.update(saved)
        return result
