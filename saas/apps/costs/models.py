from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class BudgetItem(TenantModel):
    """実行予算。受注時に工種×原価区分で確定する。"""

    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="budget_items",
        verbose_name="現場",
    )
    work_type = models.ForeignKey(
        "masters.WorkType",
        on_delete=models.CASCADE,
        related_name="budget_items",
        verbose_name="工種",
    )
    cost_category = models.ForeignKey(
        "masters.CostCategory",
        on_delete=models.PROTECT,
        related_name="budget_items",
        verbose_name="原価区分",
    )
    name = models.CharField("項目名", max_length=200)
    unit = models.CharField("単位", max_length=50, blank=True)
    quantity = models.DecimalField(
        "数量",
        max_digits=10,
        decimal_places=2,
        default=0,
    )
    unit_price = models.DecimalField(
        "単価",
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    amount = models.DecimalField(
        "金額",
        max_digits=14,
        decimal_places=0,
        default=0,
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "実行予算"
        verbose_name_plural = "実行予算"

    def __str__(self):
        return f"{self.site} / {self.work_type} / {self.name}"


class CostTransaction(TenantModel):
    """統一原価データ。全原価がこのテーブルに同じ粒度で入る。

    CostTransaction 自体は不変（追記のみ）。
    訂正時は逆仕訳＋再仕訳を生成する。
    """

    class SourceType(models.TextChoices):
        DAILY_REPORT = "daily_report", "日報（労務費）"
        PO_ITEM = "po_item", "発注明細（材料費）"
        OUTSOURCING = "outsourcing", "外注"
        EXPENSE = "expense", "経費"
        REVERSAL = "reversal", "逆仕訳"

    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="cost_transactions",
        verbose_name="現場",
    )
    work_type = models.ForeignKey(
        "masters.WorkType",
        on_delete=models.CASCADE,
        related_name="cost_transactions",
        verbose_name="工種",
    )
    cost_category = models.ForeignKey(
        "masters.CostCategory",
        on_delete=models.PROTECT,
        related_name="cost_transactions",
        verbose_name="原価区分",
    )
    amount = models.DecimalField(
        "金額",
        max_digits=14,
        decimal_places=0,
    )
    transaction_date = models.DateField("発生日")
    source_type = models.CharField(
        "発生元種別",
        max_length=20,
        choices=SourceType.choices,
    )
    source_id = models.BigIntegerField(
        "発生元ID",
        null=True,
        blank=True,
        help_text="発生元レコードのPK",
    )
    supplier = models.ForeignKey(
        "masters.Supplier",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cost_transactions",
        verbose_name="仕入先",
    )
    manhours = models.DecimalField(
        "工数",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "原価データ"
        verbose_name_plural = "原価データ"
        indexes = [
            models.Index(
                fields=["company", "site", "work_type", "cost_category"],
                name="idx_cost_tx_main",
            ),
        ]

    def __str__(self):
        return (
            f"{self.transaction_date} {self.site} "
            f"{self.get_source_type_display()} {self.amount}"
        )
