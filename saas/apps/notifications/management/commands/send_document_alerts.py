"""
書類未添付・健診期限アラートを全テナントに送信する管理コマンド。

cron 例（毎朝8時）:
    docker compose exec web python manage.py send_document_alerts

Usage:
    python manage.py send_document_alerts
    python manage.py send_document_alerts --company "ケンモチ電機"
"""

from django.core.management.base import BaseCommand

from apps.notifications.services import (
    check_certificate_missing_alerts,
    check_health_checkup_due_alerts,
    check_health_report_missing_alerts,
)
from apps.tenants.models import Company


class Command(BaseCommand):
    help = "証明書・健診書類の未添付アラートと健診期限アラートを送信"

    def add_arguments(self, parser):
        parser.add_argument(
            "--company",
            default="",
            help="特定会社名のみ実行（省略時は全テナント）",
        )

    def handle(self, *args, **options):
        company_name = options.get("company", "")
        qs = Company.objects.all()
        if company_name:
            qs = qs.filter(name=company_name)

        for company in qs:
            self.stdout.write(f"[{company.name}] アラートチェック開始")
            check_certificate_missing_alerts(company)
            check_health_report_missing_alerts(company)
            check_health_checkup_due_alerts(company)
            self.stdout.write(self.style.SUCCESS(f"[{company.name}] 完了"))
