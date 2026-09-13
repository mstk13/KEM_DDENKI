import uuid
from pathlib import Path

from django.conf import settings
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class Site(TenantModel):
    """現場。全業務データの起点。案件=現場を1:1とする。"""

    class Status(models.TextChoices):
        ESTIMATING = "estimating", "見積中"
        ORDERED = "ordered", "受注済"
        IN_PROGRESS = "in_progress", "施工中"
        COMPLETED = "completed", "完工"
        BILLED = "billed", "請求済"
        CANCELLED = "cancelled", "中止"

    code = models.CharField("現場コード", max_length=50)
    name = models.CharField("現場名", max_length=200)
    customer = models.ForeignKey(
        "masters.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sites",
        verbose_name="顧客",
    )
    work_types = models.ManyToManyField(
        "masters.WorkType",
        blank=True,
        related_name="sites",
        verbose_name="工種",
    )
    address = models.TextField("住所", blank=True)
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.ESTIMATING,
    )
    contract_amount = models.DecimalField(
        "受注金額",
        max_digits=14,
        decimal_places=0,
        default=0,
    )
    payment_terms = models.CharField(
        "支払条件",
        max_length=200,
        blank=True,
        help_text="空欄なら顧客の標準支払条件を使う。",
    )
    estimate_valid_until = models.CharField(
        "見積有効期限",
        max_length=100,
        blank=True,
        help_text="日付とは限らず「発行後30日間」等と書かれることがあるため文字列で持つ。",
    )
    note = models.TextField("備考", blank=True)
    extracted_details = models.TextField(
        "その他の読み取り項目",
        blank=True,
        help_text="見積ファイルから読み取った、上の項目に当てはまらない記載を1行1件で残す。",
    )
    start_date = models.DateField("工期開始", null=True, blank=True)
    end_date = models.DateField("工期終了", null=True, blank=True)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_sites",
        verbose_name="現場担当者",
    )
    estimator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="estimated_sites",
        verbose_name="見積担当者",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "現場"
        verbose_name_plural = "現場"
        unique_together = [("company", "code")]

    def __str__(self):
        return self.name

    @property
    def effective_payment_terms(self) -> str:
        """実際に適用される支払条件。現場に指定が無ければ顧客の標準を使う。"""
        if self.payment_terms:
            return self.payment_terms
        return self.customer.payment_terms if self.customer else ""


class EstimateImport(TenantModel):
    """見積ファイルの取込履歴。

    「いつ・誰が・どのファイルから・どの宛名で」取り込んだかを残す。
    顧客を引き当てられなかった場合も customer_name_raw に宛名を残すので、
    後から顧客マスタに登録する候補として使える。
    """

    customer = models.ForeignKey(
        "masters.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="estimate_imports",
        verbose_name="顧客",
    )
    customer_name_raw = models.CharField(
        "読み取った宛名", max_length=200, blank=True,
    )
    site = models.ForeignKey(
        Site,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="estimate_imports",
        verbose_name="登録した現場",
    )
    filename = models.CharField("ファイル名", max_length=255, blank=True)
    estimate_number = models.CharField("見積番号", max_length=100, blank=True)
    amount = models.DecimalField(
        "見積金額", max_digits=14, decimal_places=0, null=True, blank=True,
    )
    payment_terms = models.CharField("支払条件", max_length=200, blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "見積取込履歴"
        verbose_name_plural = "見積取込履歴"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.filename} → {self.customer_name_raw or '宛名不明'}"

    @property
    def is_unmatched(self) -> bool:
        """宛名は読めたのに顧客を引き当てられなかったか。登録候補の判定に使う。"""
        return self.customer_id is None and bool(self.customer_name_raw)


class Process(TenantModel):
    """工程。現場ごとの計画工程と実績。"""

    class Status(models.TextChoices):
        PLANNED = "planned", "計画"
        IN_PROGRESS = "in_progress", "進行中"
        COMPLETED = "completed", "完了"
        DELAYED = "delayed", "遅延"

    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="processes",
        verbose_name="現場",
    )
    work_type = models.ForeignKey(
        "masters.WorkType",
        on_delete=models.CASCADE,
        related_name="processes",
        verbose_name="工種",
    )
    name = models.CharField("工程名", max_length=200)
    planned_start = models.DateField("計画開始日", null=True, blank=True)
    planned_end = models.DateField("計画終了日", null=True, blank=True)
    actual_start = models.DateField("実績開始日", null=True, blank=True)
    actual_end = models.DateField("実績終了日", null=True, blank=True)
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.PLANNED,
    )
    display_order = models.IntegerField("表示順", default=0)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "工程"
        verbose_name_plural = "工程"
        ordering = ["display_order"]

    def __str__(self):
        return f"{self.site} - {self.name}"


