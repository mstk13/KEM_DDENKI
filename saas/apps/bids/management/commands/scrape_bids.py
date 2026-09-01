"""入札案件の自動取得コマンド。

全テナントの有効な ScrapeTarget を巡回し、新着案件を BidProject に登録する。

使用方法:
    # 全テナント
    python manage.py scrape_bids

    # 特定テナント
    python manage.py scrape_bids --company 1

    # 巡回間隔を無視して即時実行
    python manage.py scrape_bids --force

推奨cron設定:
    # 毎日朝8時に実行
    0 8 * * * docker compose exec web python manage.py scrape_bids
"""

from django.core.management.base import BaseCommand

from apps.bids.services import run_all_scrapes
from apps.core.tenant_context import set_current_company
from apps.tenants.models import Company


class Command(BaseCommand):
    help = "入札案件を官公庁サイトから自動取得する"

    def add_arguments(self, parser):
        parser.add_argument(
            "--company",
            type=int,
            help="特定テナントのみ実行（company PK）",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="巡回間隔を無視して即時実行",
        )

    def handle(self, *args, **options):
        company_pk = options.get("company")
        force = options.get("force", False)

        if company_pk:
            companies = Company.objects.filter(pk=company_pk, is_active=True)
        else:
            companies = Company.objects.filter(is_active=True)

        for company in companies:
            set_current_company(company)
            self.stdout.write(f"\n--- {company.name} ---")

            if force:
                # 巡回間隔をリセット
                from apps.bids.models import ScrapeTarget
                ScrapeTarget.unscoped.filter(
                    company=company, is_active=True,
                ).update(last_scraped_at=None)

            result = run_all_scrapes(company)

            self.stdout.write(
                f"  処理: {result['targets_processed']}ターゲット, "
                f"新規: {result['total_new']}件"
            )
            if result["total_new"] > 0:
                self.stdout.write(
                    self.style.SUCCESS(f"  → {result['total_new']}件の新着を通知しました")
                )
            if result["errors"]:
                for err in result["errors"][:5]:
                    self.stderr.write(f"  エラー: {err}")

        set_current_company(None)
        self.stdout.write(self.style.SUCCESS("\n完了"))
