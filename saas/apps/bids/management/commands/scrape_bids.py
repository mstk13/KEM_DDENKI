"""入札案件スクレイピング management command。

使い方:
    python manage.py scrape_bids              # 有効な全 ScrapeTarget を実行
    python manage.py scrape_bids --target 1   # 特定の ScrapeTarget ID のみ
    python manage.py scrape_bids --dry-run    # 取得のみ（DB保存しない）
    python manage.py scrape_bids --visible    # ブラウザを表示して実行（デバッグ用）
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.bids.models import BidProject, ScrapeTarget
from apps.bids.scraper import scrape_ippi


class Command(BaseCommand):
    help = "入札情報サービス (i-ppi.jp) から入札案件をスクレイピングする"

    def add_arguments(self, parser):
        parser.add_argument(
            "--target",
            type=int,
            help="特定の ScrapeTarget ID のみ実行",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="取得のみ（DB に保存しない）",
        )
        parser.add_argument(
            "--visible",
            action="store_true",
            help="ヘッドレスモードを無効化（ブラウザを表示）",
        )

    def handle(self, *args, **options):
        target_id = options.get("target")
        dry_run = options.get("dry_run", False)
        headless = not options.get("visible", False)

        # unscoped: management command はテナント横断で実行
        # テナント分離は ScrapeTarget.company で保持される
        if target_id:
            targets = ScrapeTarget.unscoped.filter(pk=target_id, is_active=True)
        else:
            targets = ScrapeTarget.unscoped.filter(is_active=True)

        if not targets.exists():
            self.stderr.write(self.style.WARNING("有効なスクレイピング対象がありません。"))
            return

        total_new = 0

        for target in targets:
            self.stdout.write(f"\n--- {target.name} ---")
            self.stdout.write(f"  キーワード: {target.keyword or '(なし)'}")
            self.stdout.write(f"  地域: {target.region or '(なし)'} {target.prefecture or ''}")
            self.stdout.write(f"  工事種別: {target.category or '(なし)'}")
            self.stdout.write(f"  過去{target.days_back}日以内")

            try:
                records = scrape_ippi(target, headless=headless)
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"  エラー: {e}"))
                continue

            self.stdout.write(f"  取得件数: {len(records)}")

            if dry_run:
                for rec in records:
                    self.stdout.write(f"    [DRY] {rec.get('title', '(無題)')}")
                continue

            new_count = 0
            for rec in records:
                title = rec.get("title", "").strip()
                if not title:
                    continue

                # source_url で重複チェック（同一テナント内）
                source_url = rec.get("source_url", "")
                if source_url and BidProject.unscoped.filter(
                    company=target.company, source_url=source_url
                ).exists():
                    continue

                # タイトル完全一致でも重複チェック
                if BidProject.unscoped.filter(
                    company=target.company, title=title
                ).exists():
                    continue

                BidProject.unscoped.create(
                    company=target.company,
                    created_by=target.created_by,
                    title=title,
                    client=rec.get("client", ""),
                    region=rec.get("region", "") or target.region or "",
                    category=rec.get("category", "") or target.category or "",
                    deadline=rec.get("deadline"),
                    budget=rec.get("budget", 0),
                    source_url=source_url,
                    status=BidProject.Status.NEW,
                )
                new_count += 1

            # ScrapeTarget のメタ情報を更新
            target.last_scraped_at = timezone.now()
            target.last_result_count = len(records)
            target.save(update_fields=["last_scraped_at", "last_result_count"])

            self.stdout.write(self.style.SUCCESS(f"  新規登録: {new_count} 件"))
            total_new += new_count

        self.stdout.write(self.style.SUCCESS(f"\n合計 {total_new} 件の新規案件を登録しました。"))
