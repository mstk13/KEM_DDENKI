from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel, TimeStampedModel


class WorkType(TenantModel):
    """工種マスタ。業種拡張の吸収層。

    階層構造で業種の違いを表現する。
    例: 電気 > 幹線・動力 / 弱電
        内装仕上 > 軽鉄・ボード / クロス
    業種拡張 = マスタへの行追加のみ。コード変更ゼロ。
    """

    code = models.CharField("コード", max_length=50)
    name = models.CharField("工種名", max_length=200)
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="親工種",
    )
    display_order = models.IntegerField("表示順", default=0)
    is_active = models.BooleanField("有効", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "工種"
        verbose_name_plural = "工種"
        unique_together = [("company", "code")]
        ordering = ["display_order", "code"]

    def __str__(self):
        return self.name


class CostCategory(TimeStampedModel):
    """原価区分。全テナント共通・システム定義。

    建設業4区分: 材料費 / 労務費 / 外注費 / 経費
    """

    code = models.CharField("コード", max_length=20, unique=True)
    name = models.CharField("区分名", max_length=100)
    display_order = models.IntegerField("表示順", default=0)

    class Meta:
        verbose_name = "原価区分"
        verbose_name_plural = "原価区分"
        ordering = ["display_order"]

    def __str__(self):
        return self.name


class Customer(TenantModel):
    """得意先マスタ。"""

    code = models.CharField("コード", max_length=50)
    name = models.CharField("得意先名", max_length=200)
    address = models.TextField("住所", blank=True)
    is_active = models.BooleanField("有効", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "得意先"
        verbose_name_plural = "得意先"
        unique_together = [("company", "code")]

    def __str__(self):
        return self.name


class Supplier(TenantModel):
    """仕入先マスタ。"""

    code = models.CharField("コード", max_length=50)
    name = models.CharField("仕入先名", max_length=200)
    contact_info = models.TextField("連絡先", blank=True)
    is_active = models.BooleanField("有効", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "仕入先"
        verbose_name_plural = "仕入先"
        unique_together = [("company", "code")]

    def __str__(self):
        return self.name


class WorkStandard(TenantModel):
    """歩掛マスタ。標準工数・標準単価。

    日報実績から将来自動更新（AI段階3の入口）。
    """

    work_type = models.ForeignKey(
        WorkType,
        on_delete=models.CASCADE,
        related_name="standards",
        verbose_name="工種",
    )
    name = models.CharField("作業名", max_length=200)
    unit = models.CharField("単位", max_length=50)
    standard_unit_cost = models.DecimalField(
        "標準単価",
        max_digits=12,
        decimal_places=2,
    )
    standard_manhours = models.DecimalField(
        "標準工数",
        max_digits=8,
        decimal_places=2,
    )
    valid_from = models.DateField("有効開始日")
    is_active = models.BooleanField("有効", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "歩掛マスタ"
        verbose_name_plural = "歩掛マスタ"

    def __str__(self):
        return f"{self.work_type} - {self.name}"
