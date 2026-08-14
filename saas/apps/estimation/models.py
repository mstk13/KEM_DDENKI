"""積算アプリのモデル定義。

Phase 1: EstimationItem, ItemAlias, Orderer, OrdererDataSource
M2+S修正: LaborRate, EstimationStandard, WorkRate, OverheadRule, WageFloor
"""

from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel

# ===================================================================
# S4: データ所有区分 Mixin
# ===================================================================


class DataScopeMixin(models.Model):
    """データ所有区分。外販時にレコードの仕分けを可能にする。

    判断基準:
    - public: 国が決めたもの（無償公開データ）
    - licensed: 金を払って買ったもの（有償・許諾必要・製品同梱不可）
    - tenant: 会社が決めたもの（テナント固有の資産）
    """

    DATA_SCOPE_CHOICES = [
        ("public", "公的データ（無償・再配布可）"),
        ("licensed", "購入データ（有償・許諾必要・同梱不可）"),
        ("tenant", "テナント固有データ"),
    ]
    data_scope = models.CharField(
        "データ所有区分",
        max_length=16,
        choices=DATA_SCOPE_CHOICES,
        default="tenant",
        db_index=True,
    )
    source_license = models.CharField(
        "出典・ライセンス",
        max_length=128,
        blank=True,
        help_text="licensed の場合、出典と契約を記録。例: 建築コスト情報 2026年8月号",
    )

    class Meta:
        abstract = True


# ===================================================================
# Phase 1: 品目マスタ・名寄せ・発注機関
# ===================================================================


class EstimationItem(DataScopeMixin, TenantModel):
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


class ItemEmbedding(TenantModel):
    """積算品目の埋め込みベクトル（ADR-0010 層A）。

    EstimationItem 本体ではなく別テーブルに置く。
    EstimationItem は simple-history 対象なので、1,024次元のベクトルを
    直接持たせると品目を編集するたび履歴行にベクトルが複製され、
    履歴テーブルが不必要に肥大するため。

    再生成可能な派生データであり、業務データではない。
    そのため history からは vector を除外している（規律4の趣旨に沿って
    履歴自体は残し、監査に意味のあるメタ情報だけを追跡する）。

    DataScopeMixin は付けない。所有区分は親の EstimationItem に従う。
    """

    estimation_item = models.OneToOneField(
        EstimationItem,
        on_delete=models.CASCADE,
        related_name="embedding",
        verbose_name="積算品目",
    )
    vector = models.JSONField(
        "埋め込みベクトル",
        default=list,
        help_text="float のリスト。bge-m3 は 1,024 次元。",
    )
    model_tag = models.CharField(
        "生成モデル",
        max_length=100,
        help_text="例: bge-m3。モデルを変えたら再生成が必要。",
    )
    dim = models.PositiveIntegerField("次元数", default=0)
    source_text = models.CharField(
        "埋め込み対象テキスト",
        max_length=500,
        help_text="実際にベクトル化した文字列。canonical_name とは限らない。",
    )
    source_hash = models.CharField(
        "対象テキストのハッシュ",
        max_length=64,
        db_index=True,
        help_text="sha256。品目名が変わったことを検知して再生成するために使う。",
    )

    history = HistoricalRecords(excluded_fields=["vector"])

    class Meta:
        verbose_name = "品目埋め込み"
        verbose_name_plural = "品目埋め込み"
        indexes = [
            models.Index(fields=["company", "model_tag"]),
        ]

    def __str__(self):
        return f"{self.estimation_item_id} ({self.model_tag}, {self.dim}d)"

    def is_stale(self, source_text: str, model_tag: str) -> bool:
        """対象テキストまたはモデルが変わっていれば True。"""
        import hashlib

        current = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        return self.source_hash != current or self.model_tag != model_tag


