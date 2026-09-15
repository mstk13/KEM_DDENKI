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

from apps.bids.announcement import extract_license_requirement
from apps.bids.models import ConstructionLicense, Qualification

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

# 案件の工事種別 → 建設業許可の業種（ADR-0065）。
# 公告が「当該工事に対応する建設業種」としか書かないときに、どの許可と照らすかを決める。
# 上から順に見る（「電気通信」を「電気」より先に見ないと電気工事業の許可に当たる）。
TRADE_ALIASES = [
    (("電気通信", "通信"), "電気通信工事業"),
    (("受変電", "電気"), "電気工事業"),
    (("管工事", "機械設備", "空調", "衛生設備", "暖冷房"), "管工事業"),
    (("建築",), "建築工事業"),
    (("土木",), "土木工事業"),
    (("塗装",), "塗装工事業"),
    (("造園",), "造園工事業"),
    (("消防",), "消防施設工事業"),
]

# 知事許可の許可行政庁から都道府県を取る。知事許可は1つの都道府県の中だけに営業所がある
_GOVERNOR_PREFECTURE = re.compile(r"(北海道|東京都|京都府|大阪府|[^\s]{2,3}県)知事")


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


def check_project(project, qualifications, today=None, licenses=None):
    """1案件の入札参加資格を判定する。

    満たさない要件が見つかっても止めず、確かめられる要件はすべて確かめて、
    不足をすべて理由に並べる（ADR-0066）。資格そのもの（発注機関・業種）が無いときは、
    等級・点数を比べる相手が無いのでそこまでにする。

    Args:
        project: BidProject
        qualifications: Qualification のリスト（自社分）
        today: 有効期限の判定日。省略時は本日
        licenses: ConstructionLicense のリスト（自社分）。公告が建設業許可や
            営業所の所在地を求めているときだけ照らす（ADR-0065）

    Returns:
        dict: eligible / reason / reason_lines / shortfalls / matched / expired / issuer_known
            eligible True  … 登録があり有効期限内（等級要件があれば充足）
            eligible False … 満たさない要件が1つ以上ある（shortfalls にすべて入る）
            eligible None  … 判定材料が無い（発注機関が資格マスタに無い等）
    """
    today = today or datetime.date.today()
    result = {
        "eligible": None,
        # 理由の全文（1行に1つ）。見送り案件の記録や一覧のツールチップに使う
        "reason": "",
        # 画面に1行ずつ出す理由
        "reason_lines": [],
        # 満たさない要件すべて。[{"failed_on": 条件, "reason": 理由}]。参加要件の該当項目に添える。
        # 条件: license / location / issuer / category / expired /
        #       grades / grade / score / unified_kind
        "shortfalls": [],
        # 確かめられなかった要件（建設業許可が未登録など）。資格不足なら「要確認」として添える
        "notes": [],
        "matched": None,
        "expired": [],
        "issuer_known": False,
        "checked": [],  # 実際に突き合わせて満たした要件（画面に根拠として出す）
        # 1つ目の不足の条件（shortfalls[0]）
        "failed_on": "",
        # 公告から読み取った建設業許可・営業所の所在地の要件（画面に出す）
        "license_requirement": {},
    }

    # 公告が建設業許可・営業所の所在地を求めていれば照らす。書かれていなければ何もしない。
    _check_license_requirement(project, licenses, today, result)

    # 公告が全省庁統一資格（物品・役務）を求めている案件は、発注機関ではなく
    # 統一資格の種類と等級で判定する。
    issuer_type = (project.required_issuer_type or "").strip()
    if issuer_type == UNIFIED_QUALIFICATION_ISSUER:
        _check_unified(project, qualifications, today, result)
        return _finish(result)

    # 公告に資格を出す機関が書かれていればそれを使う。
    # 自衛隊の基地（案件側「海上自衛隊 横須賀基地」）は防衛省の資格で参加する。
    bid_issuer = issuer_type or project.client or ""
    if not bid_issuer:
        result["reason"] = "発注機関が未入力のため判定できません。"
        return _finish(result)

    # 1. 発注機関で絞る
    by_issuer = []
    for qual in qualifications:
        if qual.issuer == UNIFIED_QUALIFICATION_ISSUER:
            continue
        score = _issuer_match_score(bid_issuer, qual.issuer)
        if score:
            by_issuer.append((score, qual))
    if not by_issuer:
        # 資格マスタに1件以上登録がある場合、対応する資格が無い＝資格不足。
        # 管轄区域外（例: 北関東防衛局の管轄に神奈川県が含まれない）も
        # このケースに該当する。
        has_any = any(q.issuer != UNIFIED_QUALIFICATION_ISSUER for q in qualifications)
        if has_any:
            _add_shortfall(
                result, "issuer",
                f"「{bid_issuer}」に対応する入札参加資格がありません。"
                "管轄区域に自社の所在地が含まれていない可能性があります。",
            )
        else:
            result["reason"] = (
                "入札参加資格が未登録です。"
                "資格マスタに登録すると自動判定できます。"
            )
        return _finish(result)

    result["issuer_known"] = True

    # 2. 工事種別で絞る。公告が業種を列挙していればそちらを優先する
    #    （スクレイパーは「物品・役務」のような大枠しか付けないことがある）。
    category = project.required_category or project.category or ""
    candidates = category_candidates(category)
    if not candidates:
        result["reason"] = (
            f"工事種別「{category or '未設定'}」に対応する業種区分が判断できません。"
            "公告で確認してください。"
        )
        return _finish(result)

    matched = [
        (score, qual) for score, qual in by_issuer
        if _category_matches(qual.category, candidates)
    ]
    if not matched:
        _add_shortfall(
            result, "category",
            f"「{bid_issuer}」には登録がありますが、"
            f"{category} に対応する業種区分（{'／'.join(candidates)}）の資格がありません。",
        )
        return _finish(result)

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
    if valid:
        best = valid[0][1]
    else:
        # 期限が切れていても、等級・点数の不足は続けて確かめる（一番新しい資格で見る）
        best = max(result["expired"], key=lambda q: q.valid_until)
        _add_shortfall(
            result, "expired",
            f"{best.issuer}／{best.category} の資格は "
            f"{best.valid_until} に有効期限が切れています。",
        )

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
            _add_shortfall(
                result, "grades",
                f"{label}の認定が必要ですが、自社は {ours} 等級です（{detail}）。",
            )
        else:
            result["checked"].append(f"{label} → 自社 {ours} 等級")

    # 5. 等級の下限が書かれている場合
    floor = normalize_grade(project.required_grade)
    if floor and ours:
        if GRADE_ORDER[ours] < GRADE_ORDER[floor]:
            _add_shortfall(
                result, "grade",
                f"{floor}等級以上が必要ですが、自社は {ours} 等級です（{detail}）。",
            )
        else:
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
            _add_shortfall(
                result, "score",
                f"{project.required_score}点以上が必要ですが、"
                f"自社は {our_score} 点です（{detail}）。",
            )
        else:
            result["checked"].append(
                f"{project.required_score}点以上 → 自社 {our_score} 点"
            )

    if not result["shortfalls"]:
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
    return _finish(result)


