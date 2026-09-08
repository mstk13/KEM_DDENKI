"""空のDBに、画面を触るための最小データを作る（開発用）。

会社1社・管理者ユーザー1人・作業員6人だけ。冪等なので何度実行してもよい。
本番データがある環境では実行しない（作業員が増えてしまう）。

    docker compose exec -T web python manage.py shell < scripts/bootstrap_demo_login.py
"""
from django.contrib.auth.models import Group

from apps.accounts.models import User
from apps.tenants.models import Company
from apps.workers.models import Worker

for name in ("admin", "manager", "worker"):
    Group.objects.get_or_create(name=name)

company, _ = Company.objects.get_or_create(
    name="ケンモチ電機",
    defaults={"industry_type": "設備工事"},
)

user, created = User.objects.get_or_create(
    username="demo",
    defaults={
        "company": company,
        "is_staff": True,
        "is_superuser": True,
        "last_name": "デモ",
        "first_name": "管理者",
    },
)
user.company = company
user.set_password("demo12345")
user.save()
user.groups.add(Group.objects.get(name="admin"))

MEMBERS = [
    ("E001", "田中 太郎"),
    ("E002", "佐藤 次郎"),
    ("E003", "鈴木 三郎"),
    ("E004", "高橋 花子"),
    ("E005", "渡辺 四郎"),
    ("E006", "伊藤 五郎"),
]
for code, name in MEMBERS:
    Worker.unscoped.get_or_create(
        company=company,
        employee_code=code,
        defaults={"name": name, "is_active": True},
    )

print("company:", company.name)
print("login:  demo / demo12345")
print("workers:", Worker.unscoped.filter(company=company).count())
