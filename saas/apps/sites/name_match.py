"""現場名の重複を、入力の途中で気づけるようにする（ADR-0077）。

同じ現場が別々に登録されてしまう原因は、名前そのものではなく表記のゆれにある。

    七沢自然ふれあいセンター改修工事
    七沢自然ふれあいセンター　改修工事      ← 全角スペース
    七沢自然ふれあいｾﾝﾀｰ改修工事           ← 半角カナ
    （仮）七沢自然ふれあいセンター改修工事   ← 頭に注記

ブラウザの <datalist> は入力した文字を前方・部分一致で拾うだけなので、
上のような1文字のゆれで候補から外れる。そこで、比べる前に表記を均し、
似ている度合いで拾い直す。

重複を**弾かない**のは、同じ建物の別年度の工事が同じ名前になることが
正当にあるため（「○○小学校電気設備改修工事」が毎年ある）。
気づかせるところまでを機械の仕事とし、分けるか一つにするかは人が決める。
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# 名前の違いに関わらない語。取り除いてから比べる。
# 「工事」だけが違う2件は同じ現場を指していることが多い。
_NOISE_WORDS = (
    "工事", "その1", "その2", "その3",
    "株式会社", "有限会社", "(株)", "(有)",
)

# 括弧とその中身。「（仮）」「（第1期）」のような注記を落とす。
_BRACKETS = re.compile(r"[（(\[【][^）)\]】]*[）)\]】]")

# 区切りに使われるだけで意味を持たない文字
_SEPARATORS = re.compile(r"[\s　・･\-－—―~〜_/／,、.。]+")

# これ以上似ていれば候補に出す。0.0〜1.0。
# 0.72 は「その1／その2」の違いだけの2件が拾える程度。
# 下げすぎると同じ市の別現場が並んで、かえって見落とす。
SIMILARITY_THRESHOLD = 0.72


def normalize_site_name(name: str) -> str:
    """比べるための形に均す。表示には使わない。

    NFKC で全角英数と半角カナを寄せ、括弧の注記・区切り・定型語を落とす。
    """
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", name).lower()
    text = _BRACKETS.sub("", text)
    for word in _NOISE_WORDS:
        text = text.replace(unicodedata.normalize("NFKC", word).lower(), "")
    text = _SEPARATORS.sub("", text)
    return text.strip()


def similarity(left: str, right: str) -> float:
    """均したあとの似ている度合い。0.0〜1.0。

    片方がもう片方を丸ごと含むときは 1.0 にする。
    「○○小学校改修」と「○○小学校改修工事（その2）」のように、
    後ろに付け足しただけの名前は、文字数の差で比率が下がってしまうため。
    """
    a, b = normalize_site_name(left), normalize_site_name(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # 短すぎる名前の部分一致は当てにならない（「A棟」が何にでも当たる）
    if len(a) >= 4 and len(b) >= 4 and (a in b or b in a):
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def find_similar_sites(company, name, *, exclude_pk=None, limit=5):
    """似た名前の現場を、似ている順に返す。

    Returns:
        [(Site, 似ている度合い), ...]
    """
    from apps.sites.models import Site

    if not normalize_site_name(name):
        return []

    # unscoped: company を引数で受けて明示的に絞る。
    # 入力途中に呼ばれるので、比較に要る列だけを読む。
    qs = Site.unscoped.filter(company=company).only(
        "id", "code", "name", "status", "start_date", "end_date",
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    scored = []
    for site in qs:
        score = similarity(name, site.name)
        if score >= SIMILARITY_THRESHOLD:
            scored.append((site, score))

    # 似ている順。同点なら新しい現場を先に出す（直近の登録と間違えやすい）
    scored.sort(key=lambda row: (-row[1], -row[0].pk))
    return scored[:limit]
