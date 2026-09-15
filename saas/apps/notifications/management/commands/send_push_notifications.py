"""まだ送っていない通知を、スマホへのプッシュ通知で送る（ADR-0062）。

scripts/scheduler.sh が1分に1回呼ぶ。送るものが無ければ何も出さない（ログを埋めないため）。
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.notifications.push import push_enabled, send_pending_pushes


class Command(BaseCommand):
    help = "まだ送っていない通知を、スマホへのプッシュ通知で送る"

    def handle(self, *args, **options):
        if not push_enabled():
            if settings.WEBPUSH_VAPID_PRIVATE_KEY:
                # 鍵を書き間違えている。黙っていると誰にも届かないので、失敗としてログに残す
                raise CommandError(
                    "WEBPUSH_VAPID_PRIVATE_KEY の形が正しくありません。"
                    "python manage.py generate_vapid_keys で作り直してください"
                )
            return
        delivered = send_pending_pushes()
        if delivered:
            stamp = f"{timezone.localtime():%Y-%m-%d %H:%M:%S}"
            self.stdout.write(f"[{stamp}] プッシュ通知を {delivered} 件届けました")