def _add_shortfall(result, failed_on, reason):
    result["shortfalls"].append({"failed_on": failed_on, "reason": reason})


def _finish(result):
    """集めた不足と、確かめられなかった要件から、判定と理由を決める（ADR-0066）。

    - 不足が1つでもあれば資格不足。理由は不足すべてと「要確認: …」
    - 不足が無く、確かめられなかった要件があれば要確認
    - どちらも無ければ、判定の途中で決めた結果と理由のまま
    """
    notes = list(result["notes"])
    if result["eligible"] is None and result["reason"]:
        # 発注機関が未入力など、途中で判定材料が尽きた理由
        notes.append(result["reason"])
    if result["shortfalls"]:
        result["eligible"] = False
        result["failed_on"] = result["shortfalls"][0]["failed_on"]
        lines = [s["reason"] for s in result["shortfalls"]]
        lines += [f"要確認: {note}" for note in notes]
    elif notes:
        result["eligible"] = None
        lines = notes
    else:
        lines = [result["reason"]] if result["reason"] else []
    result["reason_lines"] = lines
    result["reason"] = "\n".join(lines)
    return result


def normalize_trade(name: str) -> str:
    """建設業の業種を突き合わせ用に揃える。「電気工事業」「電気工事」「電気」→「電気」。"""
    text = (name or "").strip()
    if text.endswith("業"):
        text = text[:-1]
    if len(text) > 2 and text.endswith("工事"):
        text = text[:-2]
    return text


def trades_for_category(category: str) -> list[str]:
    """案件の工事種別から建設業許可の業種を決める。「建築一式工事／管工事」は両方。"""
    trades = []
    for part in (category or "").split("／"):
        for needles, trade in TRADE_ALIASES:
            if any(n in part for n in needles):
                if trade not in trades:
                    trades.append(trade)
                break
    return trades


