"""戦略5（LLMマッチング）の精度を実測して比較する検証コマンド（ADR-0010 層B）。

ローカル推論と Claude API を、同じ入力・同じ正解データに対して走らせて精度を出す。

    # 承認済み ItemAlias を正解にする（実データがある環境）
    python manage.py verify_item_matching --company 1 --providers local

    # ゴールデンフィクスチャで測る（実データが無くても回る）
    python manage.py verify_item_matching --company 1 \
        --fixture tests/fixtures/item_matching_pairs.json

    # Claude と比較する（課金される）
    python manage.py verify_item_matching --company 1 --providers local,claude

正解データは既定では **人間が承認した ItemAlias**（status=approved）を使う。
自動マッチの結果ではなく人手の判断なので、評価の基準として信頼できる。

承認済みが1件も無い環境では --fixture でゴールデンセットを渡す。
フィクスチャの品目は評価のあいだだけ作られ、**必ずロールバックされる**ので
既存データを汚さない。

--min-accuracy を下回ったら終了コード1を返すので、定期実行に載せられる。

ADR-0010 の一般則5「精度を測る手段が無いタスクは移さない」に対応する。
このコマンドで実測してから OLLAMA_CHAT_ENABLED=True にすること。
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.estimation.models import EstimationItem, ItemAlias
from apps.estimation.services import matching
from apps.estimation.services.normalization import normalize
from apps.tenants.models import Company


@dataclass
class _Case:
    """フィクスチャの1件。ItemAlias と同じ属性名にして評価ループを共通化する。"""

    raw_name: str
    normalized_name: str
    estimation_item_id: int
    kind: str = ""


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
            "--fixture",
            help="ゴールデンフィクスチャのパス。指定すると承認済みエイリアスの"
                 "代わりにこれを正解データにする（品目は評価後ロールバックされる）",
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
        providers = [p.strip() for p in options["providers"].split(",") if p.strip()]

        if options["fixture"]:
            self._handle_fixture(company, providers, options)
            return

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

        self._report(providers, cases, company, options)

    def _handle_fixture(self, company, providers, options):
        """ゴールデンフィクスチャで測る。品目は評価後にロールバックする。"""
        fixture = json.loads(
            Path(options["fixture"]).read_text(encoding="utf-8")
        )
        source = fixture.get("source", {})

        self.stdout.write(f"テナント: {company.name}")
        self.stdout.write(f"入力  : {source.get('title', options['fixture'])}")
        self.stdout.write(
            f"正解  : {len(fixture['cases'])} 件"
            f"（候補プール {len(fixture['pool'])} 件から選ばせる）"
        )
        self.stdout.write(
            "        実運用では戦略4が候補を5件に絞るため、"
            "この条件は本番より難しい\n"
        )

        with transaction.atomic():
            items = {
                entry["code"]: EstimationItem.unscoped.create(  # unscoped: company を明示
                    company=company,
                    code=entry["code"],
                    canonical_name=entry["name"],
                    unit=entry.get("unit", ""),
                )
                for entry in fixture["pool"]
            }
            pool = list(items.values())
            cases = [
                (
                    _Case(
                        raw_name=case["raw_name"],
                        # 本番と同じ正規化を通す。前処理まで含めて測らないと
                        # モデルの成績と前処理の成績を切り分けられない。
                        normalized_name=normalize(case["raw_name"]),
                        estimation_item_id=items[case["expected"]].pk,
                        kind=case.get("kind", ""),
                    ),
                    pool,
                )
                for case in fixture["cases"]
            ]
            try:
                self._report(providers, cases, company, options)
            finally:
                # 評価用の品目は残さない。
                transaction.set_rollback(True)

    def _report(self, providers, cases, company, options):
        failed = False

        for name in providers:
            hit, total, elapsed, errors, misses = self._run(name, cases, company)
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

            for raw_name, kind in misses:
                self.stdout.write(f"    外した: 「{raw_name}」 ({kind})")

        if failed:
            raise SystemExit(1)

    def _run(self, provider, cases, company):
        """1プロバイダで全ケースを走らせ、成績を返す。

        Returns:
            (正答数, 件数, 秒, 応答なし件数, 外したケースの一覧)

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
            return 0, len(cases), 0.0, len(cases), []

        hit = errors = 0
        misses = []
        start = time.time()
        with blocker:
            for alias, candidates in cases:
                got, _confidence = matching._match_by_llm(
                    alias.raw_name, alias.normalized_name, company,
                    candidate_items=candidates,
                )
                if got is None:
                    errors += 1
                    misses.append((alias.raw_name, "応答なし"))
                elif got.pk == alias.estimation_item_id:
                    hit += 1
                else:
                    misses.append((
                        alias.raw_name,
                        f"{getattr(alias, 'kind', '')} → {got.code}".strip(),
                    ))
        return hit, len(cases), time.time() - start, errors, misses
