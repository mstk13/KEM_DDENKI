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

    return {
        "work_outline": outline,
        "requirements": requirements,
        "required_grade": extract_grade_floor(requirements),
        "required_grades": extract_grades(requirements),
        "required_score": extract_score_floor(requirements),
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
# HH時MM分 のパターン
_TIME_HM = re.compile(r"[０-９\d]{1,2}\s*時\s*[０-９\d]{1,2}\s*分")

# 別表で抽出したい手続き項目のキーワードと表示ラベル
_SCHEDULE_KEYS = [
    ("入札説明書の交付期間", "入札説明書の交付・受付期限"),
    ("受付期間", "入札説明書の交付・受付期限"),
    ("申請書及び資料の受付期限", "申請書・資料の受付期限"),
    ("申請書.*受付", "申請書・資料の受付期限"),
    ("歩掛見積参考資料の交付期間", "歩掛見積参考資料の交付期限"),
    ("歩掛見積参考資料", "歩掛見積参考資料の交付期限"),
    ("入札の締切", "入札の締切"),
    ("入札締切", "入札の締切"),
    ("開札", "開札"),
]


def _parse_reiwa_datetime(text: str) -> str | None:
    """テキストから令和の日付+時刻を ISO datetime 文字列に変換する。

    「令和８年９月10日（木）12時00分」→ "2026-09-10T12:00"
    時刻がなければ None。日付だけでは返さない（DateField と区別するため）。
    """
    from datetime import date as _date

    date_m = _REIWA_DATE.search(text)
    if not date_m:
        return None
    raw = date_m.group().translate(_ZENKAKU_NUM)
    raw = re.sub(r"\s+", "", raw)
    dm = re.match(r"令和(\d+)年(\d+)月(\d+)日", raw)
    if not dm:
        return None
    try:
        d = _date(2018 + int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
    except ValueError:
        return None

    # 時刻を探す（日付の後ろのテキスト全体から）
    after_date = text[date_m.end():]
    time_m = _TIME_HM.search(after_date)
    if time_m:
        raw_t = time_m.group().translate(_ZENKAKU_NUM)
        raw_t = re.sub(r"\s+", "", raw_t)
        tm = re.match(r"(\d+)時(\d+)分", raw_t)
        if tm:
            return f"{d.isoformat()}T{int(tm.group(1)):02d}:{int(tm.group(2)):02d}"

    return d.isoformat()


def _parse_reiwa_date_only(text: str) -> str | None:
    """日付のみ（時刻なし）の場合でも ISO date を返す。"""
    from datetime import date as _date

    date_m = _REIWA_DATE.search(text)
    if not date_m:
        return None
    raw = date_m.group().translate(_ZENKAKU_NUM)
    raw = re.sub(r"\s+", "", raw)
    dm = re.match(r"令和(\d+)年(\d+)月(\d+)日", raw)
    if not dm:
        return None
    try:
        d = _date(2018 + int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
        return d.isoformat()
    except ValueError:
        return None


def _rejoin_split_dates(text: str) -> str:
    """PDFテキスト抽出で行をまたいで分割された令和日付を結合する。

    「令和\\n８年９月」→「令和８年９月」
    「12 時 00\\n分」→「12 時 00 分」
    """
    # 「令和」で終わる行と次行の「X年」を結合
    text = re.sub(r"令和\s*\n\s*(?=[０-９\d])", "令和", text)
    # 「XX 時 YY」で終わる行と次行の「分」を結合
    text = re.sub(r"(\d{1,2}\s*時\s*\d{1,2})\s*\n\s*分", r"\1 分", text)
    return text


def _clean_table_text(text: str) -> str:
    """別表のPDFテキストからアーティファクトを除去する。

    「（２）」のような節番号参照や余分な空白を潰し、
    分断された令和日付を結合できるようにする。
    """
    # 「（１）」〜「（99）」のような節番号参照を除去
    text = re.sub(r"（[０-９0-9]{1,2}）", " ", text)
    # PDFの行折り返しで「令和」と「X年」の間に文字が挟まるケースを修復
    # 「令和 付期間 ８年」→「令和８年」
    text = re.sub(
        r"令和\s+[^\d０-９]*?([０-９\d]{1,2}\s*年)",
        r"令和\1",
        text,
    )
    # 連続する空白を1つに
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _find_entry_block(lines: list[str], start: int) -> str:
    """別表の1エントリ分のテキストブロックを取り出す。

    次の「．」付き節番号が出るまでを1ブロックとする。
    PDFアーティファクトを除去して日付パターンを正しくマッチさせる。
    """
    block_lines = [lines[start]]
    for j in range(start + 1, min(start + 12, len(lines))):
        line = lines[j].strip()
        # 次のセクション番号（例: "４．入札手続等"）が来たら終了
        if re.match(r"[０-９0-9]{1,2}[．.]", line):
            break
        block_lines.append(lines[j])
    return _clean_table_text(" ".join(block_lines))


def extract_bid_schedule(text: str) -> list[dict]:
    """公告テキストから手続きスケジュール（別表）を抽出する。

    Returns:
        [{"label": "入札の締切", "datetime": "2026-09-10T12:00",
          "detail": "電子入札システムで提出"}, ...]
    """
    if not text:
        return []

    text = _rejoin_split_dates(text)
    lines = text.splitlines()
    schedule = []
    seen_labels = set()

    # 「期間」を含むラベルは範囲（から〜まで）で最後の日付を取る
    _RANGE_LABELS = {"入札説明書の交付・受付期限", "歩掛見積参考資料の交付期限"}

    for keyword, label in _SCHEDULE_KEYS:
        if label in seen_labels:
            continue
        pattern = re.compile(keyword)
        for i, line in enumerate(lines):
            if not pattern.search(line):
                continue
            # このキーワードの1エントリ分のブロックを取得
            block = _find_entry_block(lines, i)

            dates = list(_REIWA_DATE.finditer(block))
            if not dates:
                continue

            # 範囲（から〜まで）の場合は最後の日付、単一イベントは最初の日付
            target_match = dates[-1] if label in _RANGE_LABELS else dates[0]
            after_target = block[target_match.start():]

            # 日付の直後に時刻があればそれを使う
            dt = _parse_reiwa_datetime(after_target)

            # 直後に時刻がない場合、「最終日はXX時YY分まで」を探す
            if dt and "T" not in dt and "最終日" in block:
                final_day_idx = block.index("最終日")
                time_m = _TIME_HM.search(block[final_day_idx:])
                if time_m:
                    raw_t = time_m.group().translate(_ZENKAKU_NUM)
                    raw_t = re.sub(r"\s+", "", raw_t)
                    tm = re.match(r"(\d+)時(\d+)分", raw_t)
                    if tm:
                        dt = f"{dt}T{int(tm.group(1)):02d}:{int(tm.group(2)):02d}"

            if not dt:
                dt = _parse_reiwa_date_only(after_target)
            if not dt:
                continue

            # 補足情報
            detail = ""
            if "電子入札" in block:
                detail = "電子入札システム"
            if "最終日" in block:
                time_m = _TIME_HM.search(block[block.index("最終日"):])
                if time_m:
                    raw_t = time_m.group().translate(_ZENKAKU_NUM)
                    raw_t = re.sub(r"\s+", "", raw_t)
                    suffix = f"最終日は{raw_t}まで"
                    detail = f"{detail}（{suffix}）" if detail else suffix

            schedule.append({
                "label": label,
                "datetime": dt,
                "detail": detail,
            })
            seen_labels.add(label)
            break

    return schedule


def extract_deadline_from_schedule(schedule: list[dict]) -> str | None:
    """スケジュールから入札期限（申請書の受付期限）を返す。

    優先順位: 申請書の受付期限 > 入札の締切 > その他の受付期限
    """
    # 申請書の受付期限が最も重要（これを過ぎると参加できない）
    for item in schedule:
        if "申請書" in item["label"]:
            return item["datetime"]
    for item in schedule:
        if item["label"] == "入札の締切":
            return item["datetime"]
    for item in schedule:
        if "受付" in item["label"]:
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
