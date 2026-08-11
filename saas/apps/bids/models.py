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

    # --- 参加資格要件 ---
    class GradeChoices(models.TextChoices):
        A = "A", "A等級"
        B = "B", "B等級"
        C = "C", "C等級"
        D = "D", "D等級"

    required_category = models.CharField(
        "必要業種区分",
        max_length=100,
        blank=True,
        help_text="例: 役務の提供等, 電気, 建築, 土木",
    )
    required_grade = models.CharField(
        "必要等級",
        max_length=10,
        blank=True,
        choices=GradeChoices.choices,
        help_text="この等級以上の資格が必要",
    )
    required_issuer_type = models.CharField(
        "資格種別",
        max_length=200,
        blank=True,
        help_text="例: 全省庁統一資格, 防衛省, 国土交通省, 千葉県",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "入札案件"
        verbose_name_plural = "入札案件"
        ordering = ["-created_at"]

    # 等級の序列（A が最上位）
    GRADE_ORDER = {"A": 1, "B": 2, "C": 3, "D": 4}

    def check_qualification(self, qualifications):
        """自社の資格リストと照合して受注可否を判定する。

        Args:
            qualifications: Qualification の QuerySet またはリスト

        Returns:
            dict: {
                "eligible": bool,        # 受注可能か
                "reason": str,           # 判定理由
                "matched_qual": obj|None # マッチした資格
            }
        """
        import datetime

        if not self.required_grade and not self.required_category:
            return {
                "eligible": None,
                "reason": "参加要件が未設定です",
                "matched_qual": None,
            }

        today = datetime.date.today()

        for q in qualifications:
            # 有効期限チェック
            if q.valid_until and q.valid_until < today:
                continue
            if q.valid_from and q.valid_from > today:
                continue

            # 資格種別チェック（設定されている場合）
            if self.required_issuer_type and self.required_issuer_type not in q.issuer:
                continue

            # 業種区分チェック（設定されている場合）
            if self.required_category and self.required_category not in q.category:
                continue

            # 等級チェック
            if self.required_grade:
                if not q.grade:
                    continue
                req_order = self.GRADE_ORDER.get(self.required_grade, 99)
                own_order = self.GRADE_ORDER.get(q.grade.upper().strip(), 99)
                if own_order > req_order:
                    # 自社の等級が要件より低い
                    continue

            return {
                "eligible": True,
                "reason": f"{q.issuer} / {q.category} / {q.grade}等級 で参加可能",
                "matched_qual": q,
            }

        # マッチなし
        missing = []
        if self.required_issuer_type:
            missing.append(f"資格種別: {self.required_issuer_type}")
        if self.required_category:
            missing.append(f"業種: {self.required_category}")
        if self.required_grade:
            missing.append(f"{self.required_grade}等級以上")

        return {
            "eligible": False,
            "reason": f"要件を満たす資格がありません（{', '.join(missing)}）",
            "matched_qual": None,
        }

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
    """スクレイピング対象（入札情報サービス i-ppi.jp）。"""

    class Region(models.TextChoices):
        HOKKAIDO = "北海道", "北海道"
        TOHOKU = "東北", "東北"
        KANTO = "関東", "関東"
        HOKURIKU = "北陸", "北陸"
        CHUBU = "中部", "中部"
        KINKI = "近畿", "近畿"
        CHUGOKU = "中国", "中国"
        SHIKOKU = "四国", "四国"
        KYUSHU = "九州", "九州"
        OKINAWA = "沖縄", "沖縄"

    name = models.CharField("名称", max_length=200)
    url = models.URLField(
        "URL",
        default="https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=3",
    )
    keyword = models.CharField("工事名キーワード", max_length=200, blank=True)
    region = models.CharField(
        "地域（地方）", max_length=100, blank=True, choices=Region.choices
    )
    prefecture = models.CharField("都道府県", max_length=50, blank=True)
    category = models.CharField(
        "工事種別",
        max_length=100,
        blank=True,
        help_text="例: 電気, 建築, 土木",
    )
    days_back = models.PositiveIntegerField(
        "過去N日以内の更新",
        default=30,
        help_text="最終更新日の検索範囲（日数）",
    )
    is_active = models.BooleanField("有効", default=True)
    last_scraped_at = models.DateTimeField("最終取得日時", null=True, blank=True)
    last_result_count = models.PositiveIntegerField("前回取得件数", default=0)

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
