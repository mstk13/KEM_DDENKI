"""名寄せマッチングサービス。

マッチング戦略をカスケード実行し、ItemAlias を生成する。
戦略の優先順位:
  1. コード完全一致 (confidence=100)
  2. 正規化名完全一致 (confidence=90)
  3. 仕様属性一致 (confidence=70)
  4. 埋め込み類似度一致 (confidence=65〜85)   ← ADR-0010 層A
  5. LLM による候補提示 (confidence=30〜60)

1〜2 以外は必ず人間の承認を要求する。

戦略4は「候補を絞る」のが主目的で、確定判断は限定的にしか行わない。
実測で、同一品目の略記(0.768)と別種ケーブル(0.668)の類似度差が
0.10 しかないことを確認しているため、0.85 以上のみ自動確定とし、
0.65〜0.85 は上位k件を戦略5へ渡して LLM に選ばせる。
これにより LLM へ渡す候補が「先頭100件」から「類似上位k件」になり、
精度が上がると同時に入力トークンも減る。
"""

import json
import logging
from decimal import Decimal

from django.conf import settings

from apps.estimation.models import EstimationItem, ItemAlias
from apps.estimation.services import embedding as embedding_service
from apps.estimation.services.normalization import extract_spec, normalize

logger = logging.getLogger(__name__)

try:
    import anthropic

    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


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
    items = EstimationItem.unscoped.filter(  # unscoped: company を明示指定
        company=company, is_active=True,
    )
    for item in items:
        item_normalized = normalize(item.canonical_name)
        if item_normalized == normalized_name:
            return item, Decimal("90")
    return None, Decimal("0")


def _match_by_spec(normalized_name: str, company):
    """仕様 JSON の属性一致で検索。"""
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
        if item_spec.get("type") != spec.get("type"):
            continue
        if spec.get("size") and item_spec.get("size") != spec.get("size"):
            continue
        if spec.get("cores") and item_spec.get("cores") != spec.get("cores"):
            continue
        return item, Decimal("70")

    return None, Decimal("0")


# ===================================================================
# 戦略 4: 埋め込み類似度マッチング（ADR-0010 層A）
# ===================================================================

# 自動確定の上限。類似度が幾ら高くてもこれ以上の confidence は付けない。
# 90 以上にすると match_item() が status=REVIEWED にしてしまい、
# 人間のレビューを飛ばすため。類似度一致は必ずレビュー対象とする。
EMBEDDING_MAX_CONFIDENCE = 85


def _match_by_embedding(raw_name: str, normalized_name: str, company):
    """埋め込み類似度で照合する。

    Returns:
        (item, confidence, candidates)
        - item: 自動確定できた品目。閾値未満なら None
        - confidence: item がある場合のみ有効
        - candidates: LLM に渡す候補 EstimationItem のリスト（確定できた場合は空）
    """
    if not embedding_service.is_configured():
        return None, Decimal("0"), []

    query = normalized_name or raw_name
    query_vector = embedding_service.embed_text(query)
    if not query_vector:
        # Ollama に到達できない。従来どおり LLM へ落とす。
        return None, Decimal("0"), []

    items = EstimationItem.unscoped.filter(  # unscoped: company を明示指定
        company=company, is_active=True,
    ).select_related("embedding")

    pairs = [
        (item, item.embedding.vector)
        for item in items
        if hasattr(item, "embedding") and item.embedding.vector
    ]
    if not pairs:
        logger.info("埋め込み未生成のため類似度マッチングをスキップします")
        return None, Decimal("0"), []

    ranked = embedding_service.rank_by_similarity(query_vector, pairs, top_k=5)
    if not ranked:
        return None, Decimal("0"), []

    best_item, best_score = ranked[0]

    if best_score >= embedding_service.AUTO_CONFIRM_THRESHOLD:
        confidence = Decimal(
            str(min(round(best_score * 100), EMBEDDING_MAX_CONFIDENCE))
        )
        logger.info(
            "類似度マッチング確定: %s -> %s (score=%.3f)",
            raw_name, best_item.code, best_score,
        )
        return best_item, confidence, []

    # 中間帯。確定はせず、候補だけを LLM に渡す。
    logger.info(
        "類似度マッチング候補: %s -> %d件 (最高 score=%.3f)",
        raw_name, len(ranked), best_score,
    )
    return None, Decimal("0"), [item for item, _score in ranked]


# ===================================================================
# 戦略 5: LLM マッチング
# ===================================================================

LLM_SYSTEM_PROMPT = (
    "あなたは電気設備工事の積算品目の名寄せ（同一品目の突合）を行う専門家です。"
    "入力された品名に対して、候補リストから最も適合する品目を選んでください。"
    "必ずJSON形式で回答してください。"
)

LLM_USER_PROMPT = """\
以下の品名を、候補リストの中から最も適合する品目と照合してください。

## 照合対象の品名:
「{raw_name}」
（正規化後: {normalized_name}）

## 候補リスト:
{candidates_json}

以下のJSON形式で回答してください:

```json
{{
  "matches": [
    {{
      "candidate_code": "候補の品目コード",
      "confidence": 0.0-1.0の数値,
      "reason": "選択理由（日本語で簡潔に）"
    }}
  ]
}}
```

ルール:
- 上位3件まで返してください（該当なしなら空配列）
- confidence は 0.3〜0.6 の範囲で設定（確実でないため高くしない）
- 電材の表記ゆれを考慮してください（例: 3心=3C=3芯、sq=㎟=mm2）
- 明らかに異なる品目は含めないでください
"""