def _site_photo_folder(instance):
    """会社・現場・撮影日ごとのフォルダ。バックアップから取り出すときも日付で探せる。

    あとで撮影日を直しても、ファイルは動かさない（元のフォルダのまま）。
    """
    day = instance.taken_on.strftime("%Y-%m-%d") if instance.taken_on else "undated"
    return f"site_photos/{instance.company_id}/{instance.site_id}/{day}"


def site_photo_path(instance, filename):
    """現場写真の保存先。

    ファイル名は推測できない乱数にする。スマホのファイル名（IMG_1234.jpg）は
    現場をまたいで重なるうえ、連番から他の写真を当てられてしまうため。
    元の名前は original_filename に残す。
    """
    suffix = Path(filename).suffix.lower()[:10] or ".jpg"
    return f"{_site_photo_folder(instance)}/{uuid.uuid4().hex}{suffix}"


def site_photo_thumbnail_path(instance, filename):
    """一覧用の縮小画像の保存先。縮小画像は常に JPEG で作る。"""
    return f"{_site_photo_folder(instance)}/thumbs/{uuid.uuid4().hex}.jpg"


class SitePhoto(TenantModel):
    """現場写真。現地調査や施工状況を、どこの・どのような写真かと一緒に残す（ADR-0051）。

    元の写真は加工せずに残す（公共工事の写真提出では加工が認められないことがあるため）。
    一覧で何十枚も元の大きさで読み込むとスマホで重いので、縮小画像を別に持つ。
    """

    class Kind(models.TextChoices):
        SURVEY = "survey", "現地調査"
        BEFORE = "before", "施工前"
        DURING = "during", "施工中"
        AFTER = "after", "施工後"
        OTHER = "other", "その他"

    # 一覧の色分け。テンプレートに種類ごとの分岐を書かずに済むようモデル側に持つ
    KIND_BADGES = {
        Kind.SURVEY: "badge-blue",
        Kind.BEFORE: "badge-gray",
        Kind.DURING: "badge-orange",
        Kind.AFTER: "badge-green",
        Kind.OTHER: "badge-gray",
    }

    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="photos",
        verbose_name="現場",
    )
    kind = models.CharField(
        "種類", max_length=20, choices=Kind.choices, default=Kind.DURING,
    )
    location = models.CharField(
        "撮影場所", max_length=200, help_text="例: 2F 東側 分電盤、外観 北面",
    )
    taken_on = models.DateField("撮影日")
    note = models.TextField("メモ", blank=True)
    image = models.ImageField("写真", upload_to=site_photo_path, max_length=255)
    thumbnail = models.ImageField(
        "一覧用の縮小画像",
        upload_to=site_photo_thumbnail_path,
        max_length=255,
        blank=True,
        help_text="読み込めない形式の写真では作れないので空のことがある。そのときは元の写真を出す。",
    )
    original_filename = models.CharField("元のファイル名", max_length=255, blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "現場写真"
        verbose_name_plural = "現場写真"
        ordering = ["-taken_on", "-pk"]
        indexes = [
            models.Index(fields=["site", "kind"], name="sites_photo_site_kind_idx"),
        ]

    def __str__(self):
        return f"{self.site} - {self.get_kind_display()} {self.location}"

    @property
    def kind_badge(self) -> str:
        return self.KIND_BADGES.get(self.kind, "badge-gray")


@receiver(post_delete, sender=SitePhoto)
def delete_site_photo_files(sender, instance, **kwargs):
    """写真を消したら、ファイルも消す（現場ごと消したときも）。

    写真に人や個人の情報が写り込んで消したい場合があるので、ファイルを残さない。
    削除が取り消されたときにファイルだけ消えないよう、確定してから消す。
    """
    storage = instance.image.storage
    names = [field.name for field in (instance.image, instance.thumbnail) if field]

    def _remove_files():
        for name in names:
            storage.delete(name)

    transaction.on_commit(_remove_files)