class ItemAlias(DataScopeMixin, TenantModel):
    """名寄せテーブル。異なるデータソースの品名を正規品目に紐付ける。

    このテーブルがシステムの中核であり、かつテナント固有の資産。
    data_scope は原則 'tenant'。他テナントへ漏らしてはならない。
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
        EMBEDDING = "embedding", "類似度一致"
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
    category = models.CharField("データ区分", max_length=30, choices=DataCategory.choices)
    scope = models.CharField(
        "適用範囲", max_length=20, choices=Scope.choices, default=Scope.UNKNOWN,
    )
    name = models.CharField("データソース名", max_length=200)
    source_url = models.URLField("公開URL", max_length=500, blank=True)
    update_cycle = models.CharField(
        "更新頻度", max_length=20, choices=UpdateCycle.choices, default=UpdateCycle.UNKNOWN,
    )
    data_format = models.CharField(
        "提供形式", max_length=20, choices=DataFormat.choices, default=DataFormat.PDF,
    )
    is_free = models.BooleanField("無償公開", default=True)
    fiscal_year = models.IntegerField("最新取得年度", null=True, blank=True)
    last_checked_at = models.DateField("最終確認日", null=True, blank=True)
    diff_summary = models.TextField("共通基準との違い", blank=True)
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
# M2+S2: 労務単価（有効期間管理）
# ===================================================================


class LaborRate(DataScopeMixin, TenantModel):
    """公共工事設計労務単価。

    国交省が毎年3月に公表。PDFのみで配布（Excelなし）。
    年度キーではなく valid_from/valid_to で管理する（S2）。
    同一年度内でも2月と3月で単価が異なるケースに対応するため。
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "下書き"
        REVIEWED = "reviewed", "レビュー済"
        APPROVED = "approved", "承認済"

    prefecture = models.CharField("都道府県", max_length=10, db_index=True)
    occupation_code = models.CharField(
        "職種コード", max_length=16, db_index=True, blank=True,
    )
    occupation_name = models.CharField("職種名", max_length=64)

    unit_price = models.DecimalField(
        "単価（円/人日）",
        max_digits=14,
        decimal_places=0,
        null=True,
        blank=True,
        help_text="未設定職種はNULL。0を入れないこと",
    )

    # S2: 年度キーを廃止し、有効期間で管理
    valid_from = models.DateField("適用開始日", db_index=True)
    valid_to = models.DateField("適用終了日", null=True, blank=True, db_index=True)

    # 参考情報としての年度表記（引き当てキーにしない）
    fiscal_year_label = models.CharField(
        "年度表記",
        max_length=32,
        blank=True,
        help_text="表示用。例: 令和8年3月適用。引き当てには使わない",
    )

    status = models.CharField(
        "状態", max_length=20, choices=Status.choices, default=Status.DRAFT,
    )
    import_batch = models.CharField("インポートバッチ", max_length=100, blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "設計労務単価"
        verbose_name_plural = "設計労務単価"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "prefecture", "occupation_code", "valid_from"],
                name="uniq_labor_rate_period",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "prefecture", "occupation_code", "valid_from"]),
        ]

    def __str__(self):
        price = f"{self.unit_price}円" if self.unit_price else "未設定"
        return f"{self.valid_from} {self.prefecture} {self.occupation_name} {price}"


# ===================================================================
# M2+S2+S3: 積算基準・歩掛・共通費
# ===================================================================


class EstimationStandard(DataScopeMixin, TenantModel):
    """積算基準。発注者ごとの基準文書を管理する。

    S2: valid_from/valid_to + applies_by で有効期間を管理。
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "下書き"
        REVIEWED = "reviewed", "レビュー済"
        APPROVED = "approved", "承認済"

    class AppliesBy(models.TextChoices):
        BID_ANNOUNCEMENT = "bid_announcement", "入札公告日"
        CONTRACT_DATE = "contract_date", "契約日"
        ESTIMATE_DATE = "estimate_date", "積算日"

    orderer = models.ForeignKey(
        Orderer,
        on_delete=models.PROTECT,
        related_name="standards",
        verbose_name="発注機関",
    )
    name = models.CharField(
        "基準名", max_length=200,
        help_text="例: 公共建築工事積算基準 令和8年版",
    )
    # S2: 有効期間管理
    valid_from = models.DateField("適用開始日", db_index=True)
    valid_to = models.DateField("適用終了日", null=True, blank=True)
    applies_by = models.CharField(
        "適用起点",
        max_length=24,
        choices=AppliesBy.choices,
        default=AppliesBy.BID_ANNOUNCEMENT,
        help_text="発注者により起点が異なる。これがないと正しく引けない",
    )
    # 参考
    fiscal_year_label = models.CharField(
        "年度表記", max_length=32, blank=True,
    )
    source_url = models.URLField("出典URL", max_length=500, blank=True)
    source_file = models.FileField(
        "原本ファイル", upload_to="estimation/standards/", blank=True,
    )
    source_hash = models.CharField(
        "ファイルハッシュ", max_length=64, blank=True,
        help_text="差分検知用（SHA-256）",
    )
    status = models.CharField(
        "状態", max_length=20, choices=Status.choices, default=Status.DRAFT,
    )
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "積算基準"
        verbose_name_plural = "積算基準"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "orderer", "name", "valid_from"],
                name="uniq_standard_period",
            ),
        ]

    def __str__(self):
        return f"{self.orderer.name} {self.name} ({self.valid_from})"


class WorkRate(DataScopeMixin, TenantModel):
    """歩掛。作業内容ごとの標準人工数・材料使用量。

    AI抽出の場合は status=draft で投入し、人間レビュー後に approved。
    approved 以外は積算計算に使わない。
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
    work_name = models.CharField("作業名", max_length=200)
    unit = models.CharField("単位", max_length=50)
    labor = models.JSONField(
        "労務", default=list, blank=True,
        help_text='例: [{"trade":"電工","qty":0.12}]',
    )
    material = models.JSONField(
        "材料", default=list, blank=True,
        help_text='例: [{"name":"雑材料","rate":0.03}]',
    )
    remarks = models.TextField("摘要", blank=True)
    status = models.CharField(
        "状態", max_length=20, choices=Status.choices, default=Status.DRAFT,
    )
    extracted_by = models.CharField(
        "抽出方法", max_length=10, choices=ExtractedBy.choices, default=ExtractedBy.MANUAL,
    )
    source_page = models.IntegerField("出典ページ", null=True, blank=True)
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "歩掛"
        verbose_name_plural = "歩掛"
        ordering = ["standard", "work_code"]

    def __str__(self):
        return f"{self.work_name} ({self.unit})"


