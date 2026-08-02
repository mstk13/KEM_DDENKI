from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class JobTitle(TenantModel):
    """職種区分。テナントごとに定義。

    例: 電工 / 配管工 / CADオペ / 事務
    """

    name = models.CharField("職種名", max_length=100)
    is_active = models.BooleanField("有効", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "職種"
        verbose_name_plural = "職種"
        unique_together = [("company", "name")]

    def __str__(self):
        return self.name


class Position(TenantModel):
    """役職。テナントごとに定義。rank は序列（昇順）。

    例: 職長(1) / 主任(2) / シニア(3) / ミドル(4) / ジュニア(5)
    評価項目の出し分け等に利用する。
    """

    name = models.CharField("役職名", max_length=100)
    rank = models.IntegerField("序列", default=0, help_text="昇順。数字が小さいほど上位")
    is_active = models.BooleanField("有効", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "役職"
        verbose_name_plural = "役職"
        unique_together = [("company", "name")]
        ordering = ["rank"]

    def __str__(self):
        return self.name


class Worker(TenantModel):
    """作業員。日報・原価計算の主体。

    hourly_cost は労務費原価の算出単価。履歴が必要なため simple-history 付き。
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="worker_profile",
        verbose_name="ユーザーアカウント",
    )
    employee_code = models.CharField(
        "社員番号", max_length=20, blank=True,
        help_text="例: E001",
    )
    name = models.CharField("氏名", max_length=100)
    name_kana = models.CharField("フリガナ", max_length=100, blank=True)
    job_title = models.ForeignKey(
        JobTitle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workers",
        verbose_name="職種",
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workers",
        verbose_name="役職",
    )
    skill_tags = models.JSONField(
        "スキルタグ",
        default=list,
        blank=True,
    )
    hourly_cost = models.DecimalField(
        "時間単価",
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="労務費CostTransactionの算出単価",
    )
    phone = models.CharField("電話番号", max_length=20, blank=True)
    hire_date = models.DateField("入社日", null=True, blank=True)
    is_active = models.BooleanField("有効", default=True)
    note = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "作業員"
        verbose_name_plural = "作業員"

    @property
    def monthly_salary(self):
        """月収目安（8h × 21日）。"""
        return self.hourly_cost * 168

    def __str__(self):
        return self.name


class WorkerQualification(TenantModel):
    """作業員の保有資格。証明画像を添付可能。"""

    class Category(models.TextChoices):
        LICENSE = "license", "免許"
        SKILL_COURSE = "skill_course", "技能講習"
        EDUCATION = "education", "教育・特別教育"
        OTHER = "other", "その他"

    worker = models.ForeignKey(
        Worker,
        on_delete=models.CASCADE,
        related_name="qualifications",
        verbose_name="作業員",
    )
    name = models.CharField("資格名", max_length=200)
    category = models.CharField(
        "区分",
        max_length=20,
        choices=Category.choices,
        default=Category.LICENSE,
    )
    acquired_date = models.DateField("取得日", null=True, blank=True)
    expiry_date = models.DateField("有効期限", null=True, blank=True)
    certificate_image = models.ImageField(
        "証明書画像",
        upload_to="qualifications/%Y/%m/",
        blank=True,
    )
    note = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "保有資格"
        verbose_name_plural = "保有資格"
        ordering = ["category", "name"]

    def __str__(self):
        return f"{self.worker.name} - {self.name}"


class HealthCheckup(TenantModel):
    """作業員の健康診断結果。"""

    class Result(models.TextChoices):
        NORMAL = "normal", "異常なし"
        OBSERVATION = "observation", "経過観察"
        REEXAM = "reexam", "要再検査"
        TREATMENT = "treatment", "要治療"

    worker = models.ForeignKey(
        Worker,
        on_delete=models.CASCADE,
        related_name="health_checkups",
        verbose_name="作業員",
    )
    checkup_date = models.DateField("受診日")
    result = models.CharField(
        "判定",
        max_length=20,
        choices=Result.choices,
        default=Result.NORMAL,
    )
    institution = models.CharField("受診機関", max_length=200, blank=True)
    memo = models.TextField("メモ", blank=True)
    report_file = models.FileField(
        "結果ファイル",
        upload_to="health_checkups/%Y/%m/",
        blank=True,
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "健康診断"
        verbose_name_plural = "健康診断"
        ordering = ["-checkup_date"]

    def __str__(self):
        return f"{self.worker.name} - {self.checkup_date}"


class EvaluationTemplate(TenantModel):
    """テナント別の評価テンプレート。

    評価項目・質問・配点・スケールをJSONBで保持し、
    テナントごとにカスタマイズ可能にする。
    """

    name = models.CharField("テンプレート名", max_length=200)
    sections = models.JSONField(
        "評価項目",
        default=list,
        help_text="[{section, num, name, description, max_score, ...}, ...]",
    )
    survey_items = models.JSONField(
        "質問詳細",
        default=list,
        help_text="[{section, num, name, anchor_5/3/1, free_text, questions: [...]}, ...]",
    )
    scale = models.JSONField(
        "評価スケール",
        default=list,
        help_text="[{value, label}, ...]",
    )
    overall = models.JSONField(
        "総合所見項目",
        default=list,
        help_text="[{qnum, text, by_self}, ...]",
    )
    is_active = models.BooleanField("有効", default=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "評価テンプレート"
        verbose_name_plural = "評価テンプレート"

    def __str__(self):
        return f"{self.company} - {self.name}"


class WorkerEvaluation(TenantModel):
    """人材評価。アンケート回答を responses (JSONB) に格納。"""

    worker = models.ForeignKey(
        Worker,
        on_delete=models.CASCADE,
        related_name="evaluations",
        verbose_name="作業員",
    )
    evaluated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="evaluations_given",
        verbose_name="評価者",
    )
    template = models.ForeignKey(
        EvaluationTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluations",
        verbose_name="使用テンプレート",
    )
    period = models.CharField("評価期間", max_length=50, help_text="例: 2026-Q1")
    score = models.IntegerField("総合評点", null=True, blank=True)
    comment = models.TextField("総合コメント", blank=True)
    responses = models.JSONField(
        "アンケート回答",
        default=dict,
        blank=True,
        help_text="各評価項目の回答 {section_num: {score, free_text, questions: {qnum: score}}}",
    )
    overall_responses = models.JSONField(
        "総合所見回答",
        default=dict,
        blank=True,
        help_text="総合所見 {qnum: text}",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "人材評価"
        verbose_name_plural = "人材評価"

    def __str__(self):
        return f"{self.worker} - {self.period}"
