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
    """顧客マスタ。"""

    code = models.CharField("コード", max_length=50)
    name = models.CharField("顧客名", max_length=200)
    representative = models.CharField("代表者名", max_length=100, blank=True)
    contact_person = models.CharField("担当者名", max_length=100, blank=True)
    phone = models.CharField("電話番号", max_length=30, blank=True)
    fax = models.CharField("FAX", max_length=30, blank=True)
    email = models.EmailField("メール", blank=True)
    address = models.TextField("住所", blank=True)
    payment_terms = models.CharField(
        "標準支払条件",
        max_length=200,
        blank=True,
        help_text="例: 月末締め翌月末現金払い。現場ごとに違う場合は現場側で上書きする。",
    )
    note = models.TextField("備考", blank=True)
    is_active = models.BooleanField("有効", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "顧客"
        verbose_name_plural = "顧客"
        unique_together = [("company", "code")]

    def __str__(self):
        return self.name


class Supplier(TenantModel):
    """仕入先マスタ。"""

    code = models.CharField("コード", max_length=50)
    name = models.CharField("仕入先名", max_length=200)
    representative = models.CharField("代表者名", max_length=100, blank=True)
    contact_person = models.CharField("担当者名", max_length=100, blank=True)
    phone = models.CharField("電話番号", max_length=30, blank=True)
    fax = models.CharField("FAX", max_length=30, blank=True)
    email = models.EmailField("メール", blank=True)
    address = models.TextField("住所", blank=True)
    note = models.TextField("備考", blank=True)
    is_active = models.BooleanField("有効", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "仕入先"
        verbose_name_plural = "仕入先"
        unique_together = [("company", "code")]

    def __str__(self):
        return self.name


class SupplierEvaluation(TenantModel):
    """仕入先評価。金額・納期・品質・サービス内容を記録する。"""

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        related_name="evaluations",
        verbose_name="仕入先",
    )
    evaluator = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="supplier_evaluations",
        verbose_name="評価者",
    )
    evaluation_date = models.DateField("評価日")
    price_rating = models.IntegerField("金額評価(1-5)", default=3)
    delivery_rating = models.IntegerField("納期評価(1-5)", default=3)
    quality_rating = models.IntegerField("品質評価(1-5)", default=3)
    service_description = models.TextField("サービス/商品内容", blank=True)
    notes = models.TextField("備考", blank=True)

    class Meta:
        verbose_name = "仕入先評価"
        verbose_name_plural = "仕入先評価"
        ordering = ["-evaluation_date"]

    @property
    def average_rating(self):
        return round((self.price_rating + self.delivery_rating + self.quality_rating) / 3, 1)

    def __str__(self):
        return f"{self.supplier.name} - {self.evaluation_date}"


class BusinessCard(TenantModel):
    """名刺。取引先の担当者の名刺画像を保存する。"""

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="business_cards",
        verbose_name="顧客",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="business_cards",
        verbose_name="仕入先",
    )
    person_name = models.CharField("担当者名", max_length=100)
    position = models.CharField("役職", max_length=100, blank=True)
    phone = models.CharField("電話番号", max_length=20, blank=True)
    email = models.EmailField("メール", blank=True)
    image = models.ImageField(
        "名刺画像",
        upload_to="business_cards/%Y/%m/",
    )

    class Meta:
        verbose_name = "名刺"
        verbose_name_plural = "名刺"

    def __str__(self):
        partner = self.customer or self.supplier
        return f"{partner} - {self.person_name}"


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
