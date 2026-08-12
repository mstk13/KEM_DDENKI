from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class BidProject(TenantModel):
    """入札案件。"""

    class Status(models.TextChoices):
        NEW = "new", "新着"
        CONSIDERING = "considering", "検討中"
        BID = "bid", "入札済"
        WON = "won", "落札"
        LOST = "lost", "失注"
        SKIPPED = "skipped", "見送り"

    class SourceType(models.TextChoices):
        MANUAL = "manual", "手動登録"
        SCRAPING = "scraping", "Webスクレイピング"
        EMAIL = "email", "メール取込"

    title = models.CharField("案件名", max_length=300)
    client = models.CharField("発注者", max_length=200, blank=True)
    client_ref = models.ForeignKey(
        "masters.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bid_projects",
        verbose_name="発注者（マスタ）",
    )
    region = models.CharField("地域", max_length=100, blank=True)
    category = models.CharField("工事種別", max_length=100, blank=True)
    deadline = models.DateField("入札期限", null=True, blank=True)
    budget = models.DecimalField(
        "予算額",
        max_digits=14,
        decimal_places=0,
        default=0,
    )
    our_bid_amount = models.DecimalField(
        "自社入札額",
        max_digits=14,
        decimal_places=0,
        null=True,
        blank=True,
    )
    source_type = models.CharField(
        "収集元",
        max_length=20,
        choices=SourceType.choices,
        default=SourceType.MANUAL,
    )
    source_url = models.URLField("情報源URL", blank=True)
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
    )
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "入札案件"
        verbose_name_plural = "入札案件"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class BidCost(TenantModel):
    """原価情報。入札案件と1:1。"""

    project = models.OneToOneField(
        BidProject,
        on_delete=models.CASCADE,
        related_name="cost",
        verbose_name="入札案件",
    )
    estimate_amount = models.DecimalField(
        "見積額",
        max_digits=14,
        decimal_places=0,
        default=0,
    )
    actual_cost = models.DecimalField(
        "実際原価",
        max_digits=14,
        decimal_places=0,
        default=0,
    )
    memo = models.TextField("メモ", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "原価情報"
        verbose_name_plural = "原価情報"

    def __str__(self):
        return f"{self.project} の原価"


class BidCompetitor(TenantModel):
    """競合情報。"""

    project = models.ForeignKey(
        BidProject,
        on_delete=models.CASCADE,
        related_name="competitors",
        verbose_name="入札案件",
    )
    competitor_name = models.CharField("競合名", max_length=200)
    competitor_amount = models.DecimalField(
        "競合金額",
        max_digits=14,
        decimal_places=0,
        default=0,
    )
    source = models.CharField("情報源", max_length=200, blank=True)
    memo = models.TextField("メモ", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "競合情報"
        verbose_name_plural = "競合情報"

    def __str__(self):
        return f"{self.competitor_name} ({self.project})"


class BidDocument(TenantModel):
    """入札書類。入札に必要な書類をアプリ上で管理する。"""

    project = models.ForeignKey(
        BidProject,
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name="入札案件",
    )
    name = models.CharField("書類名", max_length=200)
    doc_type = models.CharField(
        "書類種別",
        max_length=50,
        blank=True,
        help_text="仕様書、図面、見積書 等",
    )
    file = models.FileField(
        "ファイル",
        upload_to="bid_documents/%Y/%m/",
    )

    class Meta:
        verbose_name = "入札書類"
        verbose_name_plural = "入札書類"

    def __str__(self):
        return f"{self.project.title} - {self.name}"


class ScrapeTarget(TenantModel):
    """スクレイピング対象。官公庁の入札情報公開ページ。"""

    SITE_KEY_CHOICES = [
        ("shigaku", "私学事業団"),
        ("mod_msdf", "海上自衛隊"),
        ("mod_gsdf", "陸上自衛隊"),
        ("mod_asdf", "航空自衛隊"),
        ("kanagawa_thk", "かながわ土地建物"),
        ("kanagawa_ebid", "神奈川電子入札共同システム"),
        ("kanagawa_swf", "神奈川県下水道公社"),
        ("npb", "国立印刷局"),
        ("geps", "政府電子調達(GEPS)"),
    ]

    name = models.CharField("名称", max_length=200)
    url = models.URLField("URL", max_length=500)
    site_key = models.CharField(
        "サイト識別子",
        max_length=30,
        choices=SITE_KEY_CHOICES,
        blank=True,
        help_text="スクレイパーの選択に使用",
    )
    region = models.CharField("地域", max_length=100, blank=True)
    category_filter = models.CharField(
        "工事種別フィルタ",
        max_length=200,
        blank=True,
        help_text="取得対象の工事種別（空欄=全件）。例: 電気,設備",
    )
    is_active = models.BooleanField("有効", default=True)
    scrape_interval_hours = models.IntegerField(
        "巡回間隔（時間）", default=24,
    )
    last_scraped_at = models.DateTimeField("最終取得日時", null=True, blank=True)
    last_result = models.CharField(
        "最終結果", max_length=200, blank=True,
        help_text="例: 新規3件取得、エラーなし",
    )
    error_count = models.IntegerField("連続エラー回数", default=0)
    last_error = models.TextField("最後のエラー", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "スクレイピング対象"
        verbose_name_plural = "スクレイピング対象"

    def __str__(self):
        return self.name


class UnitPrice(TenantModel):
    """単価マスタ。"""

    category = models.CharField("カテゴリ", max_length=100)
    item_name = models.CharField("品目名", max_length=200)
    unit = models.CharField("単位", max_length=50)
    unit_price = models.DecimalField(
        "単価",
        max_digits=14,
        decimal_places=0,
        default=0,
    )
    memo = models.TextField("メモ", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "単価マスタ"
        verbose_name_plural = "単価マスタ"
        ordering = ["category", "item_name"]

    def __str__(self):
        return f"{self.category} / {self.item_name}"


class Qualification(TenantModel):
    """入札参加資格。"""

    issuer = models.CharField("発注機関", max_length=200)
    category = models.CharField("業種区分", max_length=100, blank=True)
    grade = models.CharField("等級", max_length=50, blank=True)
    keisin_score = models.IntegerField("経審点", null=True, blank=True)
    total_score = models.IntegerField("総合点", null=True, blank=True)
    vendor_number = models.CharField("業者番号", max_length=100, blank=True)
    valid_from = models.DateField("有効開始日", null=True, blank=True)
    valid_until = models.DateField("有効期限", null=True, blank=True)
    application_type = models.CharField("申請種別", max_length=100, blank=True)
    application_method = models.CharField("申請方法", max_length=100, blank=True)
    renewed = models.BooleanField("更新済", default=False)
    memo = models.TextField("メモ", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "入札参加資格"
        verbose_name_plural = "入札参加資格"
        ordering = ["issuer", "category"]

    def __str__(self):
        return f"{self.issuer} ({self.category})"
