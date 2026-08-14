"""積算品目の埋め込みベクトルを生成・更新する。

ADR-0010 層A。品目マスタを投入・更新したあとに実行する。

    python manage.py build_item_embeddings --company 1
    python manage.py build_item_embeddings --company 1 --rebuild

実測で埋め込み1件あたり約220msかかるため、必ず一括APIでまとめて送る
（--batch-size 件ずつ）。1件ずつ呼ぶと件数分そのまま遅くなる。
"""

import hashlib

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.estimation.models import EstimationItem, ItemEmbedding
from apps.estimation.services import embedding as embedding_service


def build_source_text(item: EstimationItem) -> str:
    """ベクトル化する文字列を組み立てる。

    正規名称だけでなく単位と仕様を足す。「VVF 1.6-2C」のような
    短い品名は情報量が乏しく、単体では別品目と区別しにくいため。
    """
    parts = [item.canonical_name]
    if item.unit:
        parts.append(item.unit)
    spec = item.spec or {}
    for key in ("type", "size", "cores", "voltage"):
        value = spec.get(key)
        if value:
            parts.append(str(value))
    return " ".join(parts)


class Command(BaseCommand):
    help = "積算品目の埋め込みベクトルを生成・更新する（ADR-0010 層A）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--company", type=int, required=True,
            help="対象テナントの Company ID",
        )
        parser.add_argument(
            "--batch-size", type=int, default=64,
            help="1回のAPI呼び出しで送る件数（既定 64）",
        )
        parser.add_argument(
            "--rebuild", action="store_true",
            help="内容が変わっていないものも含めて全件を作り直す",
        )

    def handle(self, *args, **options):
        if not embedding_service.is_configured():
            raise CommandError(
                "埋め込み機能が無効です。OLLAMA_EMBED_ENABLED と "
                "OLLAMA_BASE_URL を確認してください。"
            )

        company_id = options["company"]
        batch_size = options["batch_size"]
        rebuild = options["rebuild"]
        model_tag = embedding_service._model()

        # unscoped: 管理コマンドはリクエスト文脈を持たないため company を明示指定する
        items = list(
            EstimationItem.unscoped.filter(
                company_id=company_id, is_active=True,
            ).select_related("embedding")
        )
        if not items:
            self.stdout.write(self.style.WARNING("対象品目がありません。"))
            return

        targets = []
        for item in items:
            source_text = build_source_text(item)
            existing = getattr(item, "embedding", None)
            if not rebuild and existing and not existing.is_stale(source_text, model_tag):
                continue
            targets.append((item, source_text))

        if not targets:
            self.stdout.write(
                self.style.SUCCESS(f"更新不要（全 {len(items)} 件が最新）。")
            )
            return

        self.stdout.write(
            f"対象 {len(targets)} / {len(items)} 件を {model_tag} で生成します。"
        )

        created = updated = failed = 0
        for start in range(0, len(targets), batch_size):
            chunk = targets[start:start + batch_size]
            vectors = embedding_service.embed_texts([text for _item, text in chunk])
            if vectors is None:
                failed += len(chunk)
                self.stderr.write(
                    self.style.ERROR(
                        f"  {start + 1}〜{start + len(chunk)} 件目の取得に失敗しました。"
                    )
                )
                continue

            with transaction.atomic():
                for (item, source_text), vector in zip(chunk, vectors, strict=True):
                    digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
                    # unscoped: 管理コマンドのため company を明示指定する
                    _obj, was_created = ItemEmbedding.unscoped.update_or_create(
                        estimation_item=item,
                        defaults={
                            "company": item.company,
                            "vector": vector,
                            "model_tag": model_tag,
                            "dim": len(vector),
                            "source_text": source_text[:500],
                            "source_hash": digest,
                        },
                    )
                    if was_created:
                        created += 1
                    else:
                        updated += 1

            self.stdout.write(f"  {start + len(chunk)} / {len(targets)} 件")

        summary = f"完了: 新規 {created} 件 / 更新 {updated} 件"
        if failed:
            self.stderr.write(self.style.ERROR(f"{summary} / 失敗 {failed} 件"))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
