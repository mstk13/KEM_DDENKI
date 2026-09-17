"""同じ現場が別名で登録されていないかを、登録のあとで調べる（ADR-0084）。

入力の途中で気づかせる仕組み（ADR-0077）は文字の並びだけを見るので、

    鮎まつり   ／ 厚木鮎まつり      … 文字でも拾える（0.8）
    高橋住宅   ／ 高橋アパート      … 文字では拾えない（0.4）

後者のように「言い方が違うだけ」を拾うには、意味の近さが要る。
そこで3つの手がかりを足し合わせて候補を出す。

    1. 文字の似ている度合い   apps.sites.name_match.similarity
    2. 意味の近さ             ローカル埋め込み（bge-m3）のコサイン類似度
    3. まわりの一致           発注先・住所・工期の重なり

拾った2件は、ローカルの生成モデル（qwen3:8b）に「同じ現場か」を判定させる。
年度違い・その1／その2は別の工事なので「別の現場」と答えさせる。

**統合はしない。** 候補を出すところまでが機械の仕事で、
実際に寄せるかどうかは人が画面で決める（プロダクトオーナーの指示、2026-09-17）。
ローカルAIに繋がらないときは、文字と手がかりだけで候補を出す（止めない）。
"""

from __future__ import annotations

import logging

from apps.sites.name_match import normalize_site_name, similarity

logger = logging.getLogger(__name__)

# 文字の似ている度合いがこれ以上なら候補にする（ADR-0077 と同じ）
NAME_THRESHOLD = 0.72
# 意味の近さがこれ以上なら候補にする。
# 品目の実測（apps/estimation/services/embedding.py）で、
# 同じものの略記と別のものの差が小さいことが分かっているので、
# 埋め込み単独では決めず、候補に挙げて生成モデルと人に渡す。
VECTOR_THRESHOLD = 0.80
# 一度に生成モデルへ回す上限。画面から押したときに待たせすぎないため。
DEFAULT_JUDGE_LIMIT = 30

_SYSTEM_PROMPT = (
    "あなたは建設会社の現場台帳を整理する担当者です。"
    "2つの現場名が同じ工事を指しているかを判定します。"
    "表記のゆれ（全角半角・空白・略称・「住宅」と「アパート」のような言い換え）は同じ現場です。"
    "年度や期が違うもの（令和7年度と令和8年度）、"
    "「その1」「その2」「第1期」「第2期」のように分かれている工事、"
    "同じ建物でも工種が違う工事は別の現場です。"
    "迷うときは different にしてください。"
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "same": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["same", "reason"],
}


def _sites(company):
    from apps.sites.models import Site

    # unscoped: company を引数で受けて明示的に絞る。コマンドからも呼ぶため。
    return list(
        Site.unscoped.filter(company=company, merged_into__isnull=True)
        .select_related("customer")
        .order_by("pk")
    )


def _vector_scores(sites):
    """現場名の意味の近さ。ローカル埋め込みが使えなければ空。

    Returns:
        {(左のpk, 右のpk): 近さ}
    """
    from apps.estimation.services import embedding

    if not embedding.is_configured() or len(sites) < 2:
        return {}

    vectors = embedding.embed_texts([site.name for site in sites])
    if not vectors:
        return {}

    scores = {}
    for i, left in enumerate(sites):
        for j in range(i + 1, len(sites)):
            score = embedding.cosine_similarity(vectors[i], vectors[j])
            if score >= VECTOR_THRESHOLD:
                scores[(left.pk, sites[j].pk)] = score
    return scores


def _hints(left, right):
    """まわりの手がかりのうち、一致したもの。"""
    found = []
    if left.customer_id and left.customer_id == right.customer_id:
        found.append(f"発注先が同じ（{left.customer}）")
    if left.address and right.address:
        a, b = normalize_site_name(left.address), normalize_site_name(right.address)
        if a and b and (a == b or a.startswith(b) or b.startswith(a)):
            found.append("住所が同じ")
    if (
        left.start_date and left.end_date and right.start_date and right.end_date
        and left.start_date <= right.end_date and right.start_date <= left.end_date
    ):
        found.append("工期が重なっている")
    if left.manager_id and left.manager_id == right.manager_id:
        found.append("現場担当者が同じ")
    return found


def _order(left, right):
    """残すほうを先にする。日報などのデータが多いほう、同数なら古いほう。"""
    if _row_count(left) < _row_count(right):
        return right, left
    if _row_count(left) == _row_count(right) and left.pk > right.pk:
        return right, left
    return left, right


