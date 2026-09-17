import re
from decimal import Decimal

from django.conf import settings
from django.core import validators
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
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


_CODE_PATTERN = re.compile(r"^\s*([A-Za-z]*)[-_ ]*(\d*)(.*)$")

# 社員番号のアルファベット部の表示順。ここにない文字はこの後ろにアルファベット順で並ぶ
EMPLOYEE_CODE_PREFIX_ORDER = ["Y", "S", "E", "T", "P", "A", "G"]
_PREFIX_RANK = {p: i for i, p in enumerate(EMPLOYEE_CODE_PREFIX_ORDER)}


def employee_code_sort_key(code):
    """社員番号をアルファベット部ごとに番号順へ並べるためのソートキー。

    先頭のアルファベットを EMPLOYEE_CODE_PREFIX_ORDER の順（Y→S→E→T→P→A→G）で
    まとめ、それ以外の文字はその後ろにアルファベット順で並べる。続く数字は
    "E2" < "E10" のように数値として比較する。社員番号が未設定のものは末尾に回す。
    """
    code = (code or "").strip()
    if not code:
        return (1, 0, "", 0, "", "")
    prefix, digits, rest = _CODE_PATTERN.match(code).groups()
    prefix = prefix.upper()
    rank = _PREFIX_RANK.get(prefix, len(_PREFIX_RANK))
    number = int(digits) if digits else -1
    return (0, rank, prefix, number, rest.strip().upper(), code.upper())


def sort_workers_by_code(workers):
    """作業員を社員番号順（employee_code_sort_key）に並べたリストを返す。

    同順位はフリガナ（なければ氏名）順。作業員一覧・社員名簿・出社予定など、
    作業員を並べる画面はすべてこれを通して同じ順にする。
    """
    return sorted(
        workers,
        key=lambda w: (
            employee_code_sort_key(w.employee_code),
            w.name_kana or w.name,
            w.name,
        ),
    )


def full_years_since(start, today=None):
    """start から today までの満年数。start が無ければ None。年齢・経験年数に使う。"""
    if not start:
        return None
    today = today or timezone.localdate()
    had_anniversary = (today.month, today.day) >= (start.month, start.day)
    return today.year - start.year - (0 if had_anniversary else 1)