def _check_license_requirement(project, licenses, today, result):
    """公告の建設業許可・営業所の所在地の要件を、自社の建設業許可と照らす（ADR-0065）。

    満たせば result["checked"] に根拠を、満たさなければ result["shortfalls"] に理由を足す。
    建設業許可と営業所の所在地は別々に確かめる（両方足りなければ両方の理由を出す）。
    """
    req = extract_license_requirement(project.requirements or "")
    result["license_requirement"] = req
    if not req["license_class"] and not req["prefectures"]:
        return

    licenses = list(licenses or [])
    if not licenses:
        result["notes"].append(
            "公告は建設業許可（または許可に基づく営業所の所在地）を求めていますが、"
            "自社の建設業許可が未登録のため判定できません。入札参加資格の画面で登録してください。"
        )
        return
    current = [lic for lic in licenses if lic.valid_from <= today <= lic.valid_until]
    if req["license_class"]:
        _check_license_class(project, req, licenses, current, result)
    if req["prefectures"]:
        _check_office_location(req, licenses, current, result)


def _check_license_class(project, req, licenses, current, result):
    """業種の許可があるか・有効期間内か・特定が要るなら特定か。"""
    special = req["license_class"] == "special"
    need = "特定建設業の許可" if special else "建設業の許可"
    trades = req["trades"] or trades_for_category(
        project.required_category or project.category or ""
    )
    if not trades:
        pool = [
            lic for lic in current
            if not special or lic.license_class == ConstructionLicense.LicenseClass.SPECIAL
        ]
        if not pool:
            _add_shortfall(
                result, "license", f"{need}が必要ですが、有効期間内の{need}がありません。",
            )
            return
        names = "・".join(f"{lic.trade}（{lic.get_license_class_display()}）" for lic in pool)
        result["checked"].append(f"{need} → 自社 {names}（業種は公告で確認）")
        return

    label = "・".join(trades)
    wanted = {normalize_trade(t) for t in trades}
    same = [lic for lic in licenses if normalize_trade(lic.trade) in wanted]
    if not same:
        ours = "・".join(sorted({lic.trade for lic in licenses}))
        _add_shortfall(
            result, "license",
            f"{label}の{need}が必要ですが、自社の建設業許可は {ours} だけです。",
        )
        return
    same_current = [lic for lic in same if lic in current]
    if not same_current:
        newest = max(same, key=lambda lic: lic.valid_until)
        _add_shortfall(
            result, "license",
            f"{label}の{need}が必要ですが、自社の{newest.trade}の許可は "
            f"{newest.valid_until} に有効期間が切れています（{newest.full_number}）。",
        )
        return
    if special:
        specials = [
            lic for lic in same_current
            if lic.license_class == ConstructionLicense.LicenseClass.SPECIAL
        ]
        if not specials:
            ours = same_current[0]
            _add_shortfall(
                result, "license",
                f"{label}の特定建設業の許可が必要ですが、自社の{ours.trade}は"
                f"一般建設業の許可です（{ours.full_number}）。",
            )
            return
        same_current = specials
    best = same_current[0]
    result["checked"].append(
        f"{need}（{label}） → 自社 {best.trade} "
        f"{best.get_license_class_display()} {best.full_number}"
    )


def _check_office_location(req, licenses, current, result):
    """知事許可の都道府県が、公告の求める地域に入っているか。"""
    area = "、".join(req["prefectures"])
    area_label = f"{req['area_name']}の管轄区域（{area}）" if req["area_name"] else area
    pool = current or licenses
    if any(lic.grantor_type == ConstructionLicense.GrantorType.MINISTER for lic in pool):
        result["checked"].append(f"営業所の所在地 {area_label} → 国土交通大臣許可のため公告で確認")
        return
    ours, authorities = [], []
    for lic in pool:
        m = _GOVERNOR_PREFECTURE.search(lic.authority or "")
        if m and m.group(1) not in ours:
            ours.append(m.group(1))
            authorities.append(lic.authority)
    if not ours:
        result["checked"].append(
            f"営業所の所在地 {area_label} → 許可行政庁から都道府県が分からないため公告で確認"
        )
    elif not set(ours) & set(req["prefectures"]):
        _add_shortfall(
            result, "location",
            f"{area_label}に建設業許可に基づく本店・支店・営業所が必要ですが、"
            f"自社は{'・'.join(authorities)}の許可のため、営業所は{'・'.join(ours)}だけです。",
        )
    else:
        result["checked"].append(f"営業所の所在地 {area_label} → 自社 {'・'.join(ours)}")


