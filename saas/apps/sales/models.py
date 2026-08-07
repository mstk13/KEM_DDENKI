from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class SalesVisit(TenantModel):
    """営業訪問記録。"""

    class Industry(models.TextChoices):
        DENZAI = "電材・資材", "電材・資材"
        MAKER = "メーカー・製造", "メーカー・製造"
        SHOSHA = "商社・卸", "商社・卸"
        IT = "通信・IT", "通信・IT"
        KENSETSU = "建設・設備工事", "建設・設備工事"
        SHOUENE = "省エネ・環境", "省エネ・環境"
        OFFICE = "オフィス・事務用品", "オフィス・事務用品"
        KINYU = "金融・保険・リース", "金融・保険・リース"
        JINZAI = "人材・サービス", "人材・サービス"
        KOUKOKU = "広告・印刷", "広告・印刷"
        OTHER = "その他", "その他"

    class Status(models.TextChoices):
        DRAFT = "下書き", "下書き"
        CONFIRMED = "確認済", "確認済"
        IN_PROGRESS = "対応中", "対応中"
        DONE = "完了", "完了"
        SKIPPED = "見送り", "見送り"

    industry = models.CharField(
        "業種",
        max_length=50,
        choices=Industry.choices,
        default=Industry.OTHER,
    )
    company_name = models.CharField("会社名", max_length=255)
    rep_name = models.CharField("担当者名", max_length=100, blank=True)
    business_overview = models.TextField("事業概要", blank=True)
    sales_content = models.TextField("営業内容", blank=True)
    phone = models.CharField("電話番号", max_length=50, blank=True)
    email = models.EmailField("メール", blank=True)
    website = models.URLField("Webサイト", blank=True)
    address = models.TextField("住所", blank=True)
    visit_date = models.DateField("訪問日", null=True, blank=True)
    received_date = models.DateField("受領日", null=True, blank=True)
    source_file = models.CharField("添付資料パス", max_length=500, blank=True)
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    memo = models.TextField("メモ", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "営業訪問記録"
        verbose_name_plural = "営業訪問記録"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.company_name} ({self.get_industry_display()})"
