"""戦略5（LLMマッチング）の精度を実測して比較する検証コマンド（ADR-0010 層B）。

ローカル推論と Claude API を、同じ入力・同じ正解データに対して走らせて精度を出す。

    # ローカルだけ（課金なし）
    python manage.py verify_item_matching --company 1 --providers local

    # Claude と比較する（課金される）
    python manage.py verify_item_matching --company 1 --providers local,claude

正解データは **人間が承認した ItemAlias**（status=approved）を使う。
自動マッチの結果ではなく人手の判断なので、評価の基準として信頼できる。
承認済みが1件も無い環境では何も測れないため、その旨を出して終了する。

--min-accuracy を下回ったら終了コード1を返すので、定期実行に載せられる。

ADR-0010 の一般則5「精度を測る手段が無いタスクは移さない」に対応する。
このコマンドで実測してから OLLAMA_CHAT_ENABLED=True にすること。
"""

import time
from unittest.mock import patch

from django.core.management.base import BaseCommand

from apps.estimation.models import EstimationItem, ItemAlias
from apps.estimation.services import matching
from apps.tenants.models import Company


class Command(BaseCommand):
    help = "品目名マッチング戦略5の精度を実測して比較する（ADR-0010 層B の回帰検証）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--company", type=int, required=True,
            help="対象テナントの Company ID",
        )
        parser.add_argument(
            "--providers", default="local",
            help="local,claude のカンマ区切り",
        )
        parser.add_argument(
            "--limit", type=int, default=50,
            help="評価に使う承認済みエイリアスの上限（既定 50）",
        )
        parser.add_argument(
            "--min-accuracy", type=float, default=0.0,
            help="ローカルがこれを下回ったら終了コード1（既定 0.0 = 判定しない）",
        )

    def handle(self, *args, **options):
        company = Company.objects.get(pk=options["company"])

        # 正解データ: 人間が承認したエイリアスのみ。
        gold = list(
            ItemAlias.unscoped.filter(  # unscoped: company を明示指定
                company=company,
                status=ItemAlias.Status.APPROVED,
                estimation_item__isnull=False,
            ).select_related("estimation_item")[:options["limit"]]
        )

        self.stdout.write(f"テナント: {company.name}")
        if not gold:
            self.stdout.write(self.style.WARNING(
                "承認済みの ItemAlias がありません。測れないので中止します。\n"
                "先に画面でマッチング結果を承認してください。"
            ))
            return

        # 候補は戦略4と同じ「上位k件」の形に揃える。
        # 実運用では埋め込みが絞った5件が渡るため、正解を含む小さな集合で評価する。
        pool = list(
            EstimationItem.unscoped.filter(  # unscoped: company を明示指定
                company=company, is_active=True,
            )[:matching.LOCAL_MAX_CANDIDATES]
        )
        pool_ids = {item.pk for item in pool}

        cases = []
        for alias in gold:
            candidates = list(pool)
            if alias.estimation_item_id not in pool_ids:
                # 正解が候補に無ければ評価にならないので差し込む。
                candidates = [alias.estimation_item, *pool[:-1]]
            cases.append((alias, candidates))

        self.stdout.write(
            f"正解  : {len(cases)} 件（status=approved の人手判断）"
        )
        self.stdout.write(
            f"候補  : 1件あたり最大 {matching.LOCAL_MAX_CANDIDATES} 件\n"
        )

        providers = [p.strip() for p in options["providers"].split(",") if p.strip()]
        failed = False

        for name in providers:
            hit, total, elapsed, errors = self._run(name, cases, company)
            accuracy = hit / total if total else 0.0
            line = (
                f"{name:8} 正答 {hit:4}/{total:<4}  "
                f"正答率 {accuracy:.3f}  {elapsed:7.1f}秒  "
                f"1件あたり {elapsed / total:.2f}秒"
            )
            if errors:
                line += f"  (応答なし {errors}件)"

            if name == "local" and options["min_accuracy"] > 0 and (
                accuracy < options["min_accuracy"]
            ):
                self.stderr.write(self.style.ERROR(line))
                self.stderr.write(self.style.ERROR(
                    f"  ローカルの正答率が閾値 {options['min_accuracy']} を下回りました。"
                ))
                failed = True
            else:
                self.stdout.write(self.style.SUCCESS(line))

        if failed:
            raise SystemExit(1)

    def _run(self, provider, cases, company):
        """1プロバイダで全ケースを走らせ、(正答数, 件数, 秒, 応答なし件数) を返す。

        _match_by_llm はローカル優先＋APIフォールバックなので、
        片方だけを測るには相手側を塞ぐ必要がある。
        """
        if provider == "local":
            # ローカルだけを見る。フォールバック先を塞いで混ざらないようにする。
            blocker = patch.object(matching, "_ask_claude", return_value=None)
        elif provider == "claude":
            blocker = patch.object(matching, "_ask_local", return_value=None)
        else:
            self.stderr.write(f"未知のプロバイダ: {provider}")
            return 0, len(cases), 0.0, len(cases)

        hit = errors = 0
        start = time.time()
        with blocker:
            for alias, candidates in cases:
                got, _confidence = matching._match_by_llm(
                    alias.raw_name, alias.normalized_name, company,
                    candidate_items=candidates,
                )
                if got is None:
                    errors += 1
                elif got.pk == alias.estimation_item_id:
                    hit += 1
        return hit, len(cases), time.time() - start, errors
