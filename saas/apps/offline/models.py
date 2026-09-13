"""圏外で端末に保存し、あとで送られてきた入力の受付記録（ADR-0048）。"""

from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class OfflineSubmission(TenantModel):
    """端末が付けた識別番号ごとに、送信を1回だけ受け付けた記録。

    圏外で保存した入力は、電波が戻ったときに自動で送り直す。電波の弱い場所では
    「サーバーには届いたが、応答が端末に戻らなかった」ことが起きるので、同じ入力が
    2回届きうる。識別番号で2回目を見分け、登録を二重にしない。
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="offline_submissions",
        verbose_name="送信者",
    )
    client_request_id = models.UUIDField("端末が付けた識別番号")
    path = models.CharField("送信先", max_length=300)
    location = models.CharField("登録後の移動先", max_length=500, blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "圏外保存からの送信"
        verbose_name_plural = "圏外保存からの送信"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "user", "client_request_id"],
                name="offline_submission_unique",
            ),
        ]

    def __str__(self):
        return f"{self.user} {self.path} {self.client_request_id}"