class OverheadRule(DataScopeMixin, TenantModel):
    """共通費率。共通仮設費・現場管理費・一般管理費等の計算式。

    S3: 建築設備系の体系に合わせる。
    - work_category で工事種別を管理（一括発注時は種別ごとに算定して合計）
    - revision_date + valid_from/valid_to で有効期間管理
    - 令和8年3月11日改定で一般管理費等率の算定式がまとめられた点に注意
    """

    class WorkCategory(models.TextChoices):
        BUILDING = "building", "建築工事"
        ELECTRICAL = "electrical", "電気設備工事"
        MECHANICAL = "mechanical", "機械設備工事"
        ELEVATOR = "elevator", "昇降機設備工事"

    class CostType(models.TextChoices):
        COMMON_TEMP = "common_temp", "共通仮設費"
        SITE_MGMT = "site_mgmt", "現場管理費"
        GENERAL_ADMIN = "general_admin", "一般管理費等"

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
    work_category = models.CharField(
        "工事種別",
        max_length=16,
        choices=WorkCategory.choices,
        db_index=True,
    )
    cost_type = models.CharField(
        "費目",
        max_length=16,
        choices=CostType.choices,
    )
    formula = models.TextField(
        "計算式",
        help_text="evalは使わない。専用パーサで評価する",
    )
    formula_params = models.JSONField(
        "パラメータ",
        default=dict,
        blank=True,
        help_text='係数・適用範囲・上下限',
    )
    revision_date = models.DateField(
        "改定日",
        null=True,
        blank=True,
        help_text="例: 2026-03-11",
    )
    valid_from = models.DateField("適用開始日", db_index=True, null=True, blank=True)
    valid_to = models.DateField("適用終了日", null=True, blank=True)
    status = models.CharField(
        "状態", max_length=20, choices=Status.choices, default=Status.DRAFT,
    )
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "共通費率"
        verbose_name_plural = "共通費率"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "standard", "work_category", "cost_type"],
                name="uniq_overhead_rule",
            ),
        ]

    def __str__(self):
        return f"{self.get_cost_type_display()} ({self.get_work_category_display()})"


# ===================================================================
# S6: 公契約条例 労働報酬下限額
# ===================================================================


class WageFloor(TenantModel):
    """公契約条例に基づく労働報酬下限額。

    労務単価とは別概念で遵守義務がある。
    M4 の CostComparison で下限割れを機械的に検証する。
    """

    class WorkerType(models.TextChoices):
        REGULAR = "regular", "一般"
        TRAINEE = "trainee", "見習い労働者等"

    municipality = models.CharField("自治体名", max_length=32, db_index=True)
    occupation_code = models.CharField("職種コード", max_length=16, blank=True)
    occupation_name = models.CharField("職種名", max_length=64, blank=True)
    hourly_floor = models.DecimalField(
        "下限額（円/時間）", max_digits=8, decimal_places=0,
    )
    worker_type = models.CharField(
        "労働者種別",
        max_length=16,
        choices=WorkerType.choices,
        default=WorkerType.REGULAR,
    )
    superseded_by_minimum_wage = models.BooleanField(
        "最低賃金による上書き",
        default=False,
        help_text="地域別最低賃金の改正で、条例下限より最低賃金が上回る期間",
    )
    valid_from = models.DateField("適用開始日", db_index=True)
    valid_to = models.DateField("適用終了日", null=True, blank=True)
    ordinance_ref = models.CharField("条例参照", max_length=128, blank=True)
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "労働報酬下限額"
        verbose_name_plural = "労働報酬下限額"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "municipality", "occupation_code", "worker_type", "valid_from"],
                name="uniq_wage_floor_period",
            ),
        ]

    def __str__(self):
        return f"{self.municipality} {self.occupation_name} {self.hourly_floor}円/h"


