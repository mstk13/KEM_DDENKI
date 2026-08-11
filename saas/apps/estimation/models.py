"""積算アプリのモデル定義。

Phase 1: EstimationItem（品目マスタ）、ItemAlias（名寄せ）、Orderer（発注機関）
"""

from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class EstimationItem(TenantModel):
    """積算品目マスタ。

    発注者の積算体系に合わせた品目定義。
    materials.Material は社内購買カタログであり、別の視点。
    同一物理品目でも発注者の体系ごとに別レコードになりうる。
    Optional FK で社内材料マスタと紐付ける。
    """

    class Category(models.TextChoices):
        WIRE = "wire", "電線・ケーブル"
        CONDUIT = "conduit", "電線管"
        FITTING = "fitting", "配線器具"
        LIGHTING = "lighting", "照明器具"
        PANEL = "panel", "盤"
        EQUIPMENT = "equipment", "機器"
        MATERIAL = "material", "その他材料"
        LABOR = "labor", "労務"

    class Status(models.TextChoices):
        DRAFT = "draft", "下書き"
        REVIEWED = "reviewed", "レビュー済"
        APPROVED = "approved", "承認済"

    code = models.CharField("品目コード", max_length=100)
    canonical_name = models.CharField("正規名称", max_length=300)
    category = models.CharField(
        "区分",
        max_length=20,
        choices=Category.choices,
        default=Category.MATERIAL,
    )
    unit = models.CharField("単位", max_length=50)
    spec = models.JSONField(
        "仕様",
        default=dict,
        blank=True,
        help_text='例: {"voltage":"600V","type":"CV","cores":3,"size":"38sq"}',
    )
    standard_price = models.DecimalField(
        "参考単価",
        max_digits=14,
        decimal_places=0,
        null=True,
        blank=True,
    )
    material = models.ForeignKey(
        "materials.Material",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="estimation_items",
        verbose_name="社内材料マスタ",
    )
    work_type = models.ForeignKey(
        "masters.WorkType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="estimation_items",
        verbose_name="工種",
    )
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    is_active = models.BooleanField("有効", default=True)
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "積算品目"
        verbose_name_plural = "積算品目"
        unique_together = [("company", "code")]
        indexes = [
            models.Index(fields=["company", "category"]),
        ]

    def __str__(self):
        return f"{self.code} {self.canonical_name}"


class ItemAlias(TenantModel):
    """名寄せテーブル。異なるデータソースの品名を正規品目に紐付ける。

    このテーブルがシステムの中核。
    発注者の数量書、仕入先の見積書、積算基準書それぞれが
    異なる品名で同一品目を指している対応関係を管理する。
    """

    class SourceType(models.TextChoices):
        ORDERER_BOQ = "orderer_boq", "発注者数量書"
        SUPPLIER_QUOTE = "supplier_quote", "仕入先見積"
        OWN_MATERIAL = "own_material", "社内材料マスタ"
        STANDARD = "standard", "積算基準書"

    class MatchMethod(models.TextChoices):
        EXACT_CODE = "exact_code", "コード完全一致"
        NORMALIZED = "normalized", "正規化一致"
        SPEC_MATCH = "spec_match", "仕様一致"
        LLM = "llm", "AI推定"
        MANUAL = "manual", "手動"

    class Status(models.TextChoices):
        PENDING = "pending", "未確認"
        REVIEWED = "reviewed", "レビュー済"
        APPROVED = "approved", "承認済"
        REJECTED = "rejected", "却下"

    estimation_item = models.ForeignKey(
        EstimationItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="aliases",
        verbose_name="紐付先品目",
    )
    source_type = models.CharField(
        "ソース種別",
        max_length=30,
        choices=SourceType.choices,
    )
    source_key = models.CharField(
        "ソースキー",
        max_length=200,
        blank=True,
        help_text="元データの識別子（発注者コード、仕入先品番等）",
    )
    raw_name = models.CharField("原文名称", max_length=500)
    normalized_name = models.CharField(
        "正規化名称",
        max_length=500,
        blank=True,
        help_text="正規化ルール適用後の名称",
    )
    confidence = models.DecimalField(
        "信頼度",
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="0.00〜100.00",
    )
    matched_by = models.CharField(
        "マッチ方法",
        max_length=20,
        choices=MatchMethod.choices,
        default=MatchMethod.MANUAL,
    )
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="レビュー者",
    )
    reviewed_at = models.DateTimeField("レビュー日時", null=True, blank=True)
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "名寄せ"
        verbose_name_plural = "名寄せ"
        unique_together = [("company", "source_type", "source_key", "raw_name")]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["company", "normalized_name"]),
        ]

    def __str__(self):
        return f"[{self.get_source_type_display()}] {self.raw_name}"


