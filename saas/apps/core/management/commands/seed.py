"""初期データ投入コマンド。"""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.masters.models import CostCategory


class Command(BaseCommand):
    help = "原価区分・初期グループ等のシードデータを投入"

    def handle(self, *args, **options):
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

        for group_name in ("admin", "manager", "worker"):
            Group.objects.get_or_create(name=group_name)

        self.stdout.write(self.style.SUCCESS("Seed data created successfully."))
