"""現場の安全書類（ADR-0061）。

- 安全作業確認書（新規入場者用・導入教育）: 現場ごとに作業員1人1回（EntryConfirmation）
- KY用紙（安全作業指示書）: 現場ごとに1日1枚（KySheet）。作業責任者が上半分を書き、
  参加者がそれぞれ自分の行（サイン・健康状態・検電器）を書く（KyParticipant）

様式は会社の Excel「現場ごとの書類一覧.xlsx」の2シート。文言は apps/safety/formats.py。
サインは画面に指で書いた PNG を data URL の文字列で持つ（PDF にそのまま描く）。
"""

from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel

# サインの data URL の上限（PNG で約 220KB）。スマホの高精細な画面で書いても収まる大きさ
SIGNATURE_MAX_LENGTH = 300_000


class EntryConfirmation(TenantModel):
    """安全作業確認書（新規入場者用・導入教育）。現場ごとに作業員1人1回。

    本人の情報は作業員の登録（ADR-0057・ADR-0059）と最新の健康診断から最初に入れ、
    その場で直せる。記入した時点の値をここに残す（あとで登録が変わっても書類は変えない）。
    住所・緊急連絡先・血液型・血圧・視力を含むので、見られるのは管理者・事務員・本人だけ。
    """

    class BusinessType(models.TextChoices):
        SME_OWNER = "sme_owner", "中小企業主"
        SOLE_PROPRIETOR = "sole_proprietor", "一人親方"
        NEITHER = "neither", "どちらでもない"

    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="entry_confirmations",
        verbose_name="現場",
    )
    worker = models.ForeignKey(
        "workers.Worker",
        on_delete=models.CASCADE,
        related_name="entry_confirmations",
        verbose_name="作業員",
    )
    entry_date = models.DateField("記入日")

    # ---- 本人・所属 ----
    name_kana = models.CharField("ふりがな", max_length=100, blank=True)
    birth_date = models.DateField("生年月日", null=True, blank=True)
    foreman_name = models.CharField("直属（自社）の職長名", max_length=100, blank=True)
    transport = models.CharField("当該現場までの使用交通機関", max_length=100, blank=True)
    partner_company_1 = models.CharField("1次協力会社名", max_length=100, blank=True)
    partner_company_2 = models.CharField("2次協力会社名", max_length=100, blank=True)
    partner_company_n_tier = models.CharField(
        "（　）次協力会社の次数",
        max_length=5,
        blank=True,
        help_text="例: 3",
    )
    partner_company_n = models.CharField("（　）次協力会社名", max_length=100, blank=True)

    # ---- 住所・緊急連絡先・健康 ----
    address = models.CharField("現住所", max_length=255, blank=True)
    phone = models.CharField("電話番号", max_length=20, blank=True)
    emergency_contact_name = models.CharField("緊急連絡者氏名", max_length=100, blank=True)
    emergency_contact_address = models.CharField("緊急連絡者の住所", max_length=255, blank=True)
    emergency_contact_phone = models.CharField("緊急連絡者の電話番号", max_length=20, blank=True)
    experience_years = models.PositiveSmallIntegerField("経験年数（年）", null=True, blank=True)
    experience_months = models.PositiveSmallIntegerField("経験年数（月）", null=True, blank=True)
    blood_type = models.CharField("血液型", max_length=2, blank=True)
    blood_pressure_high = models.PositiveSmallIntegerField("血圧（上）", null=True, blank=True)
    blood_pressure_low = models.PositiveSmallIntegerField("血圧（下）", null=True, blank=True)
    vision_right = models.CharField("視力（右）", max_length=10, blank=True)
    vision_left = models.CharField("視力（左）", max_length=10, blank=True)

    # ---- 質問（空＝未回答） ----
    shock_education = models.BooleanField(
        "感電災害事故防止教育・指導を受けた",
        null=True,
        blank=True,
    )
    has_illness = models.BooleanField("現在病気・具合の悪い所がある", null=True, blank=True)
    illness_detail = models.CharField("具合の悪い所", max_length=200, blank=True)
    business_type = models.CharField(
        "①中小企業主・一人親方",
        max_length=20,
        choices=BusinessType.choices,
        blank=True,
    )
    received_employment_document = models.BooleanField(
        "②雇用に関する文書の交付を受けた",
        null=True,
        blank=True,
    )
    received_safety_education = models.BooleanField(
        "③安全衛生教育を受けた",
        null=True,
        blank=True,
    )
    paying_company = models.CharField(
        "④直接給料をもらっている会社名",
        max_length=100,
        blank=True,
    )
    special_accident_insurance = models.BooleanField(
        "⑤労災保険特別加入に加入している",
        null=True,
        blank=True,
    )
    has_retirement_system = models.BooleanField(
        "⑥会社に退職金制度がある",
        null=True,
        blank=True,
    )
    has_kentaikyo_book = models.BooleanField(
        "⑦建設業退職金共済手帳を持っている",
        null=True,
        blank=True,
    )

    signature = models.TextField("自筆サイン", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "安全作業確認書"
        verbose_name_plural = "安全作業確認書"
        ordering = ["-entry_date", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "site", "worker"],
                name="safety_entry_confirmation_unique",
            ),
        ]

    def __str__(self):
        return f"{self.site} - {self.worker}"


