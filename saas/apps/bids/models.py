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

    # 入札参加資格の要件（i-ppi 連携で自動取得）
    required_category = models.CharField(
        "必要業種区分", max_length=100, blank=True,
        help_text="例: 役務の提供等, 電気, 建築, 土木",
    )
    required_grade = models.CharField(
        "必要等級", max_length=10, blank=True,
        choices=[("A", "A等級"), ("B", "B等級"), ("C", "C等級"), ("D", "D等級")],
        help_text="この等級以上の資格が必要",
    )
    required_issuer_type = models.CharField(
        "資格種別", max_length=200, blank=True,
        help_text="例: 全省庁統一資格, 防衛省, 国土交通省, 千葉県",
    )

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
    """スクレイピング対象。i-ppi.jp または個別官公庁サイト。"""

    SITE_KEY_CHOICES = [
        ("ippi", "i-ppi.jp（入札情報サービス）"),
        ("shigaku", "私学事業団"),
        ("kanagawa_swf", "神奈川県下水道公社"),
        ("kanagawa_thk", "かながわ土地建物"),
    ]

    REGION_CHOICES = [
        ("北海道", "北海道"),
        ("東北", "東北"),
        ("関東", "関東"),
        ("北陸", "北陸"),
        ("中部", "中部"),
        ("近畿", "近畿"),
        ("中国", "中国"),
        ("四国", "四国"),
        ("九州・沖縄", "九州・沖縄"),
    ]

    KOJI_KBN_CHOICES = [
        ("一般土木工事", "一般土木工事"),
        ("アスファルト舗装工事", "アスファルト舗装工事"),
        ("鋼橋上部工事", "鋼橋上部工事"),
        ("造園工事", "造園工事"),
        ("建築工事", "建築工事"),
        ("木造建築工事", "木造建築工事"),
        ("電気設備工事", "電気設備工事"),
        ("暖冷房衛生設備工事", "暖冷房衛生設備工事"),
        ("セメント・コンクリート舗装工事", "セメント・コンクリート舗装工事"),
        ("プレストレスト・コンクリート工事", "プレストレスト・コンクリート工事"),
        ("法面処理工事", "法面処理工事"),
        ("塗装工事", "塗装工事"),
        ("維持修繕工事", "維持修繕工事"),
        ("浚渫工事", "浚渫工事"),
        ("グラウト工事", "グラウト工事"),
        ("杭打工事", "杭打工事"),
        ("さく井工事", "さく井工事"),
        ("プレハブ建築工事", "プレハブ建築工事"),
        ("機械設備工事", "機械設備工事"),
        ("通信設備工事", "通信設備工事"),
        ("受変電設備工事", "受変電設備工事"),
        ("港湾土木工事", "港湾土木工事"),
        ("農林土木工事", "農林土木工事"),
        ("農林建築工事", "農林建築工事"),
        ("橋梁補修工事", "橋梁補修工事"),
        ("その他", "その他"),
    ]

    KOJI_GYOSYU_CHOICES = [
        ("土木一式工事", "土木一式工事"),
        ("建築一式工事", "建築一式工事"),
        ("大工工事", "大工工事"),
        ("左官工事", "左官工事"),
        ("とび・土工・コンクリート工事", "とび・土工・コンクリート工事"),
        ("石工事", "石工事"),
        ("屋根工事", "屋根工事"),
        ("電気工事", "電気工事"),
        ("管工事", "管工事"),
        ("タイル・れんが・ブロック工事", "タイル・れんが・ブロック工事"),
        ("鋼構造物工事", "鋼構造物工事"),
        ("鉄筋工事", "鉄筋工事"),
        ("舗装工事", "舗装工事"),
        ("浚渫工事", "浚渫工事"),
        ("板金工事", "板金工事"),
        ("ガラス工事", "ガラス工事"),
        ("塗装工事", "塗装工事"),
        ("防水工事", "防水工事"),
        ("内装仕上工事", "内装仕上工事"),
        ("機械器具設置工事", "機械器具設置工事"),
        ("熱絶縁工事", "熱絶縁工事"),
        ("電気通信工事", "電気通信工事"),
        ("造園工事", "造園工事"),
        ("さく井工事", "さく井工事"),
        ("建具工事", "建具工事"),
        ("水道施設工事", "水道施設工事"),
        ("消防施設工事", "消防施設工事"),
        ("清掃施設工事", "清掃施設工事"),
        ("解体工事", "解体工事"),
        ("その他", "その他"),
    ]

    name = models.CharField("名称", max_length=200)
    url = models.URLField("URL", max_length=500, blank=True)
    site_key = models.CharField(
        "サイト識別子",
        max_length=30,
        choices=SITE_KEY_CHOICES,
        blank=True,
        help_text="スクレイパーの選択に使用。i-ppi が基本",
    )

    # i-ppi 検索条件
    keyword = models.CharField(
        "工事名キーワード", max_length=200, blank=True,
    )
    region = models.CharField(
        "地域（地方）", max_length=100, blank=True,
        choices=REGION_CHOICES,
    )
    prefecture = models.CharField(
        "都道府県", max_length=50, blank=True,
        help_text="地域を選んだときだけ有効",
    )
    koji_kbn = models.CharField(
        "工事区分", max_length=50, blank=True,
        choices=KOJI_KBN_CHOICES,
        help_text="発注工事の区分。例: 電気設備工事, 受変電設備工事",
    )
    koji_gyosyu = models.CharField(
        "業種", max_length=50, blank=True,
        choices=KOJI_GYOSYU_CHOICES,
        help_text="建設業許可の業種区分。例: 電気工事, 電気通信工事",
    )
    days_back = models.IntegerField(
        "過去N日以内", default=30,
        help_text="最終更新日が過去N日以内の案件を検索",
    )

    # 汎用フィールド
    category = models.CharField(
        "工事種別（旧）", max_length=100, blank=True,
        help_text="非推奨。工事区分／業種を使う",
    )
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
