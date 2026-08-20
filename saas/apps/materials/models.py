from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class Material(TenantModel):
    """資材マスタ。"""

    code = models.CharField("コード", max_length=50)
    name = models.CharField("材料名", max_length=200)
    unit = models.CharField("単位", max_length=50)
    category = models.CharField("分類", max_length=100, blank=True)
    standard_price = models.DecimalField(
        "参考単価",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
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


class Quotation(TenantModel):
    """見積。仕入先から取得した見積書と、自社が顧客に出した見積の両方を持つ。

    元は仕入先からの受領見積だけを想定していたが、見積ファイル（ライデンの
    Excel/CSV・見積書 PDF）の取り込みで自社発行の見積も同じ形で扱えるように
    kind で向きを分けた。明細（QuotationItem）と材料マスタの引き当ては
    どちらの向きでも同じものを使う。
    """

    class Kind(models.TextChoices):
        RECEIVED = "received", "仕入先から受領"
        ISSUED = "issued", "自社が発行"

    class Status(models.TextChoices):
        DRAFT = "draft", "依頼中"
        RECEIVED = "received", "取得済"
        ACCEPTED = "accepted", "採用"
        REJECTED = "rejected", "不採用"

    kind = models.CharField(
        "見積の向き",
        max_length=16,
        choices=Kind.choices,
        default=Kind.RECEIVED,
        help_text="仕入先から受領した見積か、自社が顧客へ出した見積か。",
    )
    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="quotations",
        verbose_name="現場",
    )
    supplier = models.ForeignKey(
        "masters.Supplier",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="quotations",
        verbose_name="仕入先",
        help_text="受領見積のときの相手先。自社発行の見積では空。",
    )
    customer = models.ForeignKey(
        "masters.Customer",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quotations",
        verbose_name="顧客",
        help_text="自社発行の見積のときの宛先。受領見積では空。",
    )
    quotation_number = models.CharField(
        "見積番号", max_length=100, blank=True,
    )
    source_filename = models.CharField(
        "取込元ファイル名", max_length=255, blank=True,
        help_text="見積ファイルから取り込んだ場合に残す。手入力なら空。",
    )
    quotation_date = models.DateField("見積日")
    valid_until = models.DateField("有効期限", null=True, blank=True)
    total_amount = models.DecimalField(
        "合計金額",
        max_digits=14,
        decimal_places=0,
        default=0,
    )
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    file = models.FileField(
        "見積書ファイル",
        upload_to="quotations/%Y/%m/",
        blank=True,
        help_text="PDF/Excelファイル",
    )
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "見積"
        verbose_name_plural = "見積"

    def __str__(self):
        return f"見積-{self.pk} {self.counterparty_name} ({self.quotation_date})"

    @property
    def counterparty_name(self) -> str:
        """相手先の表示名。向きによって仕入先／顧客のどちらかを出す。"""
        party = self.customer if self.kind == self.Kind.ISSUED else self.supplier
        return str(party) if party else "相手先未設定"


