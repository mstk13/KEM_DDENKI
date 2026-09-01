"""入札案件と自社の入札参加資格の照合。

資格マスタ（Qualification）は発注機関ごとに表記がばらつく。実データ（96件）で
確認したゆれを吸収した上で突き合わせる。

- 発注機関: 資格側は「国土交通省(関東地方整備局)」、案件側は
  「国土交通省関東地方整備局」。防衛省のように案件側だけが
  「防衛省北関東防衛局」と地方局まで持つこともある
- 業種区分: 「電気設備」「電気工事」「電気」が同じものを指す。
  一方「電気通信」は別物なので混ぜてはいけない
- 等級:     半角/全角の A〜D、空欄、「○」が混在する

i-ppi は案件の等級要件を持たない（公告PDFにしか書かれていない）ので、
第一の判定は「その発注機関にその業種で登録があるか」。等級要件が
分かっている案件だけ、追加で等級を比較する。
"""
import datetime
import re

from apps.bids.models import Qualification

# 案件の工事種別 → 資格マスタの業種区分の候補。
# 案件側の文字列に左のいずれかが含まれたら、右の語を持つ資格を探す。
# 上から順に判定するので、より限定的なものを先に置くこと
# （「電気通信」を「電気」より先に見ないと誤って電気工事の資格に当たる）。
CATEGORY_ALIASES = [
    (("受変電",), ("受変電", "電気設備", "電気工事", "電気")),
    (("電気通信", "通信設備", "通信"), ("電気通信", "通信設備")),
    (("電気",), ("電気設備", "電気工事", "電気")),
    (("機械設備", "暖冷房", "衛生設備", "空調"), ("機械設備", "機械", "管")),
    (("維持修繕", "維持"), ("維持修繕", "維持")),
    (("橋梁補修",), ("橋梁補修",)),
    (("建築",), ("建築",)),
    (("造園",), ("造園",)),
    (("塗装",), ("塗装",)),
]

# 全省庁統一資格は物品・役務の資格で、工事の発注機関名ではない。
# 発注機関の突き合わせから除く。
UNIFIED_QUALIFICATION_ISSUER = "全省庁統一資格"

GRADE_ORDER = {"A": 4, "B": 3, "C": 2, "D": 1}


def normalize_issuer(name: str) -> str:
    """発注機関名を突き合わせ用に正規化する。

    括弧・空白・中黒を落とすと、資格側「国土交通省(関東地方整備局)」と
    案件側「国土交通省関東地方整備局」が同じ文字列になる。
    """
    return re.sub(r"[（）()・\s　]", "", name or "")


def normalize_grade(grade: str) -> str:
    """等級を半角 A〜D に揃える。等級として読めなければ空文字。

    資格マスタには全角「Ｄ」や、等級の代わりに「○」が入っている行がある。
    """
    text = (grade or "").strip().translate(str.maketrans("ＡＢＣＤ", "ABCD")).upper()
    return text if text in GRADE_ORDER else ""


def category_candidates(category: str) -> tuple[str, ...]:
    """案件の工事種別に対応する資格の業種区分の候補を返す。"""
    for needles, candidates in CATEGORY_ALIASES:
        if any(n in category for n in needles):
            return candidates
    return ()


def normalize_category(category: str) -> str:
    """業種区分を突き合わせ用に正規化する。

    資格側は「電気工事」「電気設備」「電気」と揺れるので末尾の「工事」を落とす。
    部分一致では判定できない。「電気」は「電気通信」に含まれてしまうため、
    電気通信の資格で電気設備工事に参加できると誤判定する。
    """
    text = (category or "").strip()
    if len(text) > 2 and text.endswith("工事"):
        text = text[:-2]
    return text


def _category_matches(qual_category: str, candidates: tuple[str, ...]) -> bool:
    """資格の業種区分が候補のいずれかと一致するか。"""
    target = normalize_category(qual_category)
    return any(target == normalize_category(c) for c in candidates)


def _issuer_match_score(bid_issuer: str, qual_issuer: str) -> int:
    """発注機関の一致度。0 は不一致。大きいほど限定的な一致。

    地方局まで一致した資格を、本省だけの資格より優先したいので、
    一致した資格側の名前の長さを加点する。
    """
    bid = normalize_issuer(bid_issuer)
    qual = normalize_issuer(qual_issuer)
    if not bid or not qual:
        return 0
    if bid == qual:
        return 1000 + len(qual)
    # 案件「防衛省北関東防衛局」に対する資格「防衛省」
    if bid.startswith(qual):
        return 500 + len(qual)
    # 案件「厚生労働省」に対する資格「厚生労働省(東北厚生局)」
    if qual.startswith(bid):
        return 100 + len(bid)
    return 0


