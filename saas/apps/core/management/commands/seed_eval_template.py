"""テナントに評価テンプレートの初期データを投入するコマンド。

static/data/ の JSON をテナントの EvaluationTemplate にコピーする。
既存テンプレートがあればスキップ。

Usage: python manage.py seed_eval_template --company ケンモチ電機
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.tenants.models import Company
from apps.workers.models import EvaluationTemplate

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "static" / "data"


class Command(BaseCommand):
    help = "テナントに評価テンプレートを投入"

    def add_arguments(self, parser):
        parser.add_argument(
            "--company", default="ケンモチ電機", help="会社名 (default: ケンモチ電機)",
        )
        parser.add_argument(
            "--force", action="store_true", help="既存テンプレートがあっても上書き",
        )

    def handle(self, *args, **options):
        company = Company.objects.get(name=options["company"])

        existing = EvaluationTemplate.unscoped.filter(
            company=company, is_active=True,
        ).first()

        if existing and not options["force"]:
            self.stdout.write(
                f"テンプレート「{existing.name}」が既に存在します。"
                " --force で上書きできます。"
            )
            return

        with open(DATA_DIR / "eval_items.json", encoding="utf-8") as f:
            eval_items = json.load(f)
        with open(DATA_DIR / "survey_questions.json", encoding="utf-8") as f:
            survey = json.load(f)

        if existing:
            existing.sections = eval_items
            existing.survey_items = survey["items"]
            existing.scale = survey["scale"]
            existing.overall = survey["overall"]
            existing.save()
            self.stdout.write(self.style.SUCCESS(
                f"テンプレート「{existing.name}」を更新しました。"
            ))
        else:
            EvaluationTemplate.unscoped.create(
                company=company,
                name="標準評価テンプレート",
                sections=eval_items,
                survey_items=survey["items"],
                scale=survey["scale"],
                overall=survey["overall"],
                is_active=True,
            )
            self.stdout.write(self.style.SUCCESS(
                f"「{company.name}」に標準評価テンプレートを作成しました。"
            ))