def _row_count(site):
    """その現場にぶら下がっている行の数。残すほうを決めるのに使う。"""
    if getattr(site, "_row_count", None) is None:
        total = 0
        for relation in site._meta.get_fields():
            if not (relation.auto_created and not relation.concrete):
                continue
            if relation.related_model is None or relation.one_to_one:
                continue
            total += relation.related_model._base_manager.filter(
                **{relation.field.name: site},
            ).count()
        site._row_count = total
    return site._row_count


def find_candidates(company, *, judge=True, judge_limit=DEFAULT_JUDGE_LIMIT):
    """候補を探して保存する。

    既に「別物」と決めた組は作り直さない。まだ確認していない組は、
    点数と判定を上書きする（名前を直したあとに調べ直せるように）。

    Returns:
        {"created": [SiteMergeCandidate], "updated": [...], "judged": 件数}
    """
    from apps.sites.models import SiteMergeCandidate

    sites = _sites(company)
    vectors = _vector_scores(sites)

    pairs = []
    for i, left in enumerate(sites):
        for right in sites[i + 1:]:
            name_score = similarity(left.name, right.name)
            vector_score = vectors.get((left.pk, right.pk))
            if name_score < NAME_THRESHOLD and vector_score is None:
                continue
            primary, duplicate = _order(left, right)
            pairs.append((primary, duplicate, name_score, vector_score))

    # 確からしい順に見る。生成モデルに回す数を絞るため
    pairs.sort(key=lambda row: -max(row[2], row[3] or 0))

    created, updated, judged = [], [], 0
    for primary, duplicate, name_score, vector_score in pairs:
        decided = SiteMergeCandidate.unscoped.filter(
            company=company,
        ).filter(
            primary__in=[primary, duplicate], duplicate__in=[primary, duplicate],
        ).exclude(state=SiteMergeCandidate.State.PENDING).exists()
        if decided:
            continue

        hints = _hints(primary, duplicate)
        verdict, reason = SiteMergeCandidate.Verdict.UNKNOWN, ""
        if judge and judged < judge_limit:
            verdict, reason = judge_pair(primary, duplicate, hints)
            judged += 1

        candidate, is_new = SiteMergeCandidate.unscoped.update_or_create(
            company=company, primary=primary, duplicate=duplicate,
            defaults={
                "name_score": name_score,
                "vector_score": vector_score,
                "hints": "／".join(hints),
                "verdict": verdict,
                "reason": reason,
                "state": SiteMergeCandidate.State.PENDING,
            },
        )
        (created if is_new else updated).append(candidate)
    return {"created": created, "updated": updated, "judged": judged}


def judge_pair(left, right, hints=None):
    """2件が同じ現場かを、ローカルの生成モデルに判定させる。

    Returns:
        (判定, 理由)。繋がらないときは ("unknown", "")
    """
    from apps.ai.services import local_llm
    from apps.sites.models import SiteMergeCandidate

    if not local_llm.is_configured():
        return SiteMergeCandidate.Verdict.UNKNOWN, ""

    prompt = "\n".join([
        "次の2つの現場が、同じ工事を指しているかを判定してください。",
        "",
        f"A: {left.name}",
        f"  発注先: {left.customer or '未設定'}",
        f"  住所: {left.address or '未設定'}",
        f"  工期: {left.start_date or '未設定'} 〜 {left.end_date or '未設定'}",
        "",
        f"B: {right.name}",
        f"  発注先: {right.customer or '未設定'}",
        f"  住所: {right.address or '未設定'}",
        f"  工期: {right.start_date or '未設定'} 〜 {right.end_date or '未設定'}",
        "",
        f"一致している手がかり: {'／'.join(hints) if hints else 'なし'}",
        "",
        "same には同じ現場なら true、別の現場なら false を入れてください。",
        "reason には理由を日本語で1文だけ書いてください。",
    ])

    result = local_llm.chat_json(prompt, _SCHEMA, system_prompt=_SYSTEM_PROMPT)
    if not result or not isinstance(result.get("parsed"), dict):
        return SiteMergeCandidate.Verdict.UNKNOWN, ""

    parsed = result["parsed"]
    verdict = (
        SiteMergeCandidate.Verdict.SAME if parsed.get("same")
        else SiteMergeCandidate.Verdict.DIFFERENT
    )
    return verdict, str(parsed.get("reason", ""))[:500]