class Worker(TenantModel):
    """作業員。日報・原価計算の主体。

    hourly_cost は労務費原価の算出単価。履歴が必要なため simple-history 付き。
    住所・緊急連絡先・社会保険・血液型は、管理者・事務員・本人だけが見て直せる（ADR-0057・ADR-0059）。
    """

    class BloodType(models.TextChoices):
        A = "A", "A型"
        B = "B", "B型"
        AB = "AB", "AB型"
        O = "O", "O型"  # noqa: E741 — 血液型の O。選択肢の名前を値とそろえる

    # 社会保険の選択肢は、建設業の作業員名簿（全建統一様式 第5号）の書き方に合わせる（ADR-0059）
    class HealthInsurance(models.TextChoices):
        UNION = "union", "健康保険組合"
        KYOKAI = "kyokai", "協会けんぽ"
        CONSTRUCTION_NHI = "construction_nhi", "建設国保"
        NATIONAL = "national", "国民健康保険"
        EXEMPT = "exempt", "適用除外"

    class PensionInsurance(models.TextChoices):
        EMPLOYEES = "employees", "厚生年金"
        NATIONAL = "national", "国民年金"
        RECIPIENT = "recipient", "受給者"
        EXEMPT = "exempt", "適用除外"

    class EmploymentInsurance(models.TextChoices):
        ENROLLED = "enrolled", "加入"
        DAY_LABORER = "day_laborer", "日雇保険"
        EXEMPT = "exempt", "適用除外"

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
    birth_date = models.DateField("生年月日", null=True, blank=True)
    hire_date = models.DateField("入社日", null=True, blank=True)
    experience_started_on = models.DateField(
        "経験の起算日",
        null=True,
        blank=True,
        help_text="経験年数を入力した日から、その年数を引いた日。経験年数はここから毎年自動で数える（ADR-0057）。",
    )
    # ---- ここから管理者・事務員・本人だけが見て直せる項目（ADR-0057） ----
    postal_code = models.CharField("郵便番号", max_length=8, blank=True, help_text="例: 123-4567")
    address = models.CharField("現住所", max_length=255, blank=True)
    emergency_contact_name = models.CharField("緊急連絡先の氏名", max_length=100, blank=True)
    emergency_contact_relationship = models.CharField(
        "緊急連絡先の続柄", max_length=30, blank=True, help_text="例: 妻、父、母",
    )
    emergency_contact_postal_code = models.CharField(
        "緊急連絡先の郵便番号", max_length=8, blank=True, help_text="例: 123-4567",
    )
    emergency_contact_address = models.CharField("緊急連絡先の住所", max_length=255, blank=True)
    emergency_contact_phone = models.CharField("緊急連絡先の電話番号", max_length=20, blank=True)
    # 社会保険（ADR-0059）。空欄は「まだ確かめていない」で、「適用除外」とは区別する
    health_insurance = models.CharField(
        "健康保険", max_length=20, choices=HealthInsurance.choices, blank=True,
    )
    pension_insurance = models.CharField(
        "年金保険", max_length=20, choices=PensionInsurance.choices, blank=True,
    )
    employment_insurance = models.CharField(
        "雇用保険", max_length=20, choices=EmploymentInsurance.choices, blank=True,
    )
    employment_insurance_number_last4 = models.CharField(
        "雇用保険の被保険者番号（下4桁）",
        max_length=4,
        blank=True,
        help_text="雇用保険被保険者証の番号の下4桁。雇用保険が「加入」のときだけ入れる。",
    )
    blood_type = models.CharField("血液型", max_length=2, choices=BloodType.choices, blank=True)
    is_active = models.BooleanField("有効", default=True)
    note = models.TextField("備考", blank=True)
    discord_user_id = models.CharField(
        "Discord ユーザーID",
        max_length=30,
        blank=True,
        help_text="Discordの数字ID（開発者モードで右クリック→IDをコピー）",
    )
    allowed_apps = models.JSONField(
        "利用可能アプリ",
        default=list,
        blank=True,
        help_text="アクセスを許可するアプリコードのリスト",
    )
    pin = models.CharField(
        "暗証番号",
        max_length=128,
        blank=True,
        help_text="4桁の暗証番号（ハッシュ化して保存）",
    )
    pin_set = models.BooleanField(
        "暗証番号設定済み",
        default=False,
        help_text="初回ログイン後に暗証番号を設定したかどうか",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "作業員"
        verbose_name_plural = "作業員"

    @property
    def monthly_salary(self):
        """月収目安（8h × 21日）。"""
        return self.hourly_cost * 168

    @property
    def age(self):
        """今日時点の満年齢。生年月日が未登録なら None。"""
        return full_years_since(self.birth_date)

    @property
    def experience_years(self):
        """今日時点の経験年数（満年数）。入力した日から1年ごとに1年ずつ増える。未入力なら None。"""
        return full_years_since(self.experience_started_on)

    @property
    def employment_insurance_label(self):
        """例: 加入（番号 下4桁: 1234）／日雇保険／適用除外。未入力なら空文字（ADR-0059）。"""
        if not self.employment_insurance:
            return ""
        label = self.get_employment_insurance_display()
        enrolled = self.employment_insurance == self.EmploymentInsurance.ENROLLED
        if enrolled and self.employment_insurance_number_last4:
            return f"{label}（番号 下4桁: {self.employment_insurance_number_last4}）"
        return label

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
    # 画像だけでなく PDF も受ける（ADR-0082）。台紙ごとスキャンした資格証は
    # PDF で配られることが多く、ImageField のままだと登録できなかった。
    certificate_image = models.FileField(
        "証明書（画像・PDF）",
        upload_to="qualifications/%Y/%m/",
        blank=True,
        validators=[
            validators.FileExtensionValidator(
                ["pdf", "jpg", "jpeg", "png", "gif", "webp", "heic"],
            ),
        ],
    )

    @property
    def certificate_is_pdf(self):
        """添付が PDF かどうか。画面での見せ方を分けるために使う。"""
        if not self.certificate_image:
            return False
        return self.certificate_image.name.lower().endswith(".pdf")
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
    # ---- 視力・血圧。管理者・事務員・本人だけが見て直せる（ADR-0057） ----
    vision_right_naked = models.DecimalField(
        "視力（右・裸眼）", max_digits=3, decimal_places=2, null=True, blank=True,
    )
    vision_left_naked = models.DecimalField(
        "視力（左・裸眼）", max_digits=3, decimal_places=2, null=True, blank=True,
    )
    vision_right_corrected = models.DecimalField(
        "視力（右・矯正）", max_digits=3, decimal_places=2, null=True, blank=True,
        help_text="メガネ・コンタクトをつけたときの視力",
    )
    vision_left_corrected = models.DecimalField(
        "視力（左・矯正）", max_digits=3, decimal_places=2, null=True, blank=True,
        help_text="メガネ・コンタクトをつけたときの視力",
    )
    blood_pressure_high = models.PositiveSmallIntegerField(
        "血圧（上）", null=True, blank=True, help_text="mmHg",
    )
    blood_pressure_low = models.PositiveSmallIntegerField(
        "血圧（下）", null=True, blank=True, help_text="mmHg",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "健康診断"
        verbose_name_plural = "健康診断"
        ordering = ["-checkup_date"]

    def __str__(self):
        return f"{self.worker.name} - {self.checkup_date}"

    @staticmethod
    def _vision_text(value):
        # 1.20 は「1.2」、0.05 は「0.05」と書く（視力表の書き方に合わせる）
        if value is None:
            return "-"
        tenth = value.quantize(Decimal("0.1"))
        return str(tenth if tenth == value else value.normalize())

    @property
    def has_vision(self):
        return any(v is not None for v in (
            self.vision_right_naked, self.vision_left_naked,
            self.vision_right_corrected, self.vision_left_corrected,
        ))

    @property
    def has_blood_pressure(self):
        return self.blood_pressure_high is not None or self.blood_pressure_low is not None

    @property
    def vision_label(self):
        """例: 裸眼 右1.2・左1.0 ／ 矯正 右-・左-。記録が無ければ空文字。"""
        if not self.has_vision:
            return ""
        return (
            f"裸眼 右{self._vision_text(self.vision_right_naked)}"
            f"・左{self._vision_text(self.vision_left_naked)}"
            f" ／ 矯正 右{self._vision_text(self.vision_right_corrected)}"
            f"・左{self._vision_text(self.vision_left_corrected)}"
        )

    @property
    def blood_pressure_label(self):
        """例: 128 / 82 mmHg。記録が無ければ空文字。"""
        if not self.has_blood_pressure:
            return ""
        high = self.blood_pressure_high if self.blood_pressure_high is not None else "-"
        low = self.blood_pressure_low if self.blood_pressure_low is not None else "-"
        return f"{high} / {low} mmHg"


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


class EvaluatorAssignment(TenantModel):
    """評価者 → 被評価者 の割当。

    evaluation.EvaluatorTarget（名前テキストの組）を作業員 FK で持ち直したもの
    （ADR-0028）。名前で持つと改姓や表記揺れで割当が外れるため FK にした。

    役員・社長は自分自身も評価する運用のため、evaluator == target を禁止しない。
    """

    evaluator = models.ForeignKey(
        Worker,
        on_delete=models.CASCADE,
        related_name="evaluation_target_assignments",
        verbose_name="評価者",
    )
    target = models.ForeignKey(
        Worker,
        on_delete=models.CASCADE,
        related_name="evaluator_assignments",
        verbose_name="被評価者",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "評価者割当"
        verbose_name_plural = "評価者割当"
        ordering = ["evaluator__name", "target__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "evaluator", "target"],
                name="workers_evaluator_assignment_unique",
            ),
        ]

    def __str__(self):
        return f"{self.evaluator} → {self.target}"


# ---- シグナル: 書類添付時にアラート履歴をクリア ----


@receiver(post_save, sender=WorkerQualification)
def clear_cert_alert_log(sender, instance, **kwargs):
    """証明書が添付されたらアラート履歴をクリアして再アラートを可能にする。"""
    if instance.certificate_image:
        from apps.notifications.models import AlertLog

        AlertLog.unscoped.filter(
            reference_type="workers.WorkerQualification",
            reference_id=instance.pk,
            alert_rule__alert_type="cert_missing",
        ).delete()


@receiver(post_save, sender=HealthCheckup)
def clear_health_report_alert_log(sender, instance, **kwargs):
    """健診報告書が添付されたらアラート履歴をクリアする。"""
    if instance.report_file:
        from apps.notifications.models import AlertLog

        AlertLog.unscoped.filter(
            reference_type="workers.HealthCheckup",
            reference_id=instance.pk,
            alert_rule__alert_type="health_report_missing",
        ).delete()


@receiver(post_save, sender=HealthCheckup)
def clear_health_checkup_due_alert_log(sender, instance, **kwargs):
    """新規健診記録追加時に健診期限アラート履歴をクリアする。"""
    from apps.notifications.models import AlertLog

    AlertLog.unscoped.filter(
        reference_type="workers.Worker",
        reference_id=instance.worker_id,
        alert_rule__alert_type="health_checkup_due",
    ).delete()
