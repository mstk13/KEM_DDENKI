"""コスト予測モデルの学習コマンド。

使い方:
    python manage.py train_cost_model              # 全テナント
    python manage.py train_cost_model --company-id 1  # 特定テナント
"""

from django.core.management.base import BaseCommand

from apps.ai.services.ml_predictor import CostPredictor
from apps.tenants.models import Company


class Command(BaseCommand):
    help = "LightGBM コスト予測モデルを学習する"

    def add_arguments(self, parser):
        parser.add_argument(
            "--company-id",
            type=int,
            default=None,
            help="特定テナントのIDを指定（省略時は全テナント）",
        )

    def handle(self, *args, **options):
        predictor = CostPredictor()
        company_id = options["company_id"]

        if company_id:
            companies = Company.objects.filter(pk=company_id)
            if not companies.exists():
                self.stderr.write(
                    self.style.ERROR(f"Company ID={company_id} が見つかりません。")
                )
                return
        else:
            companies = Company.objects.all()

        for company in companies:
            self.stdout.write(f"学習開始: {company.name} (ID={company.pk})")
            result = predictor.train(company)

            if result["status"] == "success":
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  完了: {result['n_samples']}件で学習, "
                        f"CV残差σ={result['cv_residuals_std']:.4f}"
                    )
                )
            elif result["status"] == "insufficient_data":
                self.stdout.write(
                    self.style.WARNING(f"  スキップ: {result['message']}")
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f"  エラー: {result}")
                )

        self.stdout.write(self.style.SUCCESS("全テナントの学習が完了しました。"))
