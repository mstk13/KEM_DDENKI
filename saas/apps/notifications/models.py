"""
通知基盤モデル。

全モジュール共通の通知（アプリ内・メール・Discord）と
アラートルール（閾値ベースの自動発火）を管理する。
"""

from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class Notification(TenantModel):
    """アプリ内通知。全モジュールからの通知を一元管理する。"""

    class Level(models.TextChoices):
        INFO = "info", "情報"
        WARNING = "warning", "警告"
        ERROR = "error", "緊急"

    class Channel(models.TextChoices):
        IN_APP = "in_app", "アプリ内"
        EMAIL = "email", "メール"
        DISCORD = "discord", "Discord"

    class Module(models.TextChoices):
        REPORTS = "reports", "日報管理"
        COSTS = "costs", "原価管理"
        MATERIALS = "materials", "材料管理"
        BIDS = "bids", "入札管理"
        SCHEDULES = "schedules", "工期管理"
        WORKERS = "workers", "人材管理"
        DEVKANRI = "devkanri", "開発管理"
        MASTERS = "masters", "取引先管理"
        SAFETY = "safety", "安全書類"
        SYSTEM = "system", "システム"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="通知先",
    )
    title = models.CharField("タイトル", max_length=300)
    body = models.TextField("本文", blank=True)
    level = models.CharField(
        "重要度",
        max_length=10,
        choices=Level.choices,
        default=Level.INFO,
    )
    module = models.CharField(
        "発生モジュール",
        max_length=20,
        choices=Module.choices,
    )
    channel = models.CharField(
        "通知チャネル",
        max_length=10,
        choices=Channel.choices,
        default=Channel.IN_APP,
    )
    # 通知元のオブジェクトへの汎用リンク
    reference_type = models.CharField(
        "参照先モデル",
        max_length=100,
        blank=True,
        help_text="例: 'costs.BudgetItem', 'workers.WorkerQualification'",
    )
    reference_id = models.PositiveBigIntegerField("参照先ID", null=True, blank=True)
    reference_url = models.CharField("参照先URL", max_length=500, blank=True)

    is_read = models.BooleanField("既読", default=False)
    read_at = models.DateTimeField("既読日時", null=True, blank=True)
    sent_at = models.DateTimeField("送信日時", auto_now_add=True)
    # スマホへのプッシュ通知（ADR-0062）の送り出しを済ませた日時。
    # 送る端末が無かった・既読だった知らせにも付ける（次の回に拾い直さないため）。
    pushed_at = models.DateTimeField("プッシュ送信日時", null=True, blank=True)

    class Meta:
        verbose_name = "通知"
        verbose_name_plural = "通知"
        ordering = ["-sent_at"]
        indexes = [
            models.Index(fields=["recipient", "is_read", "-sent_at"]),
            models.Index(fields=["module", "-sent_at"]),
        ]

    def __str__(self):
        return f"[{self.get_level_display()}] {self.title}"


class PushSubscription(TenantModel):
    """スマホへのプッシュ通知の送り先（端末1台・ブラウザ1つにつき1件）。ADR-0062。

    endpoint はブラウザがプッシュサービス（Google・Apple など）から受け取る送り先の URL。
    p256dh と auth は、その端末だけが読めるように中身を暗号化するための鍵（RFC 8291）。
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
        verbose_name="通知先",
    )
    # 端末の送り先は会社をまたいで一意。別の人がこの端末でオンにしたら付け替える
    endpoint = models.CharField("送り先", max_length=1000, unique=True)
    p256dh = models.CharField("端末の公開鍵", max_length=200)
    auth = models.CharField("端末の認証用の値", max_length=100)
    user_agent = models.CharField("ブラウザ", max_length=300, blank=True)
    last_success_at = models.DateTimeField("最後に届けた日時", null=True, blank=True)
    failure_count = models.PositiveSmallIntegerField("続けて失敗した回数", default=0)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "プッシュ通知の送り先"
        verbose_name_plural = "プッシュ通知の送り先"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} ({self.user_agent[:40] or '端末'})"


class AlertRule(TenantModel):
    """アラートルール。閾値ベースの自動通知を定義する。

    例: 原価の予算消化率が75%を超えたら警告通知を出す
    """

    class AlertType(models.TextChoices):
        COST_THRESHOLD = "cost_threshold", "原価閾値"
        QUALIFICATION_EXPIRY = "qualification_expiry", "資格期限"
        SCHEDULE_DELAY = "schedule_delay", "工期遅延"
        BID_DEADLINE = "bid_deadline", "入札期限"
        SAFETY_INCOMPLETE = "safety_incomplete", "安全書類未記入"
        CERT_MISSING = "cert_missing", "証明書未添付"
        HEALTH_REPORT_MISSING = "health_report_missing", "健診報告書未添付"
        HEALTH_CHECKUP_DUE = "health_checkup_due", "健診期限"

    name = models.CharField("ルール名", max_length=200)
    alert_type = models.CharField(
        "アラート種別",
        max_length=30,
        choices=AlertType.choices,
    )
    is_active = models.BooleanField("有効", default=True)
    threshold_value = models.IntegerField(
        "閾値",
        null=True,
        blank=True,
        help_text="原価: 消化率(%), 資格: 残日数, 工期: 残日数, 入札: 残日数",
    )
    notification_level = models.CharField(
        "通知レベル",
        max_length=10,
        choices=Notification.Level.choices,
        default=Notification.Level.WARNING,
    )
    notify_channels = models.JSONField(
        "通知チャネル",
        default=list,
        help_text='例: ["in_app", "email"]',
    )
    notify_roles = models.JSONField(
        "通知先ロール",
        default=list,
        help_text='例: ["president", "executive"]',
    )

    class Meta:
        verbose_name = "アラートルール"
        verbose_name_plural = "アラートルール"
        ordering = ["alert_type", "threshold_value"]

    def __str__(self):
        return f"{self.name} ({self.get_alert_type_display()})"


class AlertLog(TenantModel):
    """アラート発火履歴。同一条件での重複通知を防止する。"""

    alert_rule = models.ForeignKey(
        AlertRule,
        on_delete=models.CASCADE,
        related_name="logs",
        verbose_name="アラートルール",
    )
    reference_type = models.CharField("参照先モデル", max_length=100)
    reference_id = models.PositiveBigIntegerField("参照先ID")
    triggered_at = models.DateTimeField("発火日時", auto_now_add=True)
    detail = models.TextField("詳細", blank=True)

    class Meta:
        verbose_name = "アラート履歴"
        verbose_name_plural = "アラート履歴"
        indexes = [
            models.Index(fields=["alert_rule", "reference_type", "reference_id"]),
        ]

    def __str__(self):
        return f"{self.alert_rule.name} @ {self.triggered_at}"
