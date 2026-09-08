"""入札公告（PDF）から工事概要・参加要件を切り出す。

情報源URL（BidProject.source_url）が指す公開文書は、発注機関のサイトに
置かれた公告PDF、または e-bisc の公開文書サーブレットが返すPDF。
どちらも「番号 + 見出し」で章立てされた同じ体裁で、
工事概要と参加資格の節がある。

2026-08-14 に実案件11件（防衛省北関東防衛局・国土交通省関東/中部地方整備局）で
確認した結果、工事概要 10/11・参加要件 10/11 が取れた。
取れなかった1件はフォントに ToUnicode が無く、テキストが (cid:NNN) にしか
ならないPDF。

決定論的に読めないPDFは2種類ある。どちらも `garbled: True` を返し、
呼び出し側（services.fill_announcement）が LLM 読み取りに回す。

  1. (cid) 化 … フォントに ToUnicode が無く文字が化ける
  2. テキスト層なし … スキャン画像のみのPDF。抽出結果がほぼ空になる
     （防衛省「市ヶ谷（８）電気設備更新工事」がこれ）

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
import urllib.parse
import urllib.request
from datetime import date

logger = logging.getLogger(__name__)

USER_AGENT = (
    "KEC-BidMonitor/1.0 "
    "(Construction company bid monitoring; contact: admin@kem-ddenki.com)"
)
REQUEST_INTERVAL = 2.0  # 秒
TIMEOUT = 60

# 発注機関のページに載っているホスト名がそのままでは引けないことがある。
# 防衛省北関東防衛局の公告は `http://www-up.mod.go.jp/...` で案内されるが、
# このホストは名前解決できない（2026-08-15 時点）。同じパスを
# `https://www.mod.go.jp/...` に置くと取得できる。
# 発注機関ごとの実測に基づく対応表で、推測でホストを書き換えることはしない。
HOST_ALIASES = {
    "www-up.mod.go.jp": ("https", "www.mod.go.jp"),
}

# PDF なのに抽出できたテキストがこれ未満なら、テキスト層が無い
# （スキャン画像の）PDF とみなす。公告は最低でも数千字あるので、
# 章立てが取れる文書がこの長さになることはない。
MIN_TEXT_CHARS = 200


def alternate_urls(url: str) -> list[str]:
    """名前解決できないホストの代替URLを返す。該当しなければ空。"""
    if not url:
        return []
    parts = urllib.parse.urlsplit(url)
    alias = HOST_ALIASES.get(parts.hostname or "")
    if not alias:
        return []
    scheme, host = alias
    return [urllib.parse.urlunsplit((scheme, host, parts.path, parts.query, ""))]


def has_no_text_layer(data: bytes | None, text: str) -> bool:
    """PDF は取得できたのにテキスト層が無い（スキャン画像）かどうか。

    (cid) 化と違って文字化けすらせず空に近い結果になるため、
    is_garbled では拾えない。LLM に読ませる対象はこちらも含む。
    """
    return bool(data) and data.startswith(b"%PDF") and len(text.strip()) < MIN_TEXT_CHARS

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

# 「Ｄ等級以上」「「Ｄ」等級以上」のように下限が明示されている場合の等級要件。
# かぎ括弧付き表記（防衛省「Ｄ」等級以上）にも対応。
GRADE_FLOOR = re.compile(r"[「｢]?([ＡＢＣＤA-D])[」｣]?\s*(?:等級|級)\s*以上")

# 公告が認定を求める等級。国土交通省は「電気設備工事Ｂ等級又はＣ等級に
# 認定されている者であること」と列挙で書く。下限ではないので、
# 大小比較ではなく集合として扱う（Ａ等級しか無い会社はＢ・Ｃ指定に参加できない）。
GRADE = re.compile(r"[「｢]?([ＡＢＣＤA-D])[」｣]?\s*等級")
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

# 全省庁統一資格の要件。防衛省（自衛隊各基地）の物品・役務の公告は
# 「防衛省競争参加資格（全省庁統一資格）「物品の販売」のＤ等級以上」と書く。
# PDF の折り返しで「Ｄ等\n級」のように切れるので、空白を潰した文字列に当てる。
# 等級は「Ｄ等級以上」（下限）と「Ｂ，Ｃ又はＤ等級」（列挙）の2通りがある。
UNIFIED_KINDS = ("物品の製造", "物品の販売", "役務の提供等", "物品の買受け")
UNIFIED_REQUIREMENT = re.compile(
    r"全省庁統一資格[）)]?[「｢]?(" + "|".join(UNIFIED_KINDS) + r")[」｣]?の?"
    r"([^。]{1,30}?等級(?:以上)?)"
)
_GRADE_LETTER = re.compile(r"[ＡＢＣＤA-D]")
# 防衛省の建設工事の公告は「「建築一式工事」又は「管工事」で級別の格付けを受け」と
# 業種を列挙する。統一資格ではなく防衛省の工事資格で判定する。
MOD_WORKS_ISSUER = "防衛省"
MOD_WORKS_CATEGORY = re.compile(r"[「｢]([^「｢」｣]{1,12}工事)[」｣]")
MOD_WORKS_CONTEXT = ("格付", "参加資格", "競争参加")

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


def extract_unified_requirement(text: str) -> dict:
    """全省庁統一資格の要件（種類と等級下限）を返す。無ければ空。

    Returns:
        {"kind": "物品の販売", "grade": "D", "grades": ""}    … 「Ｄ等級以上」
        {"kind": "役務の提供等", "grade": "", "grades": "BCD"} … 「Ｂ，Ｃ又はＤ等級」
        {} … 書かれていない
    """
    flat = _flatten(text)
    m = UNIFIED_REQUIREMENT.search(flat)
    if not m:
        return {}
    span = m.group(2)
    letters = "".join(sorted({c.translate(_ZENKAKU) for c in _GRADE_LETTER.findall(span)}))
    if not letters:
        return {}
    if span.endswith("以上"):
        # 「Ｄ等級以上」: 一番低い等級が下限
        return {"kind": m.group(1), "grade": letters[-1], "grades": ""}
    # 「Ｂ，Ｃ又はＤ等級」: 列挙。下限ではなく集合として扱う
    return {"kind": m.group(1), "grade": "", "grades": letters}


def extract_mod_works_categories(text: str) -> list[str]:
    """防衛省の工事公告が格付けを求める業種（「建築一式工事」など）を返す。"""
    flat = _flatten(text)
    if MOD_WORKS_ISSUER + "競争参加資格" not in flat and "防衛省における" not in flat:
        return []
    found = []
    for m in MOD_WORKS_CATEGORY.finditer(flat):
        if not _has_context(flat, m, MOD_WORKS_CONTEXT, ()):
            continue
        name = m.group(1)
        if name not in found:
            found.append(name)
    return found


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
        "required_issuer_type": "",
        "required_category": "",
        "bid_schedule": [],
        "bid_deadline": None,
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
    bid_schedule = extract_bid_schedule(text)
    bid_deadline = extract_deadline_from_schedule(bid_schedule)

    # 資格の種類。統一資格（物品・役務）か、防衛省の工事資格（業種列挙）か。
    # 章の切り出しに失敗しても資格の一文は本文から拾えるよう、全文から探す。
    required_issuer_type = ""
    required_category = ""
    required_grade = extract_grade_floor(requirements)
    required_grades = extract_grades(requirements)
    unified = extract_unified_requirement(text)
    if unified:
        required_issuer_type = "全省庁統一資格"
        required_category = unified["kind"]
        required_grade = unified["grade"]
        required_grades = unified["grades"]
    else:
        works = extract_mod_works_categories(text)
        if works:
            required_issuer_type = MOD_WORKS_ISSUER
            required_category = "／".join(works)
            if not required_grade:
                required_grade = extract_grade_floor(text)
            if required_grade:
                # 「Ｃ・Ｄ等級以上」は下限。列挙として二重に持たない
                required_grades = ""

    return {
        "work_outline": outline,
        "requirements": requirements,
        "required_grade": required_grade,
        "required_grades": required_grades,
        "required_score": extract_score_floor(requirements),
        "required_issuer_type": required_issuer_type,
        "required_category": required_category,
        "bid_schedule": bid_schedule,
        "bid_deadline": bid_deadline,
        "headings": [head for head, _ in sections],
        "garbled": False,
    }


# ---- 別表: 手続きスケジュール抽出 ----

_ZENKAKU_NUM = str.maketrans("０１２３４５６７８９", "0123456789")

# 令和X年Y月Z日 のパターン
_REIWA_DATE = re.compile(
    r"令和\s*[０-９\d]{1,2}\s*年\s*[０-９\d]{1,2}\s*月\s*[０-９\d]{1,2}\s*日"
)
# 同年X月Y日 のパターン（年を省略した参照）
_SAME_YEAR_DATE = re.compile(
    r"同年\s*[０-９\d]{1,2}\s*月\s*[０-９\d]{1,2}\s*日"
)
# HH時MM分 のパターン
_TIME_HM = re.compile(r"[０-９\d]{1,2}\s*時\s*[０-９\d]{1,2}\s*分")
# HH時 のパターン（「分」省略）
_TIME_H = re.compile(r"[０-９\d]{1,2}\s*時(?!\s*[０-９\d])")
# 正午
_NOON = re.compile(r"正午")


def _parse_date_str(text: str) -> date | None:
    """令和日付文字列を date オブジェクトに変換する。"""
    from datetime import date as _date

    raw = text.translate(_ZENKAKU_NUM)
    raw = re.sub(r"\s+", "", raw)
    m = re.search(r"令和(\d+)年(\d+)月(\d+)日", raw)
    if not m:
        return None
    try:
        return _date(2018 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _parse_same_year_date(text: str, ref_year: int) -> date | None:
    """「同年X月Y日」を参照年で解決する。"""
    from datetime import date as _date

    raw = text.translate(_ZENKAKU_NUM)
    raw = re.sub(r"\s+", "", raw)
    m = re.search(r"同年(\d+)月(\d+)日", raw)
    if not m:
        return None
    try:
        return _date(ref_year, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def _extract_time(text: str) -> str:
    """テキストから時刻を抽出する。「正午」「17時」「12時00分」に対応。

    日付の直後に来る時刻がその項目の時刻なので、書式の優先順位ではなく
    「最も手前に現れたもの」を採る。防衛省の別表は開札の行のあとに
    「（紙入札方式の場合は……正午から13時までの間を除く）」という注記が続き、
    正午を先に見ると開札 15 時が 12:00 に化ける。

    Returns: "HH:MM" または ""
    """
    found = []

    m = _NOON.search(text)
    if m:
        found.append((m.start(), "12:00"))

    m = _TIME_HM.search(text)
    if m:
        raw = re.sub(r"\s+", "", m.group().translate(_ZENKAKU_NUM))
        tm = re.match(r"(\d+)時(\d+)分", raw)
        if tm:
            found.append(
                (m.start(), f"{int(tm.group(1)):02d}:{int(tm.group(2)):02d}")
            )

    m = _TIME_H.search(text)
    if m:
        raw = re.sub(r"\s+", "", m.group().translate(_ZENKAKU_NUM))
        tm = re.match(r"(\d+)時", raw)
        if tm:
            found.append((m.start(), f"{int(tm.group(1)):02d}:00"))

    if not found:
        return ""
    return min(found)[1]


def _make_datetime_str(d: date, time_str: str) -> str:
    """date と時刻文字列から ISO datetime を作る。"""
    if time_str:
        return f"{d.isoformat()}T{time_str}"
    return d.isoformat()


def _rejoin_split_dates(text: str) -> str:
    """PDFテキスト抽出で行をまたいで分割された令和日付を結合する。"""
    text = re.sub(r"令和\s*\n\s*(?=[０-９\d])", "令和", text)
    text = re.sub(r"(\d{1,2}\s*時\s*\d{1,2})\s*\n\s*分", r"\1 分", text)
    return text


def _clean_block(text: str) -> str:
    """ブロックテキストからPDFアーティファクトを除去する。"""
    text = re.sub(r"（[０-９0-9]{1,2}）", " ", text)
    text = re.sub(
        r"令和\s+[^\d０-９]*?([０-９\d]{1,2}\s*年)",
        r"令和\1",
        text,
    )
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# 番号付き項目のパターン: ①② or (1)(2) or ア イ
_NUMBERED_ITEM = re.compile(
    r"(?:^|\n)\s*([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮])\s*"
)

# 別表の節番号（「４．入札手続等」など）
_SECTION_NUM = re.compile(r"[０-９0-9]{1,2}[．.]")

# 日付を含む項目として認識するキーワード（ラベルの正規化に使う）
_LABEL_NORMALIZE = [
    (r"配置予定技術者.*専任", "配置予定技術者の専任期間"),
    (r"入札説明書.*交付", "入札説明書等の交付期間"),
    (r"申請書.*技術", "申請書・技術資料の提出期限"),
    (r"申請書.*提出期限", "申請書・技術資料の提出期限"),
    (r"技術提案.*提出期限", "申請書・技術資料の提出期限"),
    (r"見積.*提出期限", "見積等の提出期限"),
    (r"入札書.*受領期限", "入札書の受領期限"),
    (r"入札.*締切", "入札の締切"),
    (r"入札説明書.*受付", "入札説明書の交付・受付期限"),
    (r"申請書.*受付期限", "申請書・資料の受付期限"),
    (r"歩掛見積参考資料", "歩掛見積参考資料の交付期限"),
    (r"開札.*日時", "開札"),
    (r"開札", "開札"),
]


def _normalize_label(raw_label: str) -> str:
    """項目ラベルを正規化する。"""
    for pattern, normalized in _LABEL_NORMALIZE:
        if re.search(pattern, raw_label):
            return normalized
    # マッチしなければ、余分な空白を潰して返す
    return re.sub(r"\s+", "", raw_label).strip()


def _final_day_time(block: str) -> str:
    """「（ただし、最終日は17時まで）」の時刻を返す。無ければ空文字。

    交付期間の本文は「9時から18時まで（ただし、最終日は17時まで）」のように
    日々の受付時間を先に書く。期間の締め切りとして意味があるのは最終日の方。
    """
    if "最終日" not in block:
        return ""
    return _extract_time(block[block.index("最終日"):])


def _extract_last_date_with_time(block: str, ref_year: int = 0) -> str | None:
    """ブロックから最後の日付+時刻を抽出する（期間の終了日用）。"""
    # 「同年」を先にチェック
    same_year_dates = list(_SAME_YEAR_DATE.finditer(block))
    reiwa_dates = list(_REIWA_DATE.finditer(block))

    if same_year_dates and ref_year:
        last = same_year_dates[-1]
        d = _parse_same_year_date(last.group(), ref_year)
        if d:
            after = block[last.end():]
            time_str = _final_day_time(block) or _extract_time(after)
            return _make_datetime_str(d, time_str)

    if reiwa_dates:
        last = reiwa_dates[-1]
        d = _parse_date_str(last.group())
        if d:
            after = block[last.end():]
            time_str = _final_day_time(block) or _extract_time(after)
            return _make_datetime_str(d, time_str)

    return None


def _extract_first_date_with_time(block: str) -> str | None:
    """ブロックから最初の日付+時刻を抽出する（単一イベント用）。"""
    m = _REIWA_DATE.search(block)
    if not m:
        return None
    d = _parse_date_str(m.group())
    if not d:
        return None
    after = block[m.end():]
    time_str = _extract_time(after)
    return _make_datetime_str(d, time_str)


def _extract_range_start(block: str, end: str | None) -> str:
    """期間項目の開始日時を返す。取れなければ空文字。

    「令和8年9月4日から同年11月10日まで」の前半。終了日時（end）より
    後ろに来てしまったら日付の拾い違いなので捨てる。
    """
    if not end:
        return ""
    start = _extract_first_date_with_time(block)
    if not start or start >= end:
        return ""
    return start


def _is_range_item(label: str) -> bool:
    """期間（から〜まで）を表す項目か。"""
    return any(w in label for w in ("交付期間", "交付・受付", "専任期間"))


def extract_bid_schedule(text: str) -> list[dict]:
    """公告テキストから手続きスケジュールを汎用的に抽出する。

    2つの形式に対応:
    1. 別表形式（国交省）: 「４．入札手続等 入札説明書の交付期間 令和...」
    2. 番号付き形式（防衛省）: 「① 配置予定技術者の専任期間 令和...」

    Returns:
        [{"label": "入札の締切", "datetime": "2026-09-10T12:00",
          "detail": "..."}, ...]
    """
    if not text:
        return []

    text = _rejoin_split_dates(text)
    schedule = []
    seen_labels = set()

    # --- 方式1: 番号付き項目（①②③...）を探す ---
    items = list(_NUMBERED_ITEM.finditer(text))
    ref_year = 0  # 「同年」解決用

    for idx, item_match in enumerate(items):
        # このアイテムの範囲: 現在の番号から次の番号まで
        start = item_match.end()
        end = items[idx + 1].start() if idx + 1 < len(items) else min(start + 500, len(text))
        block_raw = text[start:end]
        block = _clean_block(block_raw)

        # 日付があるか
        has_date = bool(_REIWA_DATE.search(block) or _SAME_YEAR_DATE.search(block))
        if not has_date:
            continue

        # ラベル抽出: 最初の日付の前のテキスト
        date_pos = _REIWA_DATE.search(block)
        same_pos = _SAME_YEAR_DATE.search(block)
        first_date_start = min(
            (date_pos.start() if date_pos else 9999),
            (same_pos.start() if same_pos else 9999),
        )
        raw_label = block[:first_date_start].strip()
        label = _normalize_label(raw_label)

        if label in seen_labels:
            continue

        # 参照年を更新
        if date_pos:
            d = _parse_date_str(date_pos.group())
            if d:
                ref_year = d.year

        # 期間の場合は最後の日付、単一イベントは最初
        start = ""
        if _is_range_item(label):
            dt = _extract_last_date_with_time(block, ref_year)
            start = _extract_range_start(block, dt)
        else:
            dt = _extract_first_date_with_time(block)

        if not dt:
            continue

        # 補足情報
        detail = ""
        if "電子入札" in block:
            detail = "電子入札システム"
        if "最終日" in block:
            time_str = _extract_time(block[block.index("最終日"):])
            if time_str:
                suffix = f"最終日は{time_str}まで"
                detail = f"{detail}（{suffix}）" if detail else suffix
        # 場所情報
        place_m = re.search(r"([\w]+局\s*[\w]*階[\w]*室)", block)
        if place_m:
            detail = f"{detail} {place_m.group()}" if detail else place_m.group()

        schedule.append({
            "label": label,
            "start": start,
            "datetime": dt,
            "detail": detail.strip(),
        })
        seen_labels.add(label)

    # --- 方式2: 別表形式（「X．入札手続等 ... 令和...」）---
    # 番号付き形式で何も取れなかった場合にフォールバック
    if not schedule:
        lines = text.splitlines()
        _FALLBACK_KEYS = [
            ("入札説明書の交付期間", "入札説明書の交付・受付期限", True),
            ("受付期間", "入札説明書の交付・受付期限", True),
            ("申請書.*受付", "申請書・資料の受付期限", False),
            ("歩掛見積参考資料", "歩掛見積参考資料の交付期限", True),
            ("入札の締切", "入札の締切", False),
            ("入札締切", "入札の締切", False),
            ("開札", "開札", False),
        ]
        for keyword, label, is_range in _FALLBACK_KEYS:
            if label in seen_labels:
                continue
            pattern = re.compile(keyword)
            for i, line in enumerate(lines):
                if not pattern.search(line):
                    continue
                # ブロック取得
                block_lines = [lines[i]]
                for j in range(i + 1, min(i + 12, len(lines))):
                    ln = lines[j].strip()
                    if _SECTION_NUM.match(ln):
                        break
                    block_lines.append(lines[j])
                block = _clean_block(" ".join(block_lines))

                start = ""
                if is_range:
                    dt = _extract_last_date_with_time(block)
                    start = _extract_range_start(block, dt)
                else:
                    dt = _extract_first_date_with_time(block)
                if not dt:
                    continue

                detail = ""
                if "電子入札" in block:
                    detail = "電子入札システム"
                if "最終日" in block:
                    time_str = _extract_time(block[block.index("最終日"):])
                    if time_str:
                        suffix = f"最終日は{time_str}まで"
                        detail = f"{detail}（{suffix}）" if detail else suffix

                schedule.append({
                    "label": label,
                    "start": start,
                    "datetime": dt,
                    "detail": detail.strip(),
                })
                seen_labels.add(label)
                break

    return schedule


def extract_deadline_from_schedule(schedule: list[dict]) -> str | None:
    """スケジュールから最も早い提出期限を返す。

    優先順位: 申請書の提出期限 > 入札の締切/受領期限 > その他の受付期限
    """
    for item in schedule:
        if "申請書" in item["label"]:
            return item["datetime"]
    for item in schedule:
        if any(w in item["label"] for w in ("入札の締切", "入札書の受領", "入札締切")):
            return item["datetime"]
    for item in schedule:
        if "受付" in item["label"] or "提出" in item["label"]:
            return item["datetime"]
    return None


def extract_from_url(url: str) -> dict:
    """情報源URLから工事概要・参加要件を取り出す。"""
    data = fetch_document(url)
    text = extract_text(data)
    result = extract_sections(text)
    if not result["garbled"] and has_no_text_layer(data, text):
        # スキャン画像のPDF。決定論的には読めないので LLM に回す。
        logger.info("公告PDFにテキスト層がありません（スキャン画像）: %s", url)
        return {**result, "garbled": True}
    return result
