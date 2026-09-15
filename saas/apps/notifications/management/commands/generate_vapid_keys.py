"""スマホへのプッシュ通知（ADR-0062）に使う鍵を作る。

    python manage.py generate_vapid_keys

出てきた WEBPUSH_VAPID_PRIVATE_KEY= の行を、サーバーの .env に足す（本番と開発で別の鍵にする）。
秘密鍵はコミットしない・人に見せない。鍵を作り直すと、端末は次に画面を開いたときに登録し直す。
"""

from django.core.management.base import BaseCommand

from apps.notifications.push import generate_vapid_keys


class Command(BaseCommand):
    help = "スマホへのプッシュ通知に使う鍵を作り、.env に書く行を出す"

    def handle(self, *args, **options):
        private_key, public_key = generate_vapid_keys()
        self.stdout.write(
            "# サーバーの .env に足してください（秘密鍵はコミットしない・人に見せない）"
        )
        self.stdout.write(f"WEBPUSH_VAPID_PRIVATE_KEY={private_key}")
        self.stdout.write(
            f"# 公開鍵（参考。アプリが秘密鍵から計算するので .env には要りません）: {public_key}"
        )
