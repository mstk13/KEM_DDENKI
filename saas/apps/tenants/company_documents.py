"""自社書類のしまい方（ADR-0071）。

- 会社ごとに書類の種類の一覧を持つ。1件も無ければ既定の種類を入れる
- 種類ごとに、いちばん新しい書類と、それより前の版（入れ直したもの）を出す
- 受け付けるのは PDF（.pdf）と Excel（.xlsx・.xls）だけ（apps/core/documents.py の決まり）
- 登録には「中身を確認した」のチェックが要る。中を見ずに置いただけの書類を残さないため
"""

from pathlib import Path

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.tenants.models import CompanyDocument, CompanyDocumentType

# 最初に用意する書類の種類（プロダクトオーナー確認 2026-09-16）。
# (書類名, 更新がある) の組。更新がある書類は、更新日を入れると知らせが出る
DEFAULT_TYPES = (
    ("経営規模等評価結果通知書（経審）", True),
    ("総合評定値通知書", True),
    ("建設業許可証", True),
    ("入札参加資格の認定通知書", True),
    ("労災保険関係成立票", True),
    ("保険加入証明", True),
    ("登記事項証明書", False),
    ("印鑑証明書", False),
    ("納税証明書", False),
    ("決算書（財務諸表）", False),
    ("会社概要・定款", False),
)


def ensure_default_types(company) -> None:
    """会社に書類の種類が1件も無ければ、既定の種類を入れる。

    使わなくした（is_active=False）種類も「ある」に数える。全部外した会社に戻さないため。
    定時実行や画面から会社を明示して呼ぶので unscoped で絞る。
    """
    if CompanyDocumentType.unscoped.filter(company=company).exists():
        return
    order = 0
    for name, has_renewal in DEFAULT_TYPES:
        order += 10
        CompanyDocumentType.unscoped.get_or_create(
            company=company,
            name=name,
            defaults={"has_renewal": has_renewal, "display_order": order},
        )


def normalize_name(name: str) -> str:
    """書類名の前後の空白を落とし、続いた空白を1つにする。"""
    return " ".join((name or "").split())


def document_groups(company) -> list[dict]:
    """種類ごとに「いちばん新しい書類」と「前の版」をまとめて返す。

    更新がある種類を先に、その中は並び順。種類を消した書類は最後に「その他」で出す。
    """
    ensure_default_types(company)
    types = list(
        CompanyDocumentType.unscoped.filter(company=company, is_active=True)
        .order_by("-has_renewal", "display_order", "pk")
    )
    documents = list(
        CompanyDocument.unscoped.filter(company=company)
        .select_related("doc_type", "confirmed_by")
        .order_by("-issued_on", "-created_at", "-pk")
    )
    by_type: dict[int | None, list] = {}
    for document in documents:
        by_type.setdefault(document.doc_type_id, []).append(document)

    groups = []
    for doc_type in types:
        rows = by_type.pop(doc_type.pk, [])
        groups.append({
            "type": doc_type,
            "latest": rows[0] if rows else None,
            "older": rows[1:],
            "count": len(rows),
        })
    # 種類を使わなくした・消したあとの書類も見えるようにする
    leftovers = [row for rows in by_type.values() for row in rows]
    if leftovers:
        groups.append({
            "type": None, "latest": leftovers[0], "older": leftovers[1:],
            "count": len(leftovers),
        })
    return groups


def renewal_documents(company) -> list[CompanyDocument]:
    """更新日が入っている、種類ごとにいちばん新しい書類。近い順。"""
    latest = []
    for group in document_groups(company):
        document = group["latest"]
        if document is not None and document.renewal_on:
            latest.append(document)
    return sorted(latest, key=lambda d: d.renewal_on)


def save_company_document(
    company, *, doc_type, name, uploaded, kind, user=None, **values,
) -> CompanyDocument:
    """ファイルを1件しまう。同じ種類の前の書類は古い版として残す。"""
    with transaction.atomic():
        return CompanyDocument.unscoped.create(
            company=company,
            doc_type=doc_type,
            name=normalize_name(name),
            file=uploaded,
            kind=kind,
            original_filename=Path(uploaded.name).name[:255],
            size=uploaded.size or 0,
            created_by=user,
            **values,
        )


def mark_confirmed(document, user) -> CompanyDocument:
    """「中身を確認した」を記録する。誰がいつ確認したかを残す。"""
    document.confirmed = True
    document.confirmed_by = user
    document.confirmed_at = timezone.now()
    document.save(update_fields=["confirmed", "confirmed_by", "confirmed_at", "updated_at"])
    return document


def next_display_order(company) -> int:
    last = CompanyDocumentType.unscoped.filter(company=company).aggregate(
        last=Max("display_order"),
    )["last"]
    return (last or 0) + 10
