from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class Material(TenantModel):
    """資材マスタ。"""

    code = models.CharField("コード", max_length=50)
    name = models.CharField("材料名", max_length=200)
    unit = models.CharField("単位", max_length=50)
    category = models.CharField("分類", max_length=100, blank=True)
    work_type = models.ForeignKey(
        "masters.WorkType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="materials",
        verbose_name="工種",
    )
    is_active = models.BooleanField("有効", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "材料"
        verbose_name_plural = "材料"
        unique_together = [("company", "code")]

    def __str__(self):
        return self.name


class PurchaseOrder(TenantModel):
    """発注書。"""

    class Status(models.TextChoices):
        DRAFT = "draft", "下書き"
        ORDERED = "ordered", "発注済"
        PARTIALLY_RECEIVED = "partially_received", "一部検収"
        RECEIVED = "received", "検収済"
        CANCELLED = "cancelled", "取消"

    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="purchase_orders",
        verbose_name="現場",
    )
    supplier = models.ForeignKey(
        "masters.Supplier",
        on_delete=models.CASCADE,
        related_name="purchase_orders",
        verbose_name="仕入先",
    )
    order_date = models.DateField("発注日")
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "発注書"
        verbose_name_plural = "発注書"

    def __str__(self):
        return f"PO-{self.pk} {self.site} ({self.order_date})"


class PurchaseOrderItem(TenantModel):
    """発注明細。work_type を明細に持つ＝原価粒度を発注時点で確定。"""

    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="発注書",
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.CASCADE,
        related_name="order_items",
        verbose_name="材料",
    )
    quantity = models.DecimalField(
        "数量",
        max_digits=10,
        decimal_places=2,
    )
    unit_price = models.DecimalField(
        "単価",
        max_digits=12,
        decimal_places=2,
    )
    work_type = models.ForeignKey(
        "masters.WorkType",
        on_delete=models.CASCADE,
        related_name="purchase_order_items",
        verbose_name="工種",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "発注明細"
        verbose_name_plural = "発注明細"

    def __str__(self):
        return f"{self.purchase_order} - {self.material}"