def check_project(project, qualifications, today=None):
    """1案件の入札参加資格を判定する。

    Args:
        project: BidProject
        qualifications: Qualification のリスト（自社分）
        today: 有効期限の判定日。省略時は本日

    Returns:
        dict: eligible / reason / matched / expired / issuer_known
            eligible True  … 登録があり有効期限内（等級要件があれば充足）
            eligible False … 登録が無い・期限切れ・等級不足
            eligible None  … 判定材料が無い（発注機関が資格マスタに無い等）
    """
    today = today or datetime.date.today()
    result = {
        "eligible": None,
        "reason": "",
        "matched": None,
        "expired": [],
        "issuer_known": False,
        "checked": [],  # 実際に突き合わせた要件（画面に根拠として出す）
    }

    bid_issuer = project.client or ""
    if not bid_issuer:
        result["reason"] = "発注機関が未入力のため判定できません。"
        return result

    # 1. 発注機関で絞る
    by_issuer = []
    for qual in qualifications:
        if qual.issuer == UNIFIED_QUALIFICATION_ISSUER:
            continue
        score = _issuer_match_score(bid_issuer, qual.issuer)
        if score:
            by_issuer.append((score, qual))
    if not by_issuer:
        # 資格マスタは国の機関のみで、地方自治体は登録されていない。
        # 登録が無いことを「資格なし」とは扱わない。案件は取り込んだうえで
        # 要確認（eligible=None）にし、公告で確かめてもらう。
        result["reason"] = (
            f"「{bid_issuer}」の入札参加資格は登録されていません。"
            "資格要件が無いものとして取り込んでいます。"
            "参加できるかは公告の参加資格の記載で確認してください。"
        )
        return result

    result["issuer_known"] = True

    # 2. 工事種別で絞る
    category = project.category or ""
    candidates = category_candidates(category)
    if not candidates:
        result["reason"] = (
            f"工事種別「{category or '未設定'}」に対応する業種区分が判断できません。"
            "公告で確認してください。"
        )
        return result

    matched = [
        (score, qual) for score, qual in by_issuer
        if _category_matches(qual.category, candidates)
    ]
    if not matched:
        result["eligible"] = False
        result["reason"] = (
            f"「{bid_issuer}」には登録がありますが、"
            f"{category} に対応する業種区分（{'／'.join(candidates)}）の資格がありません。"
        )
        return result

    # 3. 有効期限。限定的な一致・等級が高い順に見る
    matched.sort(
        key=lambda pair: (pair[0], GRADE_ORDER.get(normalize_grade(pair[1].grade), 0)),
        reverse=True,
    )
    valid = [
        (score, qual) for score, qual in matched
        if qual.valid_until is None or qual.valid_until >= today
    ]
    result["expired"] = [
        qual for _, qual in matched
        if qual.valid_until is not None and qual.valid_until < today
    ]
    if not valid:
        newest = max(result["expired"], key=lambda q: q.valid_until)
        result["eligible"] = False
        result["reason"] = (
            f"{newest.issuer}／{newest.category} の資格は "
            f"{newest.valid_until} に有効期限が切れています。"
        )
        return result

    best = valid[0][1]
    result["matched"] = best
    detail = _describe(best)
    ours = normalize_grade(best.grade)

    # 4. 公告が等級を列挙している場合（国土交通省の「Ｂ等級又はＣ等級」）。
    #    下限ではないので大小比較してはいけない。集合に入っているかを見る。
    listed = "".join(sorted({
        g for g in (project.required_grades or "").upper() if g in GRADE_ORDER
    }))
    if listed and ours:
        label = "・".join(f"{g}等級" for g in listed)
        if ours not in listed:
            result["eligible"] = False
            result["reason"] = (
                f"{label}の認定が必要ですが、自社は {ours} 等級です（{detail}）。"
            )
            return result
        result["checked"].append(f"{label} → 自社 {ours} 等級")

    # 5. 等級の下限が書かれている場合
    floor = normalize_grade(project.required_grade)
    if floor and ours:
        if GRADE_ORDER[ours] < GRADE_ORDER[floor]:
            result["eligible"] = False
            result["reason"] = (
                f"{floor}等級以上が必要ですが、自社は {ours} 等級です（{detail}）。"
            )
            return result
        result["checked"].append(f"{floor}等級以上 → 自社 {ours} 等級")

    # 6. 点数の下限が書かれている場合（防衛省の総合審査数値・経営事項評価数値）
    if project.required_score:
        our_score = max(
            [s for s in (best.total_score, best.keisin_score) if s], default=None,
        )
        if our_score is None:
            result["checked"].append(
                f"{project.required_score}点以上 → 自社の点数が未登録のため未確認"
            )
        elif our_score < project.required_score:
            result["eligible"] = False
            result["reason"] = (
                f"{project.required_score}点以上が必要ですが、"
                f"自社は {our_score} 点です（{detail}）。"
            )
            return result
        else:
            result["checked"].append(
                f"{project.required_score}点以上 → 自社 {our_score} 点"
            )

    result["eligible"] = True
    if result["checked"]:
        result["reason"] = (
            "公告の要件を満たします（" + "／".join(result["checked"]) + f"、{detail}）。"
        )
    else:
        result["reason"] = (
            f"登録があります（{detail}）。"
            "等級・点数の要件は公告本文で確認してください。"
        )
    return result


def _describe(qual) -> str:
    """判定の根拠にした資格を1行で表す。"""
    parts = [f"{qual.issuer}／{qual.category}"]
    if qual.grade:
        parts.append(f"{qual.grade}等級")
    if qual.total_score:
        parts.append(f"総合点{qual.total_score}")
    elif qual.keisin_score:
        parts.append(f"経審{qual.keisin_score}")
    if qual.valid_until:
        parts.append(f"期限{qual.valid_until}")
    return " / ".join(parts)


def check_qualifications_for_projects(projects, company, today=None):
    """複数案件の受注可否を一括判定する。

    Returns:
        dict: {project.pk: check_project() の戻り値}
    """
    # unscoped: company を明示指定（N+1 を避けて一括で読む）
    qualifications = list(Qualification.unscoped.filter(company=company))
    return {p.pk: check_project(p, qualifications, today=today) for p in projects}
