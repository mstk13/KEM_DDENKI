"""同じ現場が別名で登録されていないかを調べ、候補を貯める（ADR-0084）。

統合はしない。候補を出すところまでで、まとめるかどうかは画面で人が決める。

夜間に1回流す想定:
    docker compose exec web python manage.py find_site_merge_candidates

    # ローカルAIを使わず、文字と手がかりだけで拾う
    docker compose exec web python manage.py find_site_merge_candidates --no-ai
"""

from django.core.management.base import BaseCommand

from apps.sites.merge_candidates import find_candidates
from apps.tenants.models import Company


class Command(BaseCommand):
    help = "現場の名寄せ候補を探す（統合はしない）"

    def add_arguments(self, parser):
        parser.add_argument("--company", default="", help="会社名（省略時は全社）")
        parser.add_argument("--no-ai", action="store_true", help="生成モデルに判定させない")
        parser.add_argument(
            "--limit", type=int, default=30, help="1回に判定させる組の上限",
        )

    def handle(self, *args, **options):
        qs = Company.objects.all()
        if options["company"]:
            qs = qs.filter(name=options["company"])

        for company in qs:
            result = find_candidates(
                company, judge=not options["no_ai"], judge_limit=options["limit"],
            )
            created, updated = len(result["created"]), len(result["updated"])
            self.stdout.write(
                f"[{company.name}] 新しい候補 {created} 件 / 見直し {updated} 件 "
                f"/ AIが判定 {result['judged']} 件",
            )
            for candidate in result["created"]:
                self.stdout.write(
                    f"  {candidate.primary.name} ← {candidate.duplicate.name}"
                    f"（{candidate.get_verdict_display()}）",
                )
        self.stdout.write(self.style.SUCCESS("完了（統合は画面から人が決めます）"))
