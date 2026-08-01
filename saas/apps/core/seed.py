"""初期データ投入: 原価区分 + Django Group。

Usage: python manage.py shell < apps/core/seed.py
"""

from django.contrib.auth.models import Group

from apps.masters.models import CostCategory

# 建設業4原価区分（システム定義・全テナント共通）
COST_CATEGORIES = [
    ("material", "材料費", 1),
    ("labor", "労務費", 2),
    ("outsourcing", "外注費", 3),
    ("expense", "経費", 4),
]

for code, name, order in COST_CATEGORIES:
    CostCategory.objects.update_or_create(
        code=code,
        defaults={"name": name, "display_order": order},
    )

# 初期グループ（ロール）
for group_name in ("admin", "manager", "worker"):
    Group.objects.get_or_create(name=group_name)

print("Seed data created: 4 cost categories, 3 groups")
