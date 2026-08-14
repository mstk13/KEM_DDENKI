"""全省庁統一資格の資格審査結果通知書データを登録する。

使い方:
    python manage.py seed_qualifications
    python manage.py seed_qualifications --replace  # 既存データを置換
"""
from django.core.management.base import BaseCommand

from apps.bids.models import Qualification
from apps.tenants.models import Company

# 資格審査結果通知書（全省庁統一資格）
# 発行番号：250128000135
# 業者コード：0000206312
# 法人番号：5021001019709
QUALIFICATIONS = [
    {
        "issuer": "全省庁統一資格",
        "category": "物品の販売",
        "grade": "C",
        "keisin_score": None,
        "total_score": 62,
        "vendor_number": "0000206312",
        "valid_from": "2025-04-01",
        "valid_until": "2028-03-31",
        "application_type": "全省庁統一資格",
        "application_method": "",
        "memo": (
            "営業品目: 電気・通信用機器類／精密機器類／その他機器類／"
            "土木・建設・建築材料／その他"
        ),
    },
    {
        "issuer": "全省庁統一資格",
        "category": "役務の提供等",
        "grade": "C",
        "keisin_score": None,
        "total_score": 62,
        "vendor_number": "0000206312",
        "valid_from": "2025-04-01",
        "valid_until": "2028-03-31",
        "application_type": "全省庁統一資格",
        "application_method": "",
        "memo": "営業品目: 賃貸借／建物管理等各種保守管理／その他",
    },
    {
        "issuer": "全省庁統一資格",
        "category": "物品の買受け",
        "grade": "B",
        "keisin_score": None,
        "total_score": 62,
        "vendor_number": "0000206312",
        "valid_from": "2025-04-01",
        "valid_until": "2028-03-31",
        "application_type": "全省庁統一資格",
        "application_method": "",
        "memo": "",
    },
]


class Command(BaseCommand):
    help = "全省庁統一資格の資格審査結果通知書データを登録する"

    def add_arguments(self, parser):
        parser.add_argument(
            "--replace",
            action="store_true",
            help="既存の全省庁統一資格データを削除して置換する",
        )

    def handle(self, *args, **options):
        replace = options.get("replace", False)

        # 最初の会社を使用（単一テナント運用を想定）
        company = Company.objects.first()
        if not company:
            self.stderr.write(self.style.ERROR("会社データがありません。先にテナントを作成してください。"))
            return

        if replace:
            deleted, _ = Qualification.unscoped.filter(
                company=company, issuer="全省庁統一資格"
            ).delete()
            self.stdout.write(f"既存の全省庁統一資格データを {deleted} 件削除しました。")

        count = 0
        for q_data in QUALIFICATIONS:
            # 重複チェック（issuer + category + vendor_number）
            if Qualification.unscoped.filter(
                company=company,
                issuer=q_data["issuer"],
                category=q_data["category"],
                vendor_number=q_data["vendor_number"],
            ).exists():
                self.stdout.write(f"  スキップ: {q_data['issuer']} / {q_data['category']}（既存）")
                continue

            Qualification.unscoped.create(company=company, **q_data)
            count += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"  登録: {q_data['issuer']} / {q_data['category']} / {q_data['grade']}等級"
                )
            )

        self.stdout.write(self.style.SUCCESS(f"\n{count} 件の資格を登録しました。"))