class QuotationItem(TenantModel):
    """見積明細。"""

    quotation = models.ForeignKey(
        Quotation,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="見積",
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="quotation_items",
        verbose_name="材料（マスタ）",
    )
    material_name = models.CharField("材料名（自由入力）", max_length=200, blank=True)
    spec = models.CharField("規格・仕様", max_length=300, blank=True)
    unit = models.CharField("単位", max_length=50, blank=True)
    # 取り込んだ見積書には金額だけで数量・単価が無い行がある（一式計上など）。
    # 0 を入れると「単価0円」という読めてもいない数字が残るので null を許す。
    quantity = models.DecimalField(
        "数量", max_digits=10, decimal_places=2, null=True, blank=True,
    )
    unit_price = models.DecimalField(
        "単価", max_digits=12, decimal_places=2, null=True, blank=True,
    )
    amount = models.DecimalField("金額", max_digits=14, decimal_places=0, default=0)
    remarks = models.CharField("備考", max_length=300, blank=True)
    sort_order = models.IntegerField("表示順", default=0)

    class Meta:
        verbose_name = "見積明細"
        verbose_name_plural = "見積明細"
        ordering = ["quotation", "sort_order", "pk"]

    def __str__(self):
        name = self.material.name if self.material else self.material_name
        return f"{self.quotation} - {name}"


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
    quotation = models.ForeignKey(
        Quotation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_orders",
        verbose_name="元見積",
    )
    order_date = models.DateField("発注日")
    delivery_date = models.DateField("納期", null=True, blank=True)
    subject = models.CharField("件名", max_length=300, blank=True)
    payment_terms = models.CharField(
        "支払条件", max_length=200, blank=True, default="月末締翌月末払",
    )
    notes = models.TextField("特記事項", blank=True)
    ordered_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ordered_purchase_orders",
        verbose_name="発注者",
    )
    total_amount = models.DecimalField(
        "合計金額",
        max_digits=14,
        decimal_places=0,
        default=0,
    )
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    file = models.FileField(
        "発注書ファイル",
        upload_to="purchase_orders/%Y/%m/",
        blank=True,
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "発注書"
        verbose_name_plural = "発注書"

    def __str__(self):
        return f"PO-{self.pk} {self.site} ({self.order_date})"

    def recalculate_total(self):
        """明細から合計金額を再計算する。"""
        total = self.items.aggregate(t=models.Sum(
            models.F("quantity") * models.F("unit_price")
        ))["t"] or 0
        self.total_amount = total
        self.save(update_fields=["total_amount"])


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
        null=True,
        blank=True,
        related_name="order_items",
        verbose_name="材料",
    )
    material_name = models.CharField(
        "材料名（自由入力）", max_length=200, blank=True,
        help_text="マスタにない場合の自由入力用",
    )
    quantity = models.DecimalField("数量", max_digits=10, decimal_places=2)
    unit = models.CharField("単位", max_length=50, blank=True)
    unit_price = models.DecimalField("単価", max_digits=12, decimal_places=2)
    tax_rate = models.DecimalField(
        "税率", max_digits=5, decimal_places=2, default=0.10,
        help_text="例: 0.10 = 10%",
    )
    work_type = models.ForeignKey(
        "masters.WorkType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_order_items",
        verbose_name="工種",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "発注明細"
        verbose_name_plural = "発注明細"

    @property
    def amount(self):
        return self.quantity * self.unit_price

    @property
    def display_name(self):
        if self.material:
            return self.material.name
        return self.material_name

    def __str__(self):
        return f"{self.purchase_order} - {self.display_name}"


class Delivery(TenantModel):
    """納品。発注に対する納品記録。"""

    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="deliveries",
        verbose_name="発注書",
    )
    delivery_date = models.DateField("納品日")
    image = models.ImageField(
        "納品書画像",
        upload_to="deliveries/%Y/%m/",
        blank=True,
        help_text="納品書の写真・スキャン画像",
    )
    original_filename = models.CharField(
        "元ファイル名", max_length=255, blank=True,
    )
    extraction_raw = models.TextField(
        "AI読取生データ", blank=True,
        help_text="Claude APIによるOCR結果の生テキスト",
    )
    received = models.BooleanField("受領済み", default=False)
    received_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_deliveries",
        verbose_name="受領者",
    )
    received_at = models.DateTimeField("受領日時", null=True, blank=True)
    inspected = models.BooleanField("検収済み", default=False)
    inspected_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inspected_deliveries",
        verbose_name="検収者",
    )
    inspected_at = models.DateTimeField("検収日時", null=True, blank=True)
    notes = models.TextField("備考", blank=True)

    class Meta:
        verbose_name = "納品"
        verbose_name_plural = "納品"

    def __str__(self):
        return f"納品 {self.delivery_date} - {self.purchase_order}"


class DeliveryItem(TenantModel):
    """納品明細。発注数量に対する納品数量をチェック。"""

    delivery = models.ForeignKey(
        Delivery,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="納品",
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.CASCADE,
        related_name="delivery_items",
        verbose_name="材料",
    )
    ordered_qty = models.DecimalField("発注数量", max_digits=10, decimal_places=2, default=0)
    delivered_qty = models.DecimalField("納品数量", max_digits=10, decimal_places=2)
    is_ok = models.BooleanField("数量OK", default=True)

    class Meta:
        verbose_name = "納品明細"
        verbose_name_plural = "納品明細"

    def __str__(self):
        return f"{self.delivery} - {self.material}"


