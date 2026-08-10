"""6ヶ月以上前の変更履歴を削除する。

定期実行推奨: crontab で月1回実行
  python manage.py cleanup_history
  python manage.py cleanup_history --months 3  # 3ヶ月で削除

simple_history の HistoricalRecords テーブルから古いレコードを削除する。
"""

import logging
from datetime import timedelta

from django.apps import apps
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "6ヶ月以上前の simple_history レコードを削除する"

    def add_arguments(self, parser):
        parser.add_argument(
            "--months",
            type=int,
            default=6,
            help="保存期間（月数）。デフォルト6ヶ月。",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="実際には削除せず、削除対象件数のみ表示する。",
        )

    def handle(self, *args, **options):
        months = options["months"]
        dry_run = options["dry_run"]
        cutoff = timezone.now() - timedelta(days=months * 30)

        self.stdout.write(
            f"保存期間: {months}ヶ月 / カットオフ: {cutoff:%Y-%m-%d %H:%M}"
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN モード（削除しません）"))

        total_deleted = 0

        # simple_history のモデルを全て探す
        for model in apps.get_models():
            if not model.__name__.startswith("Historical"):
                continue

            # history_date フィールドで古いレコードを検索
            if not hasattr(model, "history_date"):
                continue

            old_count = model.objects.filter(history_date__lt=cutoff).count()
            if old_count == 0:
                continue

            self.stdout.write(
                f"  {model._meta.label}: {old_count} 件"
            )

            if not dry_run:
                deleted, _ = model.objects.filter(history_date__lt=cutoff).delete()
                total_deleted += deleted
            else:
                total_deleted += old_count

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"合計 {total_deleted} 件が削除対象です")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"合計 {total_deleted} 件を削除しました")
            )