class Orderer(TenantModel):
    """発注機関マスタ。公共工事の発注者（国交省、都道府県、市町村等）。

    masters.Customer とは別概念。Customer は自社の取引先全般。
    Orderer は積算基準を持つ公共発注機関に特化したモデル。
    """

    class Kind(models.TextChoices):
        NATIONAL = "national", "国"
        PREFECTURE = "prefecture", "都道府県"
        CITY = "city", "市区町村"
        PUBLIC_CORP = "public_corp", "公団・公社"
        OTHER = "other", "その他"

    class SystemType(models.TextChoices):
        EIZEN = "eizen", "営繕系"
        DOBOKU = "doboku", "土木系"
        BOTH = "both", "両方"

    code = models.CharField("コード", max_length=50, blank=True)
    name = models.CharField("発注機関名", max_length=200)
    kind = models.CharField(
        "機関種別",
        max_length=20,
        choices=Kind.choices,
        default=Kind.OTHER,
    )
    system_type = models.CharField(
        "積算体系",
        max_length=20,
        choices=SystemType.choices,
        default=SystemType.EIZEN,
    )
    prefecture = models.CharField("都道府県", max_length=10, blank=True)
    standard_url = models.URLField("積算基準URL", max_length=500, blank=True)
    customer = models.ForeignKey(
        "masters.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orderer_profiles",
        verbose_name="得意先マスタ",
    )
    is_active = models.BooleanField("有効", default=True)
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "発注機関"
        verbose_name_plural = "発注機関"
        unique_together = [("company", "name")]

    def __str__(self):
        return self.name


class OrdererDataSource(TenantModel):
    """発注機関ごとのデータソース管理。

    官公庁ごとに「どのデータが共通で、どのデータが独自か」を
    一覧管理するためのテーブル。メンテナンス時の参照用。

    例: 国交省は歩掛・共通費率が全国共通だが、
        防衛省は独自歩掛を持つ。神奈川県は設計単価表が独自。
    """

    class DataCategory(models.TextChoices):
        LABOR_RATE = "labor_rate", "設計労務単価"
        WORK_RATE = "work_rate", "歩掛"
        OVERHEAD = "overhead", "共通費率"
        UNIT_PRICE = "unit_price", "設計単価"
        BOQ_FORMAT = "boq_format", "内訳書様式"
        QUANTITY_RULE = "quantity_rule", "数量積算基準"
        SPECIAL = "special", "特記・積算条件"

    class Scope(models.TextChoices):
        COMMON = "common", "国共通（国交省基準準拠）"
        ORDERER_OWN = "orderer_own", "独自基準あり"
        PARTIAL = "partial", "一部独自（国基準+独自補足）"
        UNKNOWN = "unknown", "未確認"

    class UpdateCycle(models.TextChoices):
        ANNUAL_MAR = "annual_mar", "年次（3月公表）"
        ANNUAL_APR = "annual_apr", "年次（4月改定）"
        BIANNUAL = "biannual", "半期"
        IRREGULAR = "irregular", "不定期"
        UNKNOWN = "unknown", "未確認"

    class DataFormat(models.TextChoices):
        PDF = "pdf", "PDF"
        EXCEL = "excel", "Excel"
        WEB = "web", "Webページ"
        BOOK = "book", "書籍・冊子"
        PAID_DB = "paid_db", "有償データベース"
        OTHER = "other", "その他"

    orderer = models.ForeignKey(
        Orderer,
        on_delete=models.CASCADE,
        related_name="data_sources",
        verbose_name="発注機関",
    )
    category = models.CharField(
        "データ区分",
        max_length=30,
        choices=DataCategory.choices,
    )
    scope = models.CharField(
        "適用範囲",
        max_length=20,
        choices=Scope.choices,
        default=Scope.UNKNOWN,
        help_text="国交省の共通基準に準拠しているか、独自基準があるか",
    )
    name = models.CharField(
        "データソース名",
        max_length=200,
        help_text="例: 防衛省独自歩掛、神奈川県設計単価表",
    )
    source_url = models.URLField("公開URL", max_length=500, blank=True)
    update_cycle = models.CharField(
        "更新頻度",
        max_length=20,
        choices=UpdateCycle.choices,
        default=UpdateCycle.UNKNOWN,
    )
    data_format = models.CharField(
        "提供形式",
        max_length=20,
        choices=DataFormat.choices,
        default=DataFormat.PDF,
    )
    is_free = models.BooleanField(
        "無償公開",
        default=True,
        help_text="有償の場合はFalse",
    )
    fiscal_year = models.IntegerField(
        "最新取得年度",
        null=True,
        blank=True,
        help_text="西暦（例: 2026）",
    )
    last_checked_at = models.DateField(
        "最終確認日",
        null=True,
        blank=True,
    )
    diff_summary = models.TextField(
        "共通基準との違い",
        blank=True,
        help_text="国交省基準と異なる点を記載。独自基準がある場合は必ず書く",
    )
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "データソース"
        verbose_name_plural = "データソース"
        unique_together = [("company", "orderer", "category")]
        ordering = ["orderer", "category"]

    def __str__(self):
        return f"{self.orderer.name} / {self.get_category_display()}"


