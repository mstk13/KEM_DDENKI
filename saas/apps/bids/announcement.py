"""入札公告（PDF）から工事概要・参加要件を切り出す。

情報源URL（BidProject.source_url）が指す公開文書は、発注機関のサイトに
置かれた公告PDF、または e-bisc の公開文書サーブレットが返すPDF。
どちらも「番号 + 見出し」で章立てされた同じ体裁で、
工事概要と参加資格の節がある。

2026-08-14 に実案件11件（防衛省北関東防衛局・国土交通省関東/中部地方整備局）で
確認した結果、工事概要 10/11・参加要件 10/11 が取れた。
取れなかった1件はフォントに ToUnicode が無く、テキストが (cid:NNN) にしか
ならないPDF。OCR が要るのでここでは扱わず、取得できなかったこととして返す。

注意:
- 相手は官公庁サイトなのでリクエスト間隔を空ける
- 章見出しの語彙は発注機関ごとに違う（「工事概要」「業務概要」「工事の概要」、
  「競争参加資格」「技術資料等の提出を求める対象者に必要な要件」…）。
  語彙を並べるのではなく「番号付きの短い行」という構造で拾い、
  見出しに含まれる語で分類する
"""
from __future__ import annotations

import io
import logging
import re
import ssl
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

USER_AGENT = (
    "KEC-BidMonitor/1.0 "
    "(Construction company bid monitoring; contact: admin@kem-ddenki.com)"
)
REQUEST_INTERVAL = 2.0  # 秒
TIMEOUT = 60

# 章見出し: 行頭の番号 + 区切り + 空白を含まない見出し語。
# 「４．入札手続等 入札説明書の交付期間及び受 令和８年…」のような表の行を
# 見出しと誤認しないよう、見出し語に空白を許さない。
HEADING = re.compile(
    r"(?m)^[ 　]*([0-9０-９]{1,2})[ 　．.、][ 　]*([^\s　]{2,40})[ 　]*$"
)
OUTLINE_WORDS = ("概要",)
REQUIREMENT_WORDS = ("資格", "要件")
# 「総合評価に関する事項」を要件と取り違えないための除外語
REQUIREMENT_EXCLUDE = ("総合評価", "入札手続", "その他", "契約手続")

# 「Ｄ等級以上」のように下限が明示されている場合の等級要件。
GRADE_FLOOR = re.compile(r"([ＡＢＣＤA-D])\s*(?:等級|級)\s*以上")

# 公告が認定を求める等級。国土交通省は「電気設備工事Ｂ等級又はＣ等級に
# 認定されている者であること」と列挙で書く。下限ではないので、
# 大小比較ではなく集合として扱う（Ａ等級しか無い会社はＢ・Ｃ指定に参加できない）。
GRADE = re.compile(r"([ＡＢＣＤA-D])\s*等級")
GRADE_CONTEXT = ("認定", "格付", "参加資格")
# 工事成績評定点の話を等級と取り違えないための除外語
GRADE_EXCLUDE = ("評定", "成績")

# 点数の下限。防衛省は等級ではなくこれで切る。
# 「総合審査数値（…欄の点数）が780点以上」「経営事項評価数値…が1,100点以上」
SCORE = re.compile(r"([0-9０-９][0-9０-９,，]{1,6})\s*点\s*以上")
SCORE_CONTEXT = (
    "総合審査数値", "経営事項評価数値", "総合点数", "総合数値", "総合評点",
    "審査数値", "評価数値",
)
# 「工事成績評定点が65点未満」「証明をもって65点以上の工事とみなす」は
# 過去の工事成績の話で、資格の点数ではない。
SCORE_EXCLUDE = ("評定", "成績", "とみなす")

# 文脈を見る窓の広さ（前 / 後）
CONTEXT_BACK, CONTEXT_FORWARD = 120, 40
_ZENKAKU = str.maketrans("０１２３４５６７８９，ＡＢＣＤ", "0123456789,ABCD")

_last_request_at = 0.0


def _rate_limit():
    global _last_request_at
    elapsed = time.time() - _last_request_at
    if elapsed < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - elapsed)
    _last_request_at = time.time()


def fetch_document(url: str) -> bytes | None:
    """公告文書を取得する。取れなければ None。"""
    if not url:
        return None
    _rate_limit()
    # 官公庁サイトに証明書チェーンが古いものが混ざっており、
    # 検証を有効にすると取得できない発注機関がある。
    # 取得するのは公開済みの公告文書のみで、こちらから送る情報は無い。
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=ctx) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("公告文書を取得できませんでした: %s (%s)", url, e)
        return None