class KySheet(TenantModel):
    """KY用紙（安全作業指示書）。現場ごとに1日1枚。

    危険（リスク）の行と SC-5 の朝礼時確認は、行の数が様式で決まっているので JSON で持つ。
      risks      … [{"hazard": 予想される危険, "level": "大"|"中"|"小"|"", "measure": 低減措置,
                     "checked": 作業中確認}, ...]（最大 RISK_ROWS 行）
      sc5_checks … [True/False, ...]（SC5_ROWS 行ぶん）
    サインは4か所（指導事項・確認・作業完了報告・現場巡視指導記録）。
    """

    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="ky_sheets",
        verbose_name="現場",
    )
    work_date = models.DateField("作業日")
    crew_name = models.CharField("作業班名", max_length=100, blank=True)
    planned_headcount = models.PositiveSmallIntegerField("予定人数", null=True, blank=True)
    work_start = models.TimeField("作業開始", null=True, blank=True)
    work_end = models.TimeField("作業終了", null=True, blank=True)
    leader_name = models.CharField("作業責任者", max_length=100, blank=True)

    work_content = models.TextField("作業場所と作業内容", blank=True)
    safety_instructions = models.TextField("作業責任者からの安全指示", blank=True)
    extra_check_7 = models.CharField("作成時の注意ポイント⑦", max_length=100, blank=True)
    extra_check_8 = models.CharField("作成時の注意ポイント⑧", max_length=100, blank=True)
    risks = models.JSONField("予想される危険と低減措置", default=list, blank=True)
    sc5_extra_5 = models.CharField("SC-5確認項目5", max_length=100, blank=True)
    sc5_extra_6 = models.CharField("SC-5確認項目6", max_length=100, blank=True)
    sc5_checks = models.JSONField("SC-5の朝礼時確認", default=list, blank=True)
    remarks = models.TextField("備考", blank=True)

    guidance = models.TextField("指導事項", blank=True)
    guidance_signature = models.TextField("指導事項のサイン（現場代理人または代務者）", blank=True)
    confirm_signature = models.TextField("確認のサイン（現場代理人または代務者）", blank=True)
    completion_signature = models.TextField("作業完了報告のサイン（作業責任者）", blank=True)
    patrol_record = models.TextField("現場巡視指導記録", blank=True)
    patrol_signature = models.TextField(
        "現場巡視指導記録のサイン（現場代理人または代務者）",
        blank=True,
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "KY用紙"
        verbose_name_plural = "KY用紙"
        ordering = ["-work_date", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "site", "work_date"],
                name="safety_ky_sheet_unique",
            ),
        ]

    def __str__(self):
        return f"{self.site} - {self.work_date}"


class KyParticipant(TenantModel):
    """KY用紙の参加者1人ぶんの行（氏名の自筆サイン・健康状態・検電器）。

    自分のスマホで書いても、1台のスマホを回して書いてもよい（紙の用紙と同じ使い方）。
    同じ人が書き直したら行を上書きする。
    """

    class Health(models.TextChoices):
        GOOD = "good", "○（良好）"
        POOR = "poor", "△（不調）"

    class Tester(models.TextChoices):
        CARRYING = "carrying", "○（携帯している）"
        NOT_CARRYING = "not_carrying", "×（持っていない）"
        NOT_NEEDED = "not_needed", "－（検電器が不要な作業）"

    HEALTH_MARKS = {Health.GOOD: "○", Health.POOR: "△"}
    TESTER_MARKS = {Tester.CARRYING: "○", Tester.NOT_CARRYING: "×", Tester.NOT_NEEDED: "－"}

    sheet = models.ForeignKey(
        KySheet,
        on_delete=models.CASCADE,
        related_name="participants",
        verbose_name="KY用紙",
    )
    worker = models.ForeignKey(
        "workers.Worker",
        on_delete=models.CASCADE,
        related_name="ky_participations",
        verbose_name="作業員",
    )
    health = models.CharField(
        "健康状態",
        max_length=10,
        choices=Health.choices,
        default=Health.GOOD,
    )
    health_note = models.CharField("不調の症状", max_length=200, blank=True)
    tester = models.CharField("検電器", max_length=20, choices=Tester.choices)
    signature = models.TextField("氏名（自筆サイン）")
    signed_at = models.DateTimeField("サインした日時", default=timezone.now)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "KY用紙の参加者"
        verbose_name_plural = "KY用紙の参加者"
        ordering = ["signed_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["sheet", "worker"],
                name="safety_ky_participant_unique",
            ),
        ]

    def __str__(self):
        return f"{self.sheet} - {self.worker}"

    @property
    def health_mark(self):
        return self.HEALTH_MARKS.get(self.health, "")

    @property
    def tester_mark(self):
        return self.TESTER_MARKS.get(self.tester, "")