def _get_api_key():
    """ANTHROPIC_API_KEY を取得する。"""
    api_key = getattr(settings, "ANTHROPIC_API_KEY", None)
    if not api_key:
        import os
        api_key = os.environ.get("ANTHROPIC_API_KEY")
    return api_key


def _match_by_llm(
    raw_name: str,
    normalized_name: str,
    company,
    *,
    candidate_items: list | None = None,
):
    """Claude API で候補を提示する。上位1件を返す。

    candidate_items が渡された場合はそれを候補リストとして使う。
    戦略4（埋め込み）が絞り込んだ上位k件を渡す想定で、
    「先頭100件」を送るより精度が上がり、入力トークンも減る。
    渡されない場合は従来どおり先頭100件にフォールバックする。
    """
    if not HAS_ANTHROPIC:
        return None, Decimal("0")

    api_key = _get_api_key()
    if not api_key:
        return None, Decimal("0")

    if candidate_items:
        items = candidate_items
    else:
        # 候補リストを取得（最大100件）
        items = EstimationItem.unscoped.filter(  # unscoped: company を明示指定
            company=company, is_active=True,
        )[:100]

    if not items:
        return None, Decimal("0")

    candidates = [
        {
            "code": item.code,
            "name": item.canonical_name,
            "category": item.get_category_display(),
            "unit": item.unit,
            "spec": item.spec or {},
        }
        for item in items
    ]

    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1000,
            system=[{
                "type": "text",
                "text": LLM_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{
                "role": "user",
                "content": LLM_USER_PROMPT.format(
                    raw_name=raw_name,
                    normalized_name=normalized_name,
                    candidates_json=json.dumps(candidates, ensure_ascii=False, indent=2),
                ),
            }],
        )

        result_text = response.content[0].text
        logger.info(
            f"LLMマッチング: input={response.usage.input_tokens}, "
            f"output={response.usage.output_tokens}"
        )

        # JSONパース
        if "```json" in result_text:
            start = result_text.index("```json") + len("```json")
            end = result_text.index("```", start)
            result_text = result_text[start:end].strip()
        elif "```" in result_text:
            start = result_text.index("```") + len("```")
            end = result_text.index("```", start)
            result_text = result_text[start:end].strip()

        data = json.loads(result_text)
        matches = data.get("matches", [])

        if not matches:
            return None, Decimal("0")

        # 最も信頼度の高い候補
        best = max(matches, key=lambda m: m.get("confidence", 0))
        code = best.get("candidate_code", "")
        confidence = Decimal(str(min(best.get("confidence", 0.3), 0.6))) * 100

        try:
            item = EstimationItem.unscoped.get(  # unscoped: company を明示指定
                company=company, code=code, is_active=True,
            )
            return item, confidence
        except EstimationItem.DoesNotExist:
            return None, Decimal("0")

    except Exception as e:
        logger.warning(f"LLMマッチングエラー: {e}")
        return None, Decimal("0")


# ===================================================================
# メイン関数
# ===================================================================


def _run_cascade(raw_name: str, normalized_name: str, company, *, use_llm: bool):
    """戦略2〜5を順に試し、(item, confidence, matched_by) を返す。

    戦略1（コード完全一致）は source_key を必要とするため match_item 側で扱う。
    ネストを深くしないようここへ分離している。
    """
    # 戦略 2: 正規化名完全一致
    item, confidence = _match_by_normalized_name(normalized_name, company)
    if item:
        return item, confidence, ItemAlias.MatchMethod.NORMALIZED

    # 戦略 3: 仕様属性一致
    item, confidence = _match_by_spec(normalized_name, company)
    if item:
        return item, confidence, ItemAlias.MatchMethod.SPEC_MATCH

    # 戦略 4: 埋め込み類似度一致
    item, confidence, candidates = _match_by_embedding(
        raw_name, normalized_name, company,
    )
    if item:
        return item, confidence, ItemAlias.MatchMethod.EMBEDDING

    # 戦略 5: LLM マッチング（戦略4が絞った候補があればそれを渡す）
    if use_llm:
        item, confidence = _match_by_llm(
            raw_name, normalized_name, company, candidate_items=candidates or None,
        )
        if item:
            return item, confidence, ItemAlias.MatchMethod.LLM

    return None, Decimal("0"), ItemAlias.MatchMethod.MANUAL


def match_item(
    raw_name: str,
    source_type: str,
    source_key: str,
    company,
    *,
    use_llm: bool = False,
) -> ItemAlias:
    """マッチング戦略をカスケード実行し、ItemAlias を生成して返す。

    use_llm=True の場合、戦略4まで失敗したらLLMマッチングを試みる。
    埋め込み（戦略4）は Ollama に到達できなければ黙って飛ばされ、
    従来どおり戦略5へ落ちる。
    """
    normalized_name = normalize(raw_name)

    # 戦略 1: コード完全一致
    item, confidence = _match_by_exact_code(source_key, company)
    if item:
        matched_by = ItemAlias.MatchMethod.EXACT_CODE
    else:
        item, confidence, matched_by = _run_cascade(
            raw_name, normalized_name, company, use_llm=use_llm,
        )

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


def bulk_match(
    items: list[dict],
    company,
    *,
    use_llm: bool = False,
) -> list[ItemAlias]:
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
            use_llm=use_llm,
        )
        results.append(alias)
    return results
