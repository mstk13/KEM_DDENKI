from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel

# --- 工事種別の取得対象 --------------------------------------------------
# i-ppi の「工事区分／工事種別」は発注機関ごとの自由記述で、
# 「建築工事及び土木工事」「建築一式工事（電気設備工事、機械設備工事含む。）」の
# ように複数種別が1つの文字列に入る。よって完全一致ではなく部分一致で判定する。
EXCLUDED_CATEGORY_KEYWORDS = (
    "一般土木工事",
    "土木工事",
    "アスファルト舗装工事",
    "セメント・コンクリート舗装工事",
)

# 除外語を含んでいても取得する語。自社の施工対象が含まれる案件を捨てないため。
# 例:「建築一式工事（電気設備工事、機械設備工事含む。）」
INCLUDED_CATEGORY_KEYWORDS = (
    "電気設備工事",
    "機械設備工事",
)


def is_excluded_category(category: str) -> bool:
    """工事種別が取得対象外かどうかを返す。

    除外語を含んでいても、自社対象（電気設備工事・機械設備工事）を含む場合は
    対象として残す。
    """
    if not category:
        return False
    if any(k in category for k in INCLUDED_CATEGORY_KEYWORDS):
        return False
    return any(k in category for k in EXCLUDED_CATEGORY_KEYWORDS)