def _check_unified(project, qualifications, today, result):
    """全省庁統一資格（物品の販売・役務の提供等・物品の買受け）で判定する。

    種類が一致する資格を探し、有効期限と等級（列挙・下限）を見る。不足はすべて集める。
    営業品目は公告の資格要件に書かれないので見ない。
    """
    kind = (project.required_category or "").strip()
    result["issuer_known"] = True
    same_kind = [
        q for q in qualifications
        if q.issuer == UNIFIED_QUALIFICATION_ISSUER
        and normalize_category(q.category) == normalize_category(kind)
    ]
    if not same_kind:
        has_unified = any(q.issuer == UNIFIED_QUALIFICATION_ISSUER for q in qualifications)
        _add_shortfall(
            result, "unified_kind",
            f"全省庁統一資格「{kind}」の登録がありません。"
            if has_unified else
            "全省庁統一資格が未登録です。資格マスタに登録すると自動判定できます。",
        )
        return

    valid = [q for q in same_kind if q.valid_until is None or q.valid_until >= today]
    result["expired"] = [
        q for q in same_kind if q.valid_until is not None and q.valid_until < today
    ]
    if valid:
        valid.sort(key=lambda q: GRADE_ORDER.get(normalize_grade(q.grade), 0), reverse=True)
        best = valid[0]
    else:
        best = max(result["expired"], key=lambda q: q.valid_until)
        _add_shortfall(
            result, "expired",
            f"全省庁統一資格「{kind}」は {best.valid_until} に有効期限が切れています。",
        )
    result["matched"] = best
    detail = _describe(best)
    ours = normalize_grade(best.grade)
    listed = "".join(sorted({
        g for g in (project.required_grades or "").upper() if g in GRADE_ORDER
    }))
    if listed:
        label = "・".join(f"{g}等級" for g in listed)
        if not ours:
            result["notes"].append(
                f"{label}の認定が必要ですが、自社の等級が未登録のため判定できません（{detail}）。"
            )
        elif ours not in listed:
            _add_shortfall(
                result, "grades",
                f"{label}の認定が必要ですが、自社は {ours} 等級です（{detail}）。",
            )
        else:
            result["checked"].append(f"{label} → 自社 {ours} 等級")
    floor = normalize_grade(project.required_grade)
    if floor:
        if not ours:
            result["notes"].append(
                f"{floor}等級以上が必要ですが、自社の等級が未登録のため判定できません（{detail}）。"
            )
        elif GRADE_ORDER[ours] < GRADE_ORDER[floor]:
            _add_shortfall(
                result, "grade",
                f"{floor}等級以上が必要ですが、自社は {ours} 等級です（{detail}）。",
            )
        else:
            result["checked"].append(f"{floor}等級以上 → 自社 {ours} 等級")

    if not result["shortfalls"]:
        result["eligible"] = True
        if result["checked"]:
            result["reason"] = (
                "公告の要件を満たします（" + "／".join(result["checked"]) + f"、{detail}）。"
            )
        else:
            result["reason"] = (
                f"登録があります（{detail}）。等級の要件は公告本文で確認してください。"
            )


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
    # 公告が建設業許可を求めるときに照らす自社の許可（ADR-0065）
    licenses = list(ConstructionLicense.unscoped.filter(company=company))
    return {
        p.pk: check_project(p, qualifications, today=today, licenses=licenses)
        for p in projects
    }


def related_qualifications(required_issuer_type, required_category, qualifications):
    """公告が求める資格と照らすために、自社の関係する資格を並べて返す。

    見送り案件の画面で「公告が求める資格」の隣に出す。判定はしない。

    Returns:
        {
            "issuer_label": 見出しに使う機関名,
            "rows": [{"qual": Qualification, "hit": 求める種類・業種と一致するか}],
        }
    """
    issuer_type = (required_issuer_type or "").strip()
    if issuer_type == UNIFIED_QUALIFICATION_ISSUER:
        wanted = normalize_category(required_category)
        rows = [
            {"qual": q, "hit": normalize_category(q.category) == wanted}
            for q in qualifications if q.issuer == UNIFIED_QUALIFICATION_ISSUER
        ]
        rows.sort(key=lambda r: (not r["hit"], r["qual"].category))
        return {"issuer_label": UNIFIED_QUALIFICATION_ISSUER, "rows": rows}

    if not issuer_type:
        return {"issuer_label": "", "rows": []}

    # 「建築一式工事／管工事」のように列挙されていれば、どれかに当たれば一致
    wanted = [
        c for part in (required_category or "").split("／")
        for c in category_candidates(part.strip())
    ]
    rows = []
    for q in qualifications:
        if q.issuer == UNIFIED_QUALIFICATION_ISSUER:
            continue
        if not _issuer_match_score(issuer_type, q.issuer):
            continue
        hit = bool(wanted) and _category_matches(q.category, tuple(wanted))
        rows.append({"qual": q, "hit": hit})
    rows.sort(key=lambda r: (not r["hit"], r["qual"].issuer, r["qual"].category))
    return {"issuer_label": issuer_type, "rows": rows}