def extract_text(data: bytes | None) -> str:
    """PDFのバイト列からテキストを取り出す。PDF以外は空文字。"""
    if not data or not data.startswith(b"%PDF"):
        return ""
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception as e:
        logger.warning("PDFを読めませんでした: %s", e)
        return ""


def is_garbled(text: str) -> bool:
    """フォントに ToUnicode が無く (cid:NNN) しか取れないPDFかどうか。"""
    return bool(text) and text.count("(cid:") > max(20, len(text) // 200)


def _drop_page_numbers(text: str) -> str:
    """ページ番号だけの行を落とす。章の本文に紛れ込むため。"""
    return "\n".join(
        line for line in text.splitlines() if not re.fullmatch(r"\s*\d{1,3}\s*", line)
    )


def split_sections(text: str) -> list[tuple[str, str]]:
    """番号付き見出しで区切って [(見出し, 本文), ...] を返す。"""
    marks = list(HEADING.finditer(text))
    sections = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        sections.append((mark.group(2), text[mark.end():end].strip()))
    return sections


def extract_grade_floor(text: str) -> str:
    """要件本文から「X等級以上」の下限を返す。列挙は対象外。"""
    hits = {g.translate(_ZENKAKU) for g in GRADE_FLOOR.findall(text or "")}
    # 複数書かれていれば緩いほう（＝アルファベット順で後ろ）が下限
    return max(hits) if hits else ""


def _flatten(text: str) -> str:
    """PDF由来の折り返しを潰す。

    文の途中で改行されており、括弧の中にも「。」が入るため、
    句点で文に切る方法は使えない。前後の文字数で窓を取る。
    """
    return re.sub(r"\s+", "", text or "")


def _has_context(flat: str, match, wanted, unwanted) -> bool:
    window = flat[max(0, match.start() - CONTEXT_BACK):match.end() + CONTEXT_FORWARD]
    return any(w in window for w in wanted) and not any(w in window for w in unwanted)


def extract_grades(text: str) -> str:
    """公告が認定を求める等級を返す。「Ｂ等級又はＣ等級」なら "BC"。"""
    flat = _flatten(text)
    hits = {
        m.group(1).translate(_ZENKAKU)
        for m in GRADE.finditer(flat)
        if _has_context(flat, m, GRADE_CONTEXT, GRADE_EXCLUDE)
    }
    return "".join(sorted(hits))


def extract_score_floor(text: str) -> int | None:
    """総合審査数値・経営事項評価数値の下限を返す。

    共同企業体の構成員向けに緩い点数が併記されることがあるので、
    単体で参加する前提の厳しいほう（最大値）を採る。
    """
    flat = _flatten(text)
    best = None
    for m in SCORE.finditer(flat):
        if not _has_context(flat, m, SCORE_CONTEXT, SCORE_EXCLUDE):
            continue
        value = int(m.group(1).translate(_ZENKAKU).replace(",", ""))
        best = value if best is None else max(best, value)
    return best


def extract_sections(text: str) -> dict:
    """公告テキストから工事概要・参加要件・必要等級を取り出す。

    Returns:
        {"work_outline": str, "requirements": str,
         "required_grade": str, "headings": list[str], "garbled": bool}
    """
    empty = {
        "work_outline": "",
        "requirements": "",
        "required_grade": "",
        "required_grades": "",
        "required_score": None,
        "headings": [],
        "garbled": False,
    }
    if not text:
        return empty
    if is_garbled(text):
        logger.info("公告PDFの文字が (cid) 化しており読めません（OCR未対応）")
        return {**empty, "garbled": True}

    sections = split_sections(_drop_page_numbers(text))
    outline = next(
        (body for head, body in sections
         if any(w in head for w in OUTLINE_WORDS) and body),
        "",
    )
    requirements = next(
        (body for head, body in sections
         if any(w in head for w in REQUIREMENT_WORDS)
         and not any(x in head for x in REQUIREMENT_EXCLUDE)
         and body),
        "",
    )
    return {
        "work_outline": outline,
        "requirements": requirements,
        "required_grade": extract_grade_floor(requirements),
        "required_grades": extract_grades(requirements),
        "required_score": extract_score_floor(requirements),
        "headings": [head for head, _ in sections],
        "garbled": False,
    }


def extract_from_url(url: str) -> dict:
    """情報源URLから工事概要・参加要件を取り出す。"""
    return extract_sections(extract_text(fetch_document(url)))
