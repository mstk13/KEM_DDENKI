"""初期データ投入コマンド。"""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.masters.models import CostCategory
from apps.tenants.models import Company
from apps.workers.models import JobTitle, Position


class Command(BaseCommand):
    help = "原価区分・初期グループ・職種・役職のシードデータを投入"

    def add_arguments(self, parser):
        parser.add_argument(
            "--company", default="", help="職種・役職を投入する会社名（省略時はスキップ）",
        )

    def handle(self, *args, **options):
        # 原価区分（全テナント共通）
        cost_categories = [
            ("material", "材料費", 1),
            ("labor", "労務費", 2),
            ("outsourcing", "外注費", 3),
            ("expense", "経費", 4),
        ]
        for code, name, order in cost_categories:
            CostCategory.objects.update_or_create(
                code=code,
                defaults={"name": name, "display_order": order},
            )

        # Django グループ
        for group_name in ("admin", "manager", "worker"):
            Group.objects.get_or_create(name=group_name)

        self.stdout.write(self.style.SUCCESS("原価区分・グループを投入しました。"))

        # テナント別 職種・役職
        company_name = options.get("company")
        if not company_name:
            return

        company = Company.objects.filter(name=company_name).first()
        if not company:
            self.stdout.write(f"会社「{company_name}」が見つかりません。")
            return

        job_titles = ["電工", "事務", "管理", "社長", "ITインフラ"]
        for name in job_titles:
            JobTitle.unscoped.get_or_create(company=company, name=name)

        positions = [
            ("社長", 1),
            ("役員", 2),
            ("正社員", 3),
            ("シニア", 4),
            ("ジュニア", 5),
            ("試用期間", 6),
            ("パート", 7),
            ("Developer", 8),
            ("アルバイト", 9),
        ]
        for name, rank in positions:
            Position.unscoped.update_or_create(
                company=company, name=name,
                defaults={"rank": rank},
            )

        self.stdout.write(self.style.SUCCESS(
            f"「{company.name}」に職種{len(job_titles)}件・役職{len(positions)}件を投入しました。"
        ))

        # アラートルール（書類未添付・健診期限）
        from apps.notifications.models import AlertRule, Notification

        alert_rules = [
            ("cert_missing", "証明書未添付アラート"),
            ("health_report_missing", "健診報告書未添付アラート"),
            ("health_checkup_due", "健診期限アラート（2ヶ月前）"),
        ]
        for alert_type, name in alert_rules:
            AlertRule.unscoped.get_or_create(
                company=company,
                alert_type=alert_type,
                defaults={
                    "name": name,
                    "is_active": True,
                    "notification_level": Notification.Level.WARNING,
                    "notify_channels": ["in_app", "email"],
                    "notify_roles": ["office_staff"],
                },
            )
        self.stdout.write(self.style.SUCCESS(
            f"「{company.name}」にアラートルール{len(alert_rules)}件を投入しました。"
        ))
