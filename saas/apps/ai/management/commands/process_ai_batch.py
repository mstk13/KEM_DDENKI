"""バッチキューのAIリクエストを実行する。

crontab で平日9時に実行:
  0 9 * * 1-5 cd /path/to/saas && python manage.py process_ai_batch
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "待機中のAIバッチリクエストを実行する"

    def handle(self, *args, **options):
        from apps.ai.services.batch_handler import process_pending_batches

        processed = process_pending_batches()
        self.stdout.write(
            self.style.SUCCESS(f"{processed} 件のバッチリクエストを処理しました")
        )
