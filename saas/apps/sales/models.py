"""営業来訪管理モデル。

営業担当者の来訪記録・資料管理・業界別ブラウジングを提供する。
現行版 eigyo-kanri の sales.visits テーブルに相当。
"""

from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class SalesVisit(TenantModel):
    """営業来訪記録。"""

    class Status(models.TextChoices):
        DRAFT = "draft", "下書き"
        CONFIRMED = "confirmed", "確認済"
        IN_PROGRESS = "in_progress", "対応中"
        DONE = "done", "完了"
        REJECTED = "rejected", "見送り"

    INDUSTRY_CHOICES = [
        ("electrical", "電材・資材"),
        ("manufacturer", "メーカー・製造"),
        ("it_software", "IT・ソフトウェア"),
        ("construction", "建設・設備"),
        ("insurance", "保険・金融"),
        ("vehicle", "車両・リース"),
        ("welfare", "福利厚生"),
        ("education", "教育・研修"),
        ("environment", "環境・エネルギー"),
        ("rental", "レンタル・リース"),
        ("other", "その他"),
    ]

    industry = models.CharField(
        "業界",
        max_length=50,
        choices=INDUSTRY_CHOICES,
        default="other",
    )
    company_name = models.CharField("会社名", max_length=200)
    rep_name = models.CharField("担当者名", max_length=100, blank=True)
    business_overview = models.TextField(
        "事業概要",
        blank=True,
        help_text="会社の事業内容（1-2文）",
    )
    sales_content = models.TextField(
        "営業内容",
        blank=True,
        help_text="提案内容の要約",
    )

    # 連絡先
    phone = models.CharField("電話番号", max_length=20, blank=True)
    email = models.EmailField("メール", blank=True)
    website = models.URLField("Webサイト", blank=True)
    address = models.TextField("住所", blank=True)

    # 日付
    visit_date = models.DateField("営業日", null=True, blank=True)
    received_date = models.DateField("受領日", null=True, blank=True)

    # ファイル・ステータス
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    memo = models.TextField("メモ", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "営業来訪記録"
        verbose_name_plural = "営業来訪記録"
        ordering = ["-visit_date", "-created_at"]

    def __str__(self):
        return f"{self.company_name} ({self.visit_date})"


class SalesAttachment(TenantModel):
    """営業資料の添付ファイル。PDF/画像/名刺など。"""

    visit = models.ForeignKey(
        SalesVisit,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name="来訪記録",
    )
    file = models.FileField(
        "ファイル",
        upload_to="sales/%Y/%m/",
    )
    original_name = models.CharField("元ファイル名", max_length=300)
    file_type = models.CharField(
        "ファイル種別",
        max_length=20,
        blank=True,
        help_text="pdf, image, business_card 等",
    )

    class Meta:
        verbose_name = "営業資料"
        verbose_name_plural = "営業資料"

    def __str__(self):
        return f"{self.visit.company_name} - {self.original_name}"