class Inventory(TenantModel):
    """在庫。材料×保管場所(現場/本社)ごとの在庫数を管理。"""

    material = models.ForeignKey(
        Material,
        on_delete=models.CASCADE,
        related_name="inventories",
        verbose_name="材料",
    )
    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="inventories",
        verbose_name="現場（空=本社倉庫）",
    )
    quantity = models.DecimalField(
        "在庫数",
        max_digits=10,
        decimal_places=2,
        default=0,
    )
    last_updated = models.DateTimeField("最終更新", auto_now=True)

    class Meta:
        verbose_name = "在庫"
        verbose_name_plural = "在庫"
        unique_together = [("material", "site")]

    def __str__(self):
        location = self.site.name if self.site else "本社倉庫"
        return f"{self.material.name} @ {location}: {self.quantity}"


class MaterialSupplier(TenantModel):
    """材料×仕入先の紐付け。材料ごとにどの仕入先から仕入れられるかを管理する。

    Material に対して複数の Supplier を登録でき、
    標準単価・標準納期・最小発注数量などを記録する。
    """

    material = models.ForeignKey(
        Material,
        on_delete=models.CASCADE,
        related_name="suppliers",
        verbose_name="材料",
    )
    supplier = models.ForeignKey(
        "masters.Supplier",
        on_delete=models.CASCADE,
        related_name="material_supplies",
        verbose_name="仕入先",
    )
    supplier_code = models.CharField(
        "仕入先品番", max_length=100, blank=True,
        help_text="この仕入先でのカタログ品番",
    )
    standard_unit_price = models.DecimalField(
        "標準単価", max_digits=12, decimal_places=2,
        null=True, blank=True,
    )
    lead_time_days = models.IntegerField(
        "標準納期（日）", null=True, blank=True,
        help_text="発注から納品までの標準日数",
    )
    min_order_qty = models.DecimalField(
        "最小発注数量", max_digits=10, decimal_places=2,
        null=True, blank=True,
    )
    is_preferred = models.BooleanField(
        "推奨仕入先", default=False,
        help_text="この材料の優先的な仕入先",
    )
    is_active = models.BooleanField("有効", default=True)
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "材料仕入先"
        verbose_name_plural = "材料仕入先"
        unique_together = [("company", "material", "supplier")]

    def __str__(self):
        return f"{self.material.name} ← {self.supplier.name}"


class ProcurementRecord(TenantModel):
    """調達実績。現場ごとに何をどこから仕入れたかの記録。

    発注→納品の検収完了時に自動生成される。
    実際の納期（リードタイム）を記録し、仕入先の評価に使う。
    """

    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="procurement_records",
        verbose_name="現場",
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.CASCADE,
        related_name="procurement_records",
        verbose_name="材料",
    )
    supplier = models.ForeignKey(
        "masters.Supplier",
        on_delete=models.CASCADE,
        related_name="procurement_records",
        verbose_name="仕入先",
    )
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="procurement_records",
        verbose_name="元発注書",
    )
    ordered_date = models.DateField("発注日")
    delivered_date = models.DateField("納品日", null=True, blank=True)
    actual_lead_days = models.IntegerField(
        "実納期（日）", null=True, blank=True,
        help_text="発注日から納品日までの実日数",
    )
    ordered_qty = models.DecimalField("発注数量", max_digits=10, decimal_places=2)
    delivered_qty = models.DecimalField(
        "納品数量", max_digits=10, decimal_places=2,
        null=True, blank=True,
    )
    unit_price_paid = models.DecimalField(
        "仕入単価", max_digits=12, decimal_places=2,
    )
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "調達実績"
        verbose_name_plural = "調達実績"
        indexes = [
            models.Index(fields=["company", "material", "supplier"]),
            models.Index(fields=["company", "site"]),
        ]

    def __str__(self):
        return f"{self.site.name} {self.material.name} ← {self.supplier.name}"

    def calc_lead_days(self):
        """実納期を計算する。"""
        if self.ordered_date and self.delivered_date:
            self.actual_lead_days = (self.delivered_date - self.ordered_date).days
        return self.actual_lead_days