# ===================================================================
# M3: 積算案件・内訳書
# ===================================================================


class EstimationProject(TenantModel):
    """積算案件。sites.Site のラッパーで積算固有の属性を持つ。

    Site は施工管理の視点、EstimationProject は積算の視点。
    落札前は Site が存在しない場合もある。
    """

    class Status(models.TextChoices):
        PLANNING = "planning", "検討中"
        ESTIMATING = "estimating", "積算中"
        BID = "bid", "応札済"
        WON = "won", "落札"
        LOST = "lost", "失注"
        SKIPPED = "skipped", "見送り"

    class PrimaryWorkCategory(models.TextChoices):
        BUILDING = "building", "建築工事"
        ELECTRICAL = "electrical", "電気設備工事"
        MECHANICAL = "mechanical", "機械設備工事"
        ELEVATOR = "elevator", "昇降機設備工事"

    name = models.CharField("案件名", max_length=200)
    orderer = models.ForeignKey(
        Orderer, on_delete=models.PROTECT,
        related_name="estimation_projects", verbose_name="発注機関",
    )
    standard = models.ForeignKey(
        EstimationStandard, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="projects",
        verbose_name="適用積算基準",
    )
    site = models.ForeignKey(
        "sites.Site", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="estimation_projects",
        verbose_name="現場",
    )
    bid_project = models.ForeignKey(
        "bids.BidProject", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="estimation_projects",
        verbose_name="入札案件",
    )
    primary_work_category = models.CharField(
        "主たる工事種別",
        max_length=16,
        choices=PrimaryWorkCategory.choices,
        default=PrimaryWorkCategory.ELECTRICAL,
    )
    status = models.CharField(
        "状態", max_length=20, choices=Status.choices, default=Status.PLANNING,
    )
    bid_announcement_date = models.DateField("入札公告日", null=True, blank=True)
    bid_opening_date = models.DateField(
        "開札予定日", null=True, blank=True,
        help_text="現場管理費率算定のT（工期）の起点",
    )
    construction_period_days = models.IntegerField(
        "工期（日）", null=True, blank=True,
    )
    bid_amount = models.DecimalField(
        "応札額", max_digits=14, decimal_places=0, null=True, blank=True,
    )
    award_amount = models.DecimalField(
        "落札額", max_digits=14, decimal_places=0, null=True, blank=True,
    )
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "積算案件"
        verbose_name_plural = "積算案件"

    def __str__(self):
        return self.name


class BoqLine(TenantModel):
    """内訳書明細。公共建築工事内訳書標準書式の階層構造。

    S5: 階層名は標準書式に準拠（種目別→科目別→中科目別→細目別）。
    parent FK による自己参照ツリー。
    """

    class Level(models.TextChoices):
        SHUMOKU = "shumoku", "種目別内訳書"
        KAMOKU = "kamoku", "科目別内訳書"
        CHUKAMOKU = "chukamoku", "中科目別内訳書"
        SAIMOKU = "saimoku", "細目別内訳書"

    project = models.ForeignKey(
        EstimationProject, on_delete=models.CASCADE,
        related_name="boq_lines", verbose_name="積算案件",
    )
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE,
        null=True, blank=True, related_name="children",
        verbose_name="親明細",
    )
    level = models.CharField(
        "階層", max_length=16, choices=Level.choices,
    )
    sort_order = models.IntegerField("表示順", default=0)
    name = models.CharField("名称", max_length=200)
    spec = models.CharField("仕様", max_length=300, blank=True)
    unit = models.CharField("単位", max_length=50, blank=True)
    quantity = models.DecimalField(
        "数量", max_digits=14, decimal_places=3, null=True, blank=True,
    )
    unit_price = models.DecimalField(
        "単価", max_digits=14, decimal_places=0, null=True, blank=True,
    )
    amount = models.DecimalField(
        "金額", max_digits=14, decimal_places=0, null=True, blank=True,
    )
    estimation_item = models.ForeignKey(
        EstimationItem, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="boq_lines",
        verbose_name="積算品目",
    )
    work_rate = models.ForeignKey(
        WorkRate, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="boq_lines",
        verbose_name="歩掛",
    )
    remarks = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "内訳書明細"
        verbose_name_plural = "内訳書明細"
        ordering = ["project", "sort_order"]

    def __str__(self):
        return f"[{self.get_level_display()}] {self.name}"

    def calc_amount(self):
        """数量×単価で金額を計算する。"""
        if self.quantity is not None and self.unit_price is not None:
            self.amount = self.quantity * self.unit_price
        return self.amount


