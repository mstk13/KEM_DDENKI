"""その日に現場へ出る人に、KY用紙・安全作業確認書の記入を知らせる（ADR-0061）。

scripts/scheduler.sh が毎朝 08:00 以降（12:00 まで）に1回実行する。

Usage:
    python manage.py send_safety_reminders
    python manage.py send_safety_reminders --company "ケンモチ電機" --date 2026-09-15
"""

import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.safety.services import send_morning_reminders
from apps.tenants.models import Company


class Command(BaseCommand):
    help = "その日に現場へ出る人に、KY用紙・安全作業確認書の記入を知らせる（毎朝8時）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--company", default="", help="特定会社名のみ実行（省略時は全テナント）"
        )
        parser.add_argument("--date", default="", help="対象日 YYYY-MM-DD（省略時は今日）")

    def handle(self, *args, **options):
        if options["date"]:
            try:
                day = datetime.date.fromisoformat(options["date"])
            except ValueError as exc:
                raise CommandError("--date は YYYY-MM-DD で指定してください。") from exc
        else:
            day = timezone.localdate()

        companies = Company.objects.all()
        if options["company"]:
            companies = companies.filter(name=options["company"])

        total = 0
        for company in companies:
            created = send_morning_reminders(company, day)
            total += created
            self.stdout.write(f"[{company.name}] {day} 安全書類の知らせ {created} 件")
        self.stdout.write(self.style.SUCCESS(f"完了（{total} 件）"))