# ===================================================================
# M2: 労務単価・積算基準・歩掛・共通費
# ===================================================================


class LaborRate(TenantModel):
    """公共工事設計労務単価。

    国交省が毎年3月に公表する都道府県別・職種別の労務単価。
    全発注者共通で使われる基礎データ。
    """

    prefecture = models.CharField("都道府県", max_length=10)
    trade = models.CharField(
        "職種",
        max_length=50,
        help_text="例: 電工、普通作業員、特殊作業員",
    )
    fiscal_year = models.IntegerField(
        "年度",
        help_text="西暦の開始年（令和8年度→2026）",
    )
    amount = models.DecimalField(
        "単価（円/人日）",
        max_digits=14,
        decimal_places=0,
    )
    source_url = models.URLField("出典URL", max_length=500, blank=True)
    import_batch = models.CharField(
        "インポートバッチ",
        max_length=100,
        blank=True,
        help_text="どのインポート処理で投入されたかの追跡用",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "設計労務単価"
        verbose_name_plural = "設計労務単価"
        unique_together = [("company", "prefecture", "trade", "fiscal_year")]
        indexes = [
            models.Index(fields=["company", "fiscal_year"]),
            models.Index(fields=["company", "prefecture", "trade"]),
        ]

    def __str__(self):
        return f"{self.fiscal_year} {self.prefecture} {self.trade} {self.amount}円"


class EstimationStandard(TenantModel):
    """積算基準。発注者ごと・年度ごとの基準文書を管理する。

    PDF等の原本を保存し、そこから抽出した歩掛・共通費率を
    WorkRate / OverheadRule で管理する。
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "下書き"
        REVIEWED = "reviewed", "レビュー済"
        APPROVED = "approved", "承認済"

    orderer = models.ForeignKey(
        Orderer,
        on_delete=models.CASCADE,
        related_name="standards",
        verbose_name="発注機関",
    )
    name = models.CharField(
        "基準名",
        max_length=200,
        help_text="例: 公共建築工事積算基準 令和8年版",
    )
    fiscal_year = models.IntegerField("年度")
    source_url = models.URLField("出典URL", max_length=500, blank=True)
    source_file = models.FileField(
        "原本ファイル",
        upload_to="estimation/standards/",
        blank=True,
    )
    source_hash = models.CharField(
        "ファイルハッシュ",
        max_length=64,
        blank=True,
        help_text="差分検知用（SHA-256）",
    )
    effective_from = models.DateField("適用開始日", null=True, blank=True)
    effective_to = models.DateField("適用終了日", null=True, blank=True)
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "積算基準"
        verbose_name_plural = "積算基準"
        unique_together = [("company", "orderer", "name", "fiscal_year")]

    def __str__(self):
        return f"{self.orderer.name} {self.name} ({self.fiscal_year})"


class WorkRate(TenantModel):
    """歩掛。作業内容ごとの標準人工数・材料使用量。

    積算基準から抽出される。AI抽出の場合は status=draft で投入し、
    人間のレビュー後に approved にする。
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "下書き"
        REVIEWED = "reviewed", "レビュー済"
        APPROVED = "approved", "承認済"

    class ExtractedBy(models.TextChoices):
        AI = "ai", "AI抽出"
        MANUAL = "manual", "手入力"

    standard = models.ForeignKey(
        EstimationStandard,
        on_delete=models.CASCADE,
        related_name="work_rates",
        verbose_name="積算基準",
    )
    work_code = models.CharField("作業コード", max_length=50, blank=True)
    work_name = models.CharField(
        "作業名",
        max_length=200,
        help_text="例: ケーブル配線 CV 38sq以下",
    )
    unit = models.CharField("単位", max_length=50, help_text="例: m, 個, 箇所")
    labor = models.JSONField(
        "労務",
        default=list,
        blank=True,
        help_text='例: [{"trade":"電工","qty":0.12},{"trade":"普通作業員","qty":0.05}]',
    )
    material = models.JSONField(
        "材料",
        default=list,
        blank=True,
        help_text='例: [{"name":"雑材料","rate":0.03}]',
    )
    remarks = models.TextField("摘要", blank=True)
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    extracted_by = models.CharField(
        "抽出方法",
        max_length=10,
        choices=ExtractedBy.choices,
        default=ExtractedBy.MANUAL,
    )
    source_page = models.IntegerField(
        "出典ページ",
        null=True,
        blank=True,
        help_text="レビュー時にPDFと並べて表示するため",
    )
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "歩掛"
        verbose_name_plural = "歩掛"
        ordering = ["standard", "work_code"]

    def __str__(self):
        return f"{self.work_name} ({self.unit})"


class OverheadRule(TenantModel):
    """共通費率。共通仮設費・現場管理費・一般管理費等の計算式。

    共通費率は工事価格・工期に対する対数式等で定義されるため、
    単純な率ではなく式のまま保持する。
    式の評価は eval を使わず、安全な数式パーサで行う。
    """

    class Category(models.TextChoices):
        TEMPORARY = "temporary", "共通仮設費"
        SITE_MGMT = "site_mgmt", "現場管理費"
        GENERAL = "general", "一般管理費等"

    class Status(models.TextChoices):
        DRAFT = "draft", "下書き"
        REVIEWED = "reviewed", "レビュー済"
        APPROVED = "approved", "承認済"

    standard = models.ForeignKey(
        EstimationStandard,
        on_delete=models.CASCADE,
        related_name="overhead_rules",
        verbose_name="積算基準",
    )
    category = models.CharField(
        "費目",
        max_length=20,
        choices=Category.choices,
    )
    work_type_label = models.CharField(
        "工事種別",
        max_length=50,
        help_text="例: 電気設備, 機械設備, 昇降機設備",
    )
    formula = models.TextField(
        "計算式",
        help_text="例: rate = 27.354 * pow(direct_cost / 1000, -0.0871)"
                  " ※eval不使用、専用パーサで評価",
    )
    params = models.JSONField(
        "パラメータ",
        default=dict,
        blank=True,
        help_text='係数・適用範囲・上下限。例: {"min_cost":1000000,"max_rate":0.15}',
    )
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "共通費率"
        verbose_name_plural = "共通費率"
        unique_together = [("company", "standard", "category", "work_type_label")]

    def __str__(self):
        return f"{self.get_category_display()} ({self.work_type_label})"
