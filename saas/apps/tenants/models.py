from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.managers import UnscopedManager
from apps.core.models import TimeStampedModel


class Company(TimeStampedModel):
    """テナント（会社）。全データの起点。"""

    name = models.CharField("会社名", max_length=200)
    industry_type = models.CharField(
        "業種（参考情報）",
        max_length=100,
        blank=True,
        help_text="ロジックの分岐には使用禁止（ADR-0003）",
    )
    contract_plan = models.CharField("契約プラン", max_length=50, blank=True)
    is_active = models.BooleanField("有効", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "会社"
        verbose_name_plural = "会社"

    def __str__(self):
        return self.name


class CompanyApp(TimeStampedModel):
    """テナントごとの有効アプリ。機能アクセス制御と課金判定の単一情報源。"""

    APP_CODES = [
        ("jinzai", "人材管理"),
        ("hyoka", "人材評価"),
        ("koutei", "工期・工程管理"),
        ("zairyo", "材料管理"),
        ("nippou", "日報管理"),
        ("genka", "原価・予実管理"),
    ]

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="apps",
        verbose_name="会社",
    )
    app_code = models.CharField("アプリコード", max_length=20, choices=APP_CODES)
    is_enabled = models.BooleanField("有効", default=False)
    enabled_at = models.DateTimeField("有効化日時", null=True, blank=True)

    # CompanyApp はテナント横断で参照する場面がある（@app_required）
    objects = UnscopedManager()
    unscoped = UnscopedManager()

    history = HistoricalRecords()

    class Meta:
        verbose_name = "有効アプリ"
        verbose_name_plural = "有効アプリ"
        unique_together = [("company", "app_code")]

    def __str__(self):
        return f"{self.company} - {self.get_app_code_display()}"
