"""名寄せマッチングサービス。

マッチング戦略をカスケード実行し、ItemAlias を生成する。
戦略の優先順位:
  1. コード完全一致 (confidence=100)
  2. 正規化名完全一致 (confidence=90)
  3. 仕様属性一致 (confidence=70)
  4. LLM による候補提示 (confidence=30〜60)

1〜2 以外は必ず人間の承認を要求する。
"""

import json
import logging
from decimal import Decimal

from django.conf import settings

from apps.estimation.models import EstimationItem, ItemAlias
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
# 戦略 4: LLM マッチング
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


def _match_by_llm(raw_name: str, normalized_name: str, company):
    """Claude API で候補を提示する。上位1件を返す。"""
    if not HAS_ANTHROPIC:
        return None, Decimal("0")

    api_key = _get_api_key()
    if not api_key:
        return None, Decimal("0")

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


def match_item(
    raw_name: str,
    source_type: str,
    source_key: str,
    company,
    *,
    use_llm: bool = False,
) -> ItemAlias:
    """マッチング戦略をカスケード実行し、ItemAlias を生成して返す。

    use_llm=True の場合、戦略3まで失敗したらLLMマッチングを試みる。
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
            elif use_llm:
                # 戦略 4: LLM マッチング
                item, confidence = _match_by_llm(
                    raw_name, normalized_name, company,
                )
                if item:
                    matched_by = ItemAlias.MatchMethod.LLM
                else:
                    matched_by = ItemAlias.MatchMethod.MANUAL
                    confidence = Decimal("0")
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
