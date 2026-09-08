"""全省庁統一資格の「省庁別許可内容一覧」Excel を読み込んで登録する。

使い方:
    python manage.py import_unified_qualifications <xlsx>
    python manage.py import_unified_qualifications <xlsx> --replace  # 既存を全て置換
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.bids.importer import import_unified_excel
from apps.bids.models import UnifiedQualification
from apps.tenants.models import Company


class Command(BaseCommand):
    help = "全省庁統一資格の省庁別許可内容一覧（Excel）を登録する"

    def add_arguments(self, parser):
        parser.add_argument("xlsx", help="省庁別許可内容一覧を含む Excel ファイル")
        parser.add_argument(
            "--replace", action="store_true",
            help="既存の省庁別データを全て削除してから登録する",
        )
        parser.add_argument(
            "--company", type=int, default=None,
            help="登録先の会社ID（省略時は最初の会社）",
        )

    def handle(self, *args, **options):
        if options["company"]:
            company = Company.objects.filter(pk=options["company"]).first()
        else:
            # 単一テナント運用を想定し、最初の会社に登録する
            company = Company.objects.first()
        if not company:
            raise CommandError("会社データがありません。先にテナントを作成してください。")

        try:
            records = import_unified_excel(options["xlsx"])
        except Exception as e:  # noqa: BLE001 - ファイル起因のエラーは全て利用者に見せる
            raise CommandError(f"読み込みに失敗しました: {e}") from e
        if not records:
            raise CommandError("登録できる行がありません。")

        created = updated = 0
        with transaction.atomic():
            if options["replace"]:
                deleted, _ = UnifiedQualification.unscoped.filter(company=company).delete()
                self.stdout.write(f"既存データを {deleted} 件削除しました。")
            for rec in records:
                _obj, was_created = UnifiedQualification.unscoped.update_or_create(
                    company=company, agency=rec["agency"],
                    defaults={k: v for k, v in rec.items() if k != "agency"},
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"{company.name}: {created} 件登録、{updated} 件更新しました"
            f"（全 {len(records)} 機関）。"
        ))
