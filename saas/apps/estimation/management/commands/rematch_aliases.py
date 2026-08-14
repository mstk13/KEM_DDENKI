"""既存の名寄せを再評価する。

マッチング手段が増えたとき（例: ADR-0010 で埋め込み照合を追加）、
それ以前に「手動・信頼度0」で記録された名寄せは放置すると
そのまま残り続ける。このコマンドで洗い直す。

    # 何が変わるか見るだけ
    python manage.py rematch_aliases --company 1 --dry-run

    # 未確認のものを再評価する
    python manage.py rematch_aliases --company 1

    # レビュー済みも含めて無条件に上書きする（人間の判断が消える）
    python manage.py rematch_aliases --company 1 --force

既定では未確認（pending）のものだけを対象にし、
レビュー済み・承認済み・却下済みには触れない。
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.estimation.models import ItemAlias
from apps.estimation.services.matching import FINALISED_STATUSES, match_item


class Command(BaseCommand):
    help = "既存の名寄せを現在のマッチング手段で再評価する"

    def add_arguments(self, parser):
        parser.add_argument(
            "--company", type=int, required=True,
            help="対象テナントの Company ID",
        )
        parser.add_argument(
            "--use-llm", action="store_true",
            help="戦略5（Claude API）も使う。課金される。",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="レビュー済みも含めて上書きする。人間の判断が消えるので注意。",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="変更せず、何が変わるかだけ表示する。",
        )
        parser.add_argument(
            "--limit", type=int, default=0,
            help="処理件数の上限（0で無制限）。",
        )

    def handle(self, *args, **options):
        company_id = options["company"]
        force = options["force"]
        dry_run = options["dry_run"]

        # unscoped: 管理コマンドはリクエスト文脈を持たないため company を明示指定する
        qs = ItemAlias.unscoped.filter(company_id=company_id)
        if not force:
            qs = qs.exclude(status__in=FINALISED_STATUSES)
        qs = qs.select_related("estimation_item", "company").order_by("id")

        if options["limit"]:
            qs = qs[: options["limit"]]

        aliases = list(qs)
        if not aliases:
            self.stdout.write(self.style.WARNING("対象の名寄せがありません。"))
            return

        scope = "全件（レビュー済み含む）" if force else "未確認のみ"
        mode = "確認のみ" if dry_run else "更新"
        self.stdout.write(f"対象 {len(aliases)} 件（{scope}） / {mode}")
        if force and not dry_run:
            self.stdout.write(self.style.WARNING(
                "--force 指定のため、レビュー済みの判断も上書きされます。"
            ))

        changed = unchanged = 0
        for alias in aliases:
            before = (
                alias.estimation_item_id, alias.matched_by, alias.confidence,
            )

            if dry_run:
                # 実際に更新せず、同じ判定を通して結果だけ見る。
                # transaction を張って必ず巻き戻す。
                try:
                    with transaction.atomic():
                        updated = match_item(
                            raw_name=alias.raw_name,
                            source_type=alias.source_type,
                            source_key=alias.source_key,
                            company=alias.company,
                            use_llm=options["use_llm"],
                            force=force,
                        )
                        after = (
                            updated.estimation_item_id, updated.matched_by,
                            updated.confidence,
                        )
                        raise _Rollback
                except _Rollback:
                    pass
            else:
                updated = match_item(
                    raw_name=alias.raw_name,
                    source_type=alias.source_type,
                    source_key=alias.source_key,
                    company=alias.company,
                    use_llm=options["use_llm"],
                    force=force,
                )
                after = (
                    updated.estimation_item_id, updated.matched_by,
                    updated.confidence,
                )

            if before == after:
                unchanged += 1
                continue

            changed += 1
            name = alias.raw_name[:34]
            self.stdout.write(
                f"  {name:<36} {before[1]}({before[2]}) -> {after[1]}({after[2]})"
            )

        summary = f"完了: 変更 {changed} 件 / 変更なし {unchanged} 件"
        if dry_run:
            summary += "（--dry-run のため保存していません）"
        self.stdout.write(self.style.SUCCESS(summary))


class _Rollback(Exception):
    """--dry-run で変更を巻き戻すためだけの内部例外。"""
