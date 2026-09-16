import uuid
from pathlib import Path

from django.conf import settings
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from simple_history.models import HistoricalRecords

from apps.core.managers import UnscopedManager
from apps.core.models import TenantModel, TimeStampedModel


class Company(TimeStampedModel):
    """テナント（会社）。全データの起点。"""

    name = models.CharField("会社名", max_length=200)
    industry_type = models.CharField(
        "業種（参考情報）",
        max_length=100,
        blank=True,
        help_text="ロジックの分岐には使用禁止（ADR-0003）",
    )
    contract_plan = models.CharField("契約プラン", max_length=50, blank=True)
    is_active = models.BooleanField("有効", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "会社"
        verbose_name_plural = "会社"

    def __str__(self):
        return self.name


class CompanyApp(TimeStampedModel):
    """テナントごとの有効アプリ。機能アクセス制御と課金判定の単一情報源。"""

    APP_CODES = [
        ("jinzai", "人材管理"),
        ("hyoka", "人材評価"),
        ("koutei", "工期・工程管理"),
        ("zairyo", "材料管理"),
        ("nippou", "日報管理"),
        ("genka", "原価・予実管理"),
    ]

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="apps",
        verbose_name="会社",
    )
    app_code = models.CharField("アプリコード", max_length=20, choices=APP_CODES)
    is_enabled = models.BooleanField("有効", default=False)
    enabled_at = models.DateTimeField("有効化日時", null=True, blank=True)

    # CompanyApp はテナント横断で参照する場面がある（@app_required）
    objects = UnscopedManager()
    unscoped = UnscopedManager()

    history = HistoricalRecords()

    class Meta:
        verbose_name = "有効アプリ"
        verbose_name_plural = "有効アプリ"
        unique_together = [("company", "app_code")]

    def __str__(self):
        return f"{self.company} - {self.get_app_code_display()}"


# ===================================================================
# 自社書類（ADR-0071）
#
# 経営規模等評価結果通知書（経審）・建設業許可証・登記事項証明書など、会社そのものの書類を
# 1か所にしまっておく。読み込んだ中身は AI で読み取って一覧に出し、更新のある書類は
# 更新日の3か月前・1か月前・2週間前に知らせる（apps/tenants/document_alerts.py）。
# ===================================================================


def company_document_path(instance, filename):
    """自社書類の保存先。会社ごとのフォルダに、推測できない乱数の名前で置く。

    元の名前は original_filename に残し、開くときにその名前で返す。
    """
    suffix = Path(filename).suffix.lower()[:10]
    return f"company_documents/{instance.company_id}/{uuid.uuid4().hex}{suffix}"


class CompanyDocumentType(TenantModel):
    """自社書類の種類（会社ごとの一覧）。管理画面で名前・並び順・使う／使わないを変える。"""

    name = models.CharField("書類名", max_length=200)
    has_renewal = models.BooleanField(
        "更新がある",
        default=False,
        help_text="更新日を入れて、3か月前・1か月前・2週間前に知らせる書類か。",
    )
    display_order = models.PositiveIntegerField("並び順", default=0)
    is_active = models.BooleanField("使う", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "自社書類の種類"
        verbose_name_plural = "自社書類の種類"
        ordering = ["display_order", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="tenants_company_document_type_unique",
            ),
        ]

    def __str__(self):
        return self.name


class CompanyDocument(TenantModel):
    """登録した自社書類1件（ファイル1つ）。同じ種類を入れ直すと、前のものは古い版として残る。"""

    class Kind(models.TextChoices):
        PDF = "pdf", "PDF"
        EXCEL = "excel", "Excel"

    doc_type = models.ForeignKey(
        CompanyDocumentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
        verbose_name="種類",
    )
    name = models.CharField("書類名", max_length=200)
    file = models.FileField("ファイル", upload_to=company_document_path, max_length=255)
    kind = models.CharField("形式", max_length=10, choices=Kind.choices)
    original_filename = models.CharField("元のファイル名", max_length=255)
    size = models.PositiveBigIntegerField("大きさ（バイト）", default=0)
    issued_on = models.DateField("発行日", null=True, blank=True)
    renewal_on = models.DateField(
        "更新日", null=True, blank=True, help_text="次に更新・提出が必要な日。",
    )
    memo = models.TextField("メモ", blank=True)

    # 登録した人が中身を見たか。見ずに置いただけの書類を見分けるため（ADR-0071）
    confirmed = models.BooleanField("中身を確認した", default=False)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="確認した人",
    )
    confirmed_at = models.DateTimeField("確認した日時", null=True, blank=True)

    # AI が読み取った中身。人が直した値ではないので、そのまま帳票には使わない
    ai_summary = models.TextField("AI が読み取った要約", blank=True)
    ai_fields = models.JSONField("AI が読み取った項目", default=list, blank=True)
    ai_checked_at = models.DateTimeField("AI で読み取った日時", null=True, blank=True)

    # 更新の知らせをどこまで出したか。履歴を増やさないよう update で書く
    reminder_step = models.PositiveSmallIntegerField(
        "知らせた段階", null=True, blank=True, editable=False,
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "自社書類"
        verbose_name_plural = "自社書類"
        ordering = ["-issued_on", "-created_at", "-pk"]
        indexes = [
            models.Index(fields=["company", "renewal_on"], name="tenants_doc_renewal_idx"),
        ]

    def __str__(self):
        return f"{self.name}（{self.original_filename}）"

    def save(self, *args, **kwargs):
        """更新日を直したら、知らせの段階を数え直す（前の段階の知らせを出し直す）。"""
        if self.pk:
            before = CompanyDocument.unscoped.filter(pk=self.pk).values("renewal_on").first()
            if before and before["renewal_on"] != self.renewal_on:
                self.reminder_step = None
        super().save(*args, **kwargs)


@receiver(post_delete, sender=CompanyDocument)
def delete_company_document_file(sender, instance, **kwargs):
    """書類を消したら、保存したファイルも消す。決算書など社外に出せない中身を残さない。"""
    storage = instance.file.storage
    name = instance.file.name
    if name:
        transaction.on_commit(lambda: storage.delete(name))
