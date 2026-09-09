from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class AttendReport(TenantModel):
    """勤怠日報ヘッダ。1日1現場の出勤記録をまとめる。"""

    class Status(models.TextChoices):
        UNCONFIRMED = "未確認", "未確認"
        CONFIRMED = "確認済", "確認済"
        APPROVED = "承認済", "承認済"
        REJECTED = "差戻し", "差戻し"

    report_date = models.DateField("日付")
    site_name = models.CharField("現場名", max_length=255, blank=True)
    work_content = models.TextField("作業内容", blank=True)
    note = models.TextField("備考", blank=True)
    status = models.CharField(
        "状態",
        max_length=20,
        choices=Status.choices,
        default=Status.UNCONFIRMED,
    )
    source_text = models.TextField("元テキスト", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "勤怠日報"
        verbose_name_plural = "勤怠日報"
        ordering = ["-report_date"]

    def __str__(self):
        return f"{self.report_date} {self.site_name}"


class AttendEntry(TenantModel):
    """作業員ごとの勤怠エントリ。"""

    report = models.ForeignKey(
        AttendReport,
        on_delete=models.CASCADE,
        related_name="entries",
        verbose_name="勤怠日報",
    )
    worker = models.ForeignKey(
        "workers.Worker",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attend_entries",
        verbose_name="作業員",
    )
    employee_name = models.CharField("氏名", max_length=100)
    start_time = models.CharField("開始時刻", max_length=10, blank=True)
    end_time = models.CharField("終了時刻", max_length=10, blank=True)
    break_minutes = models.IntegerField("休憩(分)", default=60)
    early_minutes = models.IntegerField("早出(分)", default=0)
    normal_minutes = models.IntegerField("所定(分)", default=0)
    overtime_minutes = models.IntegerField("残業(分)", default=0)
    total_minutes = models.IntegerField("合計(分)", default=0)
    note = models.TextField("備考", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "勤怠エントリ"
        verbose_name_plural = "勤怠エントリ"
        ordering = ["employee_name"]

    def __str__(self):
        return f"{self.employee_name} ({self.report.report_date})"


class AttendPlan(TenantModel):
    """出社予定。作業員1人・1日ぶんの予定を1件で持つ。

    実績（AttendReport / AttendEntry）とは別テーブルにする。予定は先の日付を
    先回りで埋めるもので、実績は日報から後で入る。同じ行に持つと
    「予定のまま実績が入っていない日」と「休みだった日」の区別が付かなくなる。

    予定が無い日は行を作らない（＝未定）。月の全マスに行を作ると、
    人数×日数ぶんの空行が毎月増えるだけで読み取れる情報が増えない。
    """

    class Kind(models.TextChoices):
        OFFICE = "office", "出社"
        SITE = "site", "現場"
        DIRECT = "direct", "直行直帰"
        REMOTE = "remote", "在宅"
        TRIP = "trip", "出張"
        PAID = "paid", "有休"
        HALF = "half", "半休"
        OFF = "off", "休み"

    # 「その日に稼働する」とみなす区分。日ごとの出社人数はこれで数える。
    # 在宅・有休・休みは人数に入れない。半休は現場に出るとは限らないため除く。
    WORKING_KINDS = ("office", "site", "direct", "trip")

    # 予定表のマスに出す1文字。31日ぶんを横に並べるので、
    # 「直行直帰」のような語をそのまま出すと列が広がりすぎて月が一覧できない。
    # 正式名称はパレット・凡例・日別画面・ツールチップに出る。
    SHORT_LABELS = {
        "office": "出",
        "site": "現",
        "direct": "直",
        "remote": "宅",
        "trip": "張",
        "paid": "有",
        "half": "半",
        "off": "休",
    }

    # 区分ごとに何を登録させるか。画面の入力欄の出し分けはこの定義に従う。
    #   time  … 開始・終了時刻を訊く
    #   place … 場所の入力欄のラベル。空なら訊かない
    #   span  … 複数日にまたがる登録（何日から何日まで）を許す
    # 出張だけ span を持つ。行先へ行って戻るまでが1件の予定で、
    # 曜日をまたぐのが普通のため。保存時は日ごとの行に展開する
    # （1日1行という持ち方を崩すと、出社人数の集計と月グリッドが成り立たない）。
    KIND_FIELDS = {
        "office": {"time": True, "place": "", "span": False},
        "site": {"time": True, "place": "現場名", "span": False},
        "direct": {"time": True, "place": "現場名", "span": False},
        "remote": {"time": True, "place": "", "span": False},
        "trip": {"time": False, "place": "行先", "span": True},
        "paid": {"time": False, "place": "", "span": False},
        "half": {"time": True, "place": "", "span": False},
        "off": {"time": False, "place": "", "span": False},
    }

    # 出張などで一度に展開できる日数の上限。
    # 日付の打ち間違い（2026 → 2036）で数千行作らないための歯止め。
    MAX_SPAN_DAYS = 92

    worker = models.ForeignKey(
        "workers.Worker",
        on_delete=models.CASCADE,
        related_name="attend_plans",
        verbose_name="作業員",
    )
    plan_date = models.DateField("予定日")
    kind = models.CharField(
        "区分", max_length=20, choices=Kind.choices, default=Kind.OFFICE,
    )
    # 空なら「所定どおり」。AttendSettings の standard_start / standard_end を
    # 既定として画面に出すが、値はコピーせず空のままにする。
    # コピーすると所定時間を変えたときに過去の予定まで書き換わってしまう。
    start_time = models.TimeField("開始時刻", null=True, blank=True)
    end_time = models.TimeField("終了時刻", null=True, blank=True)
    # 現場・直行直帰なら現場名、出張なら行先。区分ごとに意味が変わるだけで
    # 「どこへ行くか」という同じ情報なので、列は分けない。
    # 画面側のラベルは KIND_FIELDS の place を使う。
    note = models.CharField(
        "場所・メモ", max_length=200, blank=True,
        help_text="現場名・行き先など",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "出社予定"
        verbose_name_plural = "出社予定"
        ordering = ["plan_date", "worker__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "worker", "plan_date"],
                name="uniq_attend_plan_worker_date",
            ),
        ]

    def __str__(self):
        return f"{self.worker} {self.plan_date} {self.get_kind_display()}"

    @property
    def is_working(self) -> bool:
        """その日に稼働する予定か。"""
        return self.kind in self.WORKING_KINDS

    @property
    def short_label(self) -> str:
        """予定表のマスに出す1文字。"""
        return self.SHORT_LABELS.get(self.kind, "")

    @property
    def time_label(self) -> str:
        """マスに出す短い時刻表記。「9-17」「9:30-17」。時刻未設定なら空。"""
        return format_time_range(self.start_time, self.end_time)


def format_time_range(start, end) -> str:
    """時刻の組を短く書く。予定表のマスは狭いので分は0のとき省く。

    夜間工事があるため終了が開始より早い組み合わせも許す（日をまたぐ想定）。
    """
    def fmt(value):
        return f"{value.hour}:{value.minute:02d}" if value.minute else str(value.hour)

    if start and end:
        return f"{fmt(start)}-{fmt(end)}"
    if start:
        return f"{fmt(start)}-"
    if end:
        return f"-{fmt(end)}"
    return ""


class AttendSettings(TenantModel):
    """勤怠計算用のキーバリュー設定。"""

    key = models.CharField("設定キー", max_length=50)
    value = models.CharField("設定値", max_length=100)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "勤怠設定"
        verbose_name_plural = "勤怠設定"
        unique_together = [("company", "key")]

    def __str__(self):
        return f"{self.key}={self.value}"

    # デフォルト設定キー
    DEFAULTS = {
        "standard_start": "08:00",
        "standard_end": "17:00",
        "early_boundary": "08:00",
        "standard_hours": "8.0",
        "break_minutes": "60",
        "round_minutes": "0",
        "overtime_mode": "clock",
    }

    @classmethod
    def get_settings_dict(cls, company):
        """会社の全設定を辞書で返す。未設定キーはデフォルト値を使用。"""
        saved = dict(
            cls.unscoped.filter(company=company).values_list("key", "value")
        )
        result = dict(cls.DEFAULTS)
        result.update(saved)
        return result
