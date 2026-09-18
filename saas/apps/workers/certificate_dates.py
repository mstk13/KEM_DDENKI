"""資格証の PDF から、取得日と有効期限を読み取る（ADR-0095）。

資格証には「交付年月日」「修了年月日」「有効期限」が書かれている。
PDF に文字が入っていれば、そこから日付を拾って保有資格に入れる。

読み取れるのは**文字が入っている PDF** だけである。台紙ごとスキャンした
画像の PDF（今ある資格書一覧のほとんど）は文字を持たないので読み取れない。
その場合は日付を空のままにし、これまでどおり CSV（有効期限.csv）で渡すか、
画面から手で入れる。

生年月日を取得日と取り違えないよう、日付は**見出しの直後にあるもの**だけを拾う。
"""

from __future__ import annotations

import calendar
import datetime
import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# 見出し。この語の後ろに続く日付を拾う
ACQUIRED_LABELS = (
    "交付年月日", "交付日", "交付", "修了年月日", "修了日",
    "認定年月日", "取得年月日", "取得日", "合格年月日",
)
EXPIRY_LABELS = ("有効期限", "有効期間", "まで有効")

# 取り違えると困る見出し。この後ろの日付は取得日にしない
_IGNORE_LABELS = ("生年月日", "生 年 月 日")

# 元号と、その元年に当たる西暦
_ERAS = {"令和": 2018, "平成": 1988, "昭和": 1925}

# 「令和8年7月30日」「平成23年7月25日」
_WAREKI = re.compile(
    r"(令和|平成|昭和)\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?",
)
# 「2029年3月31日」「2029年7月」。運転免許証の「2030年(令和12年)04月09日」のように、
# 年と月の間に元号の言い換えが挟まる書き方も読む
_SEIREKI_KANJI = re.compile(
    r"(\d{4})\s*年\s*(?:[(（][^)）]{0,12}[)）]\s*)?(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?",
)
# 「2031.03.31」「2031/03/31」「2031-03-31」
_SEIREKI_MARK = re.compile(r"(\d{4})[./-](\d{1,2})(?:[./-](\d{1,2}))?")

# 見出しから何文字先までを見るか。カードは項目が近くに並んでいる
_WINDOW = 30

# 生年月日の見出しと、その直後の日付
_BIRTHDAY = re.compile(
    r"(?:生年月日|生\s*年\s*月\s*日)\s*"
    r"(?:(?:令和|平成|昭和)\s*\d{1,2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日?生?"
    r"|\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日?生?"
    r"|\d{4}[./-]\d{1,2}[./-]\d{1,2})",
)


def _drop_birthdays(text: str) -> str:
    """生年月日の見出しと日付を落とす。ほかの日付には触らない。"""
    return _BIRTHDAY.sub(" ", text)


def _to_date(year: int, month: int, day: int | None):
    """日が書かれていなければ月末にする（「有効期限 2028年7月」のような書き方）。"""
    if not (1 <= month <= 12):
        return None
    if day is None:
        day = calendar.monthrange(year, month)[1]
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def _first_date(text: str):
    """文字列の先頭付近にある日付。和暦・西暦のどちらでも。"""
    candidates = []

    match = _WAREKI.search(text)
    if match:
        era, year, month, day = match.groups()
        candidates.append((
            match.start(),
            _to_date(_ERAS[era] + int(year), int(month), int(day) if day else None),
        ))

    match = _SEIREKI_KANJI.search(text)
    if match:
        year, month, day = match.groups()
        candidates.append((
            match.start(), _to_date(int(year), int(month), int(day) if day else None),
        ))

    match = _SEIREKI_MARK.search(text)
    if match:
        year, month, day = match.groups()
        candidates.append((
            match.start(), _to_date(int(year), int(month), int(day) if day else None),
        ))

    candidates = [(at, value) for at, value in candidates if value is not None]
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def _all_dates(text: str):
    """文字列に出てくる日付を、出た順に返す。"""
    found = []
    for pattern, wareki in (
        (_WAREKI, True), (_SEIREKI_KANJI, False), (_SEIREKI_MARK, False),
    ):
        for match in pattern.finditer(text):
            groups = match.groups()
            if wareki:
                era, year, month, day = groups
                value = _to_date(
                    _ERAS[era] + int(year), int(month), int(day) if day else None,
                )
            else:
                year, month, day = groups
                value = _to_date(int(year), int(month), int(day) if day else None)
            if value is not None:
                found.append((match.start(), value))
    found.sort()
    return [value for _at, value in found]


def _find(text: str, labels, *, latest=False):
    """見出しの直後にある日付。

    latest=True なら、見出しが何度も出てくるときに**新しいほうの日付**を選ぶ
    （監理技術者資格者証の「初回交付」と「交付」のような並び）。
    """
    found = []
    for label in labels:
        at = text.find(label)
        while at != -1:
            value = _first_date(text[at + len(label): at + len(label) + _WINDOW])
            if value is not None:
                found.append(value)
            at = text.find(label, at + 1)
        if found and not latest:
            return found[0]
    if not found:
        return None
    return max(found) if latest else found[0]


def parse_dates_from_text(text: str):
    """資格証の文面から (取得日, 有効期限) を読み取る。

    読み取れなかったものは None。
    """
    if not text:
        return None, None

    flat = unicodedata.normalize("NFKC", text)
    # 生年月日は取得日と間違えやすいので、見出しとその直後の日付だけ落とす
    flat = _drop_birthdays(flat)

    expiry = _find(flat, EXPIRY_LABELS)
    if expiry is None:
        # 「2030年(令和12年)04月09日まで有効」「令和13年8月23日まで有効」のような書き方。
        # 直前に元号の言い換えが入ることがあるので、いちばん後ろの日付を使う
        match = re.search(r"(.{0,40}?)まで有効", flat)
        if match:
            dates = _all_dates(match.group(1))
            expiry = dates[-1] if dates else None

    acquired = _find(flat, ACQUIRED_LABELS, latest=True)
    if acquired is not None and expiry is not None and acquired == expiry:
        acquired = None
    return acquired, expiry


def read_dates_from_pdf(source):
    """PDF から (取得日, 有効期限) を読み取る。文字が無ければ (None, None)。

    Args:
        source: パス、またはファイルのように読めるもの
    """
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - 依存が入っていない環境向け
        return None, None

    try:
        if hasattr(source, "seek"):
            source.seek(0)
        with pdfplumber.open(source) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages[:3])
    except Exception:
        logger.info("資格証の PDF を読めませんでした", exc_info=True)
        return None, None
    finally:
        if hasattr(source, "seek"):
            source.seek(0)

    return parse_dates_from_text(text)
