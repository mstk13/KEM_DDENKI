"""名寄せマッチングサービス。

マッチング戦略をカスケード実行し、ItemAlias を生成する。
戦略の優先順位:
  1. コード完全一致 (confidence=100)
  2. 正規化名完全一致 (confidence=90)
  3. 仕様属性一致 (confidence=70)
  4. (Phase 2) LLM による候補提示

1〜2 以外は必ず人間の承認を要求する。
"""

from decimal import Decimal

from apps.estimation.models import EstimationItem, ItemAlias
from apps.estimation.services.normalization import extract_spec, normalize


def _match_by_exact_code(source_key: str, company):
    """source_key でコード完全一致を試みる。"""
    if not source_key:
        return None, Decimal("0")
    try:
        item = EstimationItem.unscoped.get(  # unscoped: company を明示指定
            company=company, code=source_key, is_active=True,
        )
        return item, Decimal("100")
    except EstimationItem.DoesNotExist:
        return None, Decimal("0")


def _match_by_normalized_name(normalized_name: str, company):
    """正規化後の名称で既存品目の canonical_name を検索。"""
    if not normalized_name:
        return None, Decimal("0")
    # canonical_name を正規化して比較
    items = EstimationItem.unscoped.filter(  # unscoped: company を明示指定
        company=company, is_active=True,
    )
    for item in items:
        item_normalized = normalize(item.canonical_name)
        if item_normalized == normalized_name:
            return item, Decimal("90")
    return None, Decimal("0")


def _match_by_spec(normalized_name: str, company):
    """仕様 JSON の属性一致で検索。

    type + size（ケーブルの場合は cores も）が一致すれば候補とする。
    """
    spec = extract_spec(normalized_name)
    if not spec.get("type"):
        return None, Decimal("0")

    items = EstimationItem.unscoped.filter(  # unscoped: company を明示指定
        company=company, is_active=True,
    )

    for item in items:
        if not item.spec:
            continue
        item_spec = item.spec
        # type が一致することが最低条件
        if item_spec.get("type") != spec.get("type"):
            continue
        # size が一致
        if spec.get("size") and item_spec.get("size") != spec.get("size"):
            continue
        # cores が一致（指定がある場合）
        if spec.get("cores") and item_spec.get("cores") != spec.get("cores"):
            continue
        return item, Decimal("70")

    return None, Decimal("0")


def match_item(
    raw_name: str,
    source_type: str,
    source_key: str,
    company,
) -> ItemAlias:
    """マッチング戦略をカスケード実行し、ItemAlias を生成して返す。

    全て失敗した場合は status=PENDING, estimation_item=None で作成。
    """
    normalized_name = normalize(raw_name)

    # 戦略 1: コード完全一致
    item, confidence = _match_by_exact_code(source_key, company)
    if item:
        matched_by = ItemAlias.MatchMethod.EXACT_CODE
    else:
        # 戦略 2: 正規化名完全一致
        item, confidence = _match_by_normalized_name(normalized_name, company)
        if item:
            matched_by = ItemAlias.MatchMethod.NORMALIZED
        else:
            # 戦略 3: 仕様属性一致
            item, confidence = _match_by_spec(normalized_name, company)
            if item:
                matched_by = ItemAlias.MatchMethod.SPEC_MATCH
            else:
                matched_by = ItemAlias.MatchMethod.MANUAL
                confidence = Decimal("0")

    # 高信頼度（コード一致・正規化一致）は reviewed、それ以外は pending
    if confidence >= Decimal("90"):
        status = ItemAlias.Status.REVIEWED
    else:
        status = ItemAlias.Status.PENDING

    alias, _created = ItemAlias.unscoped.get_or_create(  # unscoped: company を明示指定
        company=company,
        source_type=source_type,
        source_key=source_key or "",
        raw_name=raw_name,
        defaults={
            "estimation_item": item,
            "normalized_name": normalized_name,
            "confidence": confidence,
            "matched_by": matched_by,
            "status": status,
        },
    )
    return alias


def bulk_match(items: list[dict], company) -> list[ItemAlias]:
    """一括マッチング。

    items: [{"raw_name": str, "source_type": str, "source_key": str}, ...]
    """
    results = []
    for entry in items:
        alias = match_item(
            raw_name=entry["raw_name"],
            source_type=entry.get("source_type", ItemAlias.SourceType.ORDERER_BOQ),
            source_key=entry.get("source_key", ""),
            company=company,
        )
        results.append(alias)
    return results