def _selectable(names: list[str]) -> list[tuple[str, str]]:
    """i-ppi の選択肢から取得対象外のものを落として choices にする。

    検索条件の選択肢と取り込み時のフィルタが食い違うと、
    選べるのに1件も保存されない条件ができてしまうため、同じ判定を通す。
    """
    return [(n, n) for n in names if not is_excluded_category(n)]


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
    deadline = models.DateTimeField("入札期限", null=True, blank=True)
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
    source_url = models.URLField("情報源URL", max_length=500, blank=True)
    # 1案件に複数の公開文書がぶら下がる（公告・指名結果書・入札調書・積算内訳書…）。
    # 先頭が公告とは限らず、読めないこともあるので候補を全部持っておき、
    # 順に試して要件が読めたものを source_url にする。
    document_urls = models.TextField(
        "公開文書URL（候補）", blank=True,
        help_text="1行1URL。公告らしい順に並べる",
    )
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
    )
    notes = models.TextField("備考", blank=True)

    # --- 案件概要（i-ppi の詳細ページから取得） ---
    agency_dept = models.CharField("担当部・事務所", max_length=200, blank=True)
    location = models.CharField("工事場所", max_length=400, blank=True)
    bid_method = models.CharField("入札契約方式", max_length=200, blank=True)
    design_no = models.CharField("設計書番号", max_length=100, blank=True)
    announced_on = models.DateField("公告日", null=True, blank=True)
    opening_on = models.DateField("開札日", null=True, blank=True)
    electronic_bid = models.CharField("電子入札対象", max_length=50, blank=True)
    summary = models.TextField(
        "案件概要（取得原文）", blank=True,
        help_text="情報源の詳細ページの項目をそのまま保存したもの",
    )
    work_outline = models.TextField(
        "工事概要", blank=True,
        help_text="工事の内容・数量・工期など。公告や仕様書から転記する",
    )
    requirements = models.TextField(
        "参加要件", blank=True,
        help_text="入札参加資格・同種工事の実績・配置技術者などの要件。公告から転記する",
    )

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
    # 公告が求める等級は「B等級以上」（下限）とは限らず、
    # 国土交通省は「Ｂ等級又はＣ等級に認定されている者」と列挙で指定する。
    # 下限として大小比較すると、A等級しか持たない場合に誤って参加可と出る。
    required_grades = models.CharField(
        "必要等級（該当）", max_length=20, blank=True,
        help_text="公告が認定を求める等級。列挙のときは並べる。例: BC",
    )
    # 防衛省は等級ではなく点数で切る。
    # 「総合審査数値…が780点以上」「経営事項評価数値…が1,100点以上」
    required_score = models.IntegerField(
        "必要点数", null=True, blank=True,
        help_text="総合審査数値・経営事項評価数値の下限",
    )

    # 公告の別表から抽出した手続きスケジュール
    # [{"label": "申請書及び資料の受付期限", "datetime": "2026-08-07T15:00",
    #   "detail": "電子入札システムで提出"}, ...]
    bid_schedule = models.JSONField(
        "入札手続スケジュール", default=list, blank=True,
        help_text="公告の別表から抽出した各種期限と提出物",
    )

    # ガントチャート上での手直し。公告の項目ラベルをキーにする。
    # {"入札書の受領期限": {"kind": "deadline", "start": "2026-09-20",
    #                      "end": "2026-10-27"}}
    # kind は BidScheduleRule.Kind と同じ値。start / end は日付のみで、
    # 時刻（正午必着など）は公告から読んだ値をそのまま使う。
    # bid_schedule を上書きせず別に持つのは、公告を取り直しても
    # 手直しが消えないようにするため。
    schedule_overrides = models.JSONField(
        "手続きの扱い（案件別）", default=dict, blank=True,
        help_text="ガントチャート上で変更した項目の扱いと日付",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "入札案件"
        verbose_name_plural = "入札案件"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class BidScheduleRule(TenantModel):
    """公告の手続き項目を受注までの流れのどこに置くか、の会社共通の既定。

    公告のラベルは発注機関ごとに違う（「入札書の受領期限」「入札の締切」…）ので、
    bids.gantt が正規化した「段階」をキーにする。段階ごとに1件。

    案件単位の例外は BidProject.schedule_overrides で持ち、こちらより優先する。
    """

    class Kind(models.TextChoices):
        DEADLINE = "deadline", "締切（流れの一本道に入れる）"
        PERIOD = "period", "期間（並走する窓口）"
        HIDDEN = "hidden", "図に出さない"

    stage = models.CharField(
        "段階", max_length=100,
        help_text="例: 参加申請, 入札書提出, 開札・落札者決定",
    )
    kind = models.CharField(
        "扱い", max_length=20, choices=Kind.choices, default=Kind.DEADLINE,
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "手続きの扱い（会社既定）"
        verbose_name_plural = "手続きの扱い（会社既定）"
        ordering = ["stage"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "stage"],
                name="uniq_bid_schedule_rule_company_stage",
            ),
        ]

    def __str__(self):
        return f"{self.stage}: {self.get_kind_display()}"


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
        ("ippi", "i-ppi.jp（全国入札情報）"),
        ("shigaku", "私学事業団"),
        ("kanagawa_swf", "神奈川県下水道公社"),
        ("kanagawa_thk", "かながわ土地建物"),
        ("msdf_hokyuhonbu", "海自 補給本部"),
        ("msdf_yokosuka", "海自 横須賀基地"),
        ("msdf_chichijima", "海自 父島基地"),
        ("msdf_atsugi", "海自 厚木航空基地隊"),
        ("msdf_kansenpokyu", "海自 艦船補給処"),
        ("msdf_shimofusa", "海自 下総航空基地隊"),
        ("msdf_tateyama", "海自 館山航空基地隊"),
        ("asdf_yokota", "空自 横田基地"),
        ("asdf_meguro", "空自 目黒基地"),
        ("asdf_kumagaya", "空自 熊谷基地"),
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

    # i-ppi の「工事区分」プルダウンの全選択肢。取得対象外のものは
    # _selectable() が落とすので、この一覧は i-ppi の実物と同じ並びで持つ。
    KOJI_KBN_ALL = [
        "一般土木工事",
        "アスファルト舗装工事",
        "鋼橋上部工事",
        "造園工事",
        "建築工事",
        "木造建築工事",
        "電気設備工事",
        "暖冷房衛生設備工事",
        "セメント・コンクリート舗装工事",
        "プレストレスト・コンクリート工事",
        "法面処理工事",
        "塗装工事",
        "維持修繕工事",
        "浚渫工事",
        "グラウト工事",
        "杭打工事",
        "さく井工事",
        "プレハブ建築工事",
        "機械設備工事",
        "通信設備工事",
        "受変電設備工事",
        "港湾土木工事",
        "農林土木工事",
        "農林建築工事",
        "橋梁補修工事",
        "その他",
    ]
    KOJI_KBN_CHOICES = _selectable(KOJI_KBN_ALL)

    KOJI_GYOSYU_ALL = [
        "土木一式工事",
        "建築一式工事",
        "大工工事",
        "左官工事",
        "とび・土工・コンクリート工事",
        "石工事",
        "屋根工事",
        "電気工事",
        "管工事",
        "タイル・れんが・ブロック工事",
        "鋼構造物工事",
        "鉄筋工事",
        "舗装工事",
        "浚渫工事",
        "板金工事",
        "ガラス工事",
        "塗装工事",
        "防水工事",
        "内装仕上工事",
        "機械器具設置工事",
        "熱絶縁工事",
        "電気通信工事",
        "造園工事",
        "さく井工事",
        "建具工事",
        "水道施設工事",
        "消防施設工事",
        "清掃施設工事",
        "解体工事",
        "その他",
    ]
    KOJI_GYOSYU_CHOICES = _selectable(KOJI_GYOSYU_ALL)

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
        "巡回間隔（時間）", default=48,
        help_text="2日=48時間。cron は2日に1回実行",
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
