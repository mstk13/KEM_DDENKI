"""抽出精度を実測して比較する検証コマンド（ADR-0010）。

決定論的パーサ・ローカルLLM・Claude API の3者を、
同じ入力・同じ正解データに対して走らせて精度を出す。

    # CIと同じ（モデル不要・ネットワーク不要）
    python manage.py verify_llm_extraction

    # ローカルLLMも含めて比較
    python manage.py verify_llm_extraction --providers deterministic,local

    # Claude も含める（課金される）
    python manage.py verify_llm_extraction --providers deterministic,local,claude

正解データはフィクスチャの表から決定論的に組み立てる。
LLM を介さずに作れるので、評価の基準として信頼できる。

--min-f1 を下回ったら終了コード1を返すので、定期実行に載せられる。
"""

import json
import re
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.estimation.services import labor_table

DEFAULT_FIXTURE = (
    Path(settings.BASE_DIR) / "tests" / "fixtures" / "labor_rate_page03.json"
)

PREFECTURE_CELL = re.compile(r"^\s*(\d{2})\s+(\S+?[都道府県])\s*$")

LOCAL_SCHEMA = {
    "type": "object",
    "properties": {
        "rates": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "prefecture": {"type": "string"},
                "occupation_name": {"type": "string"},
                "unit_price": {"type": "integer"},
            },
            "required": ["prefecture", "occupation_name", "unit_price"],
        }},
    },
    "required": ["rates"],
}


def build_ground_truth(tables) -> set[tuple[str, str, int]]:
    """フィクスチャの表から正解の三つ組を作る。"""
    return {
        (row.prefecture, row.occupation_name, row.unit_price)
        for row in labor_table.parse_page(tables)
        if row.unit_price is not None
    }


def score(got: set, truth: set) -> tuple[float, float, float]:
    if not got:
        return 0.0, 0.0, 0.0
    hit = len(got & truth)
    precision = hit / len(got)
    recall = hit / len(truth) if truth else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )
    return precision, recall, f1


class Command(BaseCommand):
    help = "労務単価表の抽出精度を実測して比較する（ADR-0010 の回帰検証）"

    def add_arguments(self, parser):
        parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
        parser.add_argument(
            "--providers", default="deterministic",
            help="deterministic,local,claude のカンマ区切り",
        )
        parser.add_argument(
            "--min-f1", type=float, default=0.99,
            help="決定論的パーサがこれを下回ったら終了コード1（既定 0.99）",
        )

    def handle(self, *args, **options):
        fixture_path = Path(options["fixture"])
        providers = [p.strip() for p in options["providers"].split(",") if p.strip()]

        with fixture_path.open(encoding="utf-8") as f:
            fixture = json.load(f)

        truth = build_ground_truth(fixture["tables"])
        source = fixture.get("source", {})

        self.stdout.write(f"入力  : {source.get('title', fixture_path.name)}")
        self.stdout.write(
            f"        p.{source.get('page_number', '?')} / "
            f"data_scope={source.get('data_scope', '?')}"
        )
        self.stdout.write(f"正解  : {len(truth)} 件（表から決定論的に生成）\n")

        failed = False
        for name in providers:
            runner = getattr(self, f"_run_{name}", None)
            if runner is None:
                self.stderr.write(f"未知のプロバイダ: {name}")
                continue
            try:
                got, elapsed, note = runner(fixture)
            except Exception as e:  # noqa: BLE001 - 検証コマンドなので握って報告する
                self.stderr.write(self.style.ERROR(f"{name:14} 実行エラー: {e}"))
                failed = True
                continue

            precision, recall, f1 = score(got, truth)
            line = (
                f"{name:14} 抽出 {len(got):4}件  "
                f"適合率 {precision:.3f}  再現率 {recall:.3f}  F1 {f1:.3f}  "
                f"{elapsed:7.1f}秒"
            )
            if note:
                line += f"  ({note})"

            if name == "deterministic" and f1 < options["min_f1"]:
                self.stderr.write(self.style.ERROR(line))
                self.stderr.write(
                    self.style.ERROR(
                        f"  決定論的パーサの F1 が閾値 {options['min_f1']} を下回りました。"
                    )
                )
                failed = True
            else:
                self.stdout.write(self.style.SUCCESS(line))

        if failed:
            raise SystemExit(1)

    # --- 各プロバイダ ---

    def _run_deterministic(self, fixture):
        start = time.time()
        rows = labor_table.parse_page(fixture["tables"])
        got = {
            (r.prefecture, r.occupation_name, r.unit_price)
            for r in rows
            if r.unit_price is not None
        }
        return got, time.time() - start, "LLM未使用"

    def _run_local(self, fixture):
        from apps.estimation.services.labor_pdf import (
            STRUCTURE_SYSTEM_PROMPT,
            STRUCTURE_USER_PROMPT,
        )

        prompt = STRUCTURE_USER_PROMPT.format(
            page_number=fixture["source"].get("page_number", 0),
            raw_text=fixture.get("raw_text", "")[:3000],
            tables_json=json.dumps(
                fixture["tables"], ensure_ascii=False, indent=2
            )[:5000],
        )
        base = getattr(
            settings, "OLLAMA_BASE_URL", "http://host.docker.internal:11434"
        ).rstrip("/")
        body = json.dumps({
            "model": getattr(settings, "OLLAMA_CHAT_MODEL", "qwen3:8b"),
            "system": STRUCTURE_SYSTEM_PROMPT,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "format": LOCAL_SCHEMA,
            "keep_alive": "10m",
            "options": {"temperature": 0.7, "top_p": 0.8, "top_k": 20,
                        "num_ctx": 16384},
        }, ensure_ascii=False).encode("utf-8")

        request = urllib.request.Request(
            f"{base}/api/generate", data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        start = time.time()
        with urllib.request.urlopen(request, timeout=1800) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        elapsed = time.time() - start
        return self._to_triples(json.loads(data["response"])), elapsed, None

    def _run_claude(self, fixture):
        import anthropic

        from apps.estimation.services.labor_pdf import (
            STRUCTURE_MAX_TOKENS,
            STRUCTURE_SYSTEM_PROMPT,
            STRUCTURE_USER_PROMPT,
            _parse_json,
        )

        api_key = getattr(settings, "ANTHROPIC_API_KEY", None)
        if not api_key:
            import os
            api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY が未設定です")

        prompt = STRUCTURE_USER_PROMPT.format(
            page_number=fixture["source"].get("page_number", 0),
            raw_text=fixture.get("raw_text", "")[:3000],
            tables_json=json.dumps(
                fixture["tables"], ensure_ascii=False, indent=2
            )[:5000],
        )
        client = anthropic.Anthropic(api_key=api_key)
        start = time.time()
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=STRUCTURE_MAX_TOKENS,
            system=[{"type": "text", "text": STRUCTURE_SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.time() - start
        note = f"stop={resp.stop_reason} out={resp.usage.output_tokens}tok"
        try:
            return self._to_triples(_parse_json(resp.content[0].text)), elapsed, note
        except (ValueError, json.JSONDecodeError) as e:
            return set(), elapsed, f"{note} パース失敗({e})"

    @staticmethod
    def _to_triples(payload: dict) -> set[tuple[str, str, int]]:
        top = (payload.get("prefecture") or "").strip()
        triples = set()
        for rate in payload.get("rates", []):
            prefecture = (rate.get("prefecture") or top or "").strip()
            job = (rate.get("occupation_name") or "").strip()
            price = rate.get("unit_price")
            if prefecture and job and isinstance(price, int):
                triples.add((prefecture, job, price))
        return triples