# ===================================================================
# M4: 差分分析
# ===================================================================


class PurchaseRecord(DataScopeMixin, TenantModel):
    """仕入実績。問屋の請求書・納品書から投入する。

    raw_name と raw_code は必ず保持する。
    名寄せは後から何度でもやり直せる必要がある。
    """

    class ImportSource(models.TextChoices):
        MANUAL = "manual", "手入力"
        CSV = "csv", "CSV"
        OCR = "ocr", "OCR"
        EDI = "edi", "EDI"

    supplier = models.ForeignKey(
        "masters.Supplier", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="estimation_purchases",
        verbose_name="仕入先",
    )
    estimation_item = models.ForeignKey(
        EstimationItem, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="purchase_records",
        verbose_name="積算品目（名寄せ後）",
    )
    raw_name = models.CharField(
        "伝票上の表記", max_length=500,
        help_text="必ず保持。名寄せは後からやり直せる必要がある",
    )
    raw_code = models.CharField("問屋品番", max_length=200, blank=True)
    purchase_date = models.DateField("仕入日")
    quantity = models.DecimalField("数量", max_digits=14, decimal_places=3)
    unit = models.CharField("単位", max_length=50, blank=True)
    unit_price = models.DecimalField(
        "仕入単価（円）", max_digits=14, decimal_places=0,
    )
    amount = models.DecimalField(
        "金額（円）", max_digits=14, decimal_places=0,
        null=True, blank=True,
    )
    project = models.ForeignKey(
        EstimationProject, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="purchase_records",
        verbose_name="案件",
    )
    import_source = models.CharField(
        "投入方法", max_length=10, choices=ImportSource.choices,
        default=ImportSource.MANUAL,
    )
    import_batch = models.CharField("インポートバッチ", max_length=100, blank=True)
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "仕入実績"
        verbose_name_plural = "仕入実績"
        indexes = [
            models.Index(fields=["company", "purchase_date"]),
            models.Index(fields=["company", "estimation_item"]),
        ]

    def __str__(self):
        return f"{self.purchase_date} {self.raw_name} {self.unit_price}円"


class CostComparison(TenantModel):
    """差分分析。発注者基準単価 vs 自社仕入単価。

    このシステムの最終出力。
    「いくら安くできるか」ではなく「この案件の想定粗利」として設計。
    """

    project = models.ForeignKey(
        EstimationProject, on_delete=models.CASCADE,
        related_name="cost_comparisons", verbose_name="積算案件",
    )
    estimation_item = models.ForeignKey(
        EstimationItem, on_delete=models.CASCADE,
        related_name="cost_comparisons", verbose_name="積算品目",
    )
    quantity = models.DecimalField(
        "数量", max_digits=14, decimal_places=3, null=True, blank=True,
    )
    standard_price = models.DecimalField(
        "発注者基準単価（円）", max_digits=14, decimal_places=0,
        null=True, blank=True,
    )
    own_price = models.DecimalField(
        "自社仕入単価（円）", max_digits=14, decimal_places=0,
        null=True, blank=True,
    )
    own_price_basis = models.CharField(
        "算出根拠", max_length=200, blank=True,
        help_text="例: 直近6件の中央値、○○電材見積",
    )
    diff_amount = models.DecimalField(
        "差額（円）", max_digits=14, decimal_places=0,
        null=True, blank=True,
    )
    diff_ratio = models.DecimalField(
        "差率（%）", max_digits=7, decimal_places=2,
        null=True, blank=True,
    )
    calculated_at = models.DateTimeField("算出日時", auto_now=True)
    notes = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "差分分析"
        verbose_name_plural = "差分分析"
        unique_together = [("company", "project", "estimation_item")]

    def __str__(self):
        return f"{self.project.name} / {self.estimation_item.canonical_name}"

    def calc_diff(self):
        """差額・差率を計算する。"""
        if self.standard_price and self.own_price:
            self.diff_amount = self.standard_price - self.own_price
            if self.standard_price > 0:
                self.diff_ratio = (
                    self.diff_amount * 100 / self.standard_price
                )
        return self
