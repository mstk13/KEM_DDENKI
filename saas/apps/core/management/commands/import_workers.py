"""作業員名簿（JSON）からWorkerデータをインポートするコマンド。

Usage: python manage.py import_workers /path/to/workers.json
"""

import json

from django.core.management.base import BaseCommand

from apps.tenants.models import Company
from apps.workers.models import JobTitle, Worker


class Command(BaseCommand):
    help = "JSONファイルから作業員データをインポート"

    def add_arguments(self, parser):
        parser.add_argument("json_file", help="JSONファイルのパス")
        parser.add_argument(
            "--company", default="ケンモチ電機", help="会社名 (default: ケンモチ電機)",
        )

    def handle(self, *args, **options):
        company, _ = Company.objects.get_or_create(
            name=options["company"],
            defaults={"industry_type": "設備工事"},
        )

        with open(options["json_file"], encoding="utf-8") as f:
            workers_data = json.load(f)

        created = 0
        updated = 0

        for w in workers_data:
            job_title = None
            if w.get("job_type"):
                job_title, _ = JobTitle.unscoped.get_or_create(
                    company=company, name=w["job_type"],
                )

            hire_date = w.get("hire_date") or None
            furigana = w.get("furigana", "")
            skill_tags = w.get("qualifications", [])

            worker, is_new = Worker.unscoped.update_or_create(
                company=company,
                name=w["name"],
                defaults={
                    "name_kana": furigana,
                    "job_title": job_title,
                    "hire_date": hire_date,
                    "skill_tags": skill_tags,
                    "hourly_cost": 0,
                    "is_active": True,
                },
            )

            if is_new:
                created += 1
                self.stdout.write(f"  + {worker.name} ({furigana})")
            else:
                updated += 1
                self.stdout.write(f"  ~ {worker.name} ({furigana})")

        self.stdout.write(
            self.style.SUCCESS(
                f"\n完了: {created}名追加, {updated}名更新 (会社: {company.name})"
            )
        )
