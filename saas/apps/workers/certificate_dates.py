"""資格証から、取得日と有効期限を読み取る（ADR-0095・ADR-0096）。

資格証には「交付年月日」「修了年月日」「有効期限」が書かれている。読み方は2段。

1. PDF に入っている文字を読む（文字で作られた証明書）
2. 文字が無ければ画像にして OCR で読む（台紙ごとスキャンした証明書。ADR-0096）

間違った日付を入れないことを優先する。

- 生年月日は取得日にしない（資格証は生年月日と交付日が近くに並ぶ）
- OCR は読み方を変えて3通り試し、**多数決**で決める。割れたら「読めなかった」とする
- どちらでも読めなければ空のままにし、CSV（有効期限.csv）か画面から人が入れる
"""

from __future__ import annotations

import calendar
import datetime
import logging
import re
import unicodedata
from collections import Counter

logger = logging.getLogger(__name__)

# 見出し。この語の後ろに続く日付を拾う
ACQUIRED_LABELS = (
    "交付年月日", "交付日", "交付", "修了年月日", "修了日",
    "認定年月日", "取得年月日", "取得日", "合格年月日",
)
# 「期限」だけでも拾う。OCR は「有効期限」を「交効期限」のように崩すことがある
EXPIRY_LABELS = ("有効期限", "有効期間", "まで有効", "期限")

# 取り違えると困る見出し。この後ろの日付は取得日にしない
_IGNORE_LABELS = ("生年月日", "生 年 月 日")

# 元号と、その元年に当たる西暦
_ERAS = {"令和": 2018, "平成": 1988, "昭和": 1925}

# 「令和8年7月30日」「平成23年7月25日」。
# OCR は「日」を落とすことがあるので、月の直後の数字は日として読む
_WAREKI = re.compile(
    r"(令和|平成|昭和)\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s{0,2}(?:(\d{1,2})\s*日?)?",
)
# 「2029年3月31日」「2029年7月」。運転免許証の「2030年(令和12年)04月09日」のように、
# 年と月の間に元号の言い換えが挟まる書き方も読む
_SEIREKI_KANJI = re.compile(
    r"(\d{4})\s*年\s*(?:[(（][^)）]{0,12}[)）]\s*)?(\d{1,2})\s*月\s{0,2}"
    r"(?:(\d{1,2})\s*日?)?",
)
# 「2031.03.31」「2031/03/31」「2031-03-31」
_SEIREKI_MARK = re.compile(r"(\d{4})[./-](\d{1,2})(?:[./-](\d{1,2}))?")

# 見出しから何文字先までを見るか。カードは項目が近くに並んでいる
_WINDOW = 30

# 何ページ目まで見るか。資格証は表・裏の2枚で足りる
_MAX_PAGES = 2
# OCR の読み方。カードの作りによって当たり外れがあるので何通りか試す。
# (画像の細かさ, 拡大率, tesseract のページ解析モード)
_OCR_VARIANTS = (
    (400, 1.5, "--psm 6"),
    (400, 1.5, "--psm 4"),
    (300, 1.0, ""),
)

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
    """資格証から (取得日, 有効期限) を読み取る。

    まず PDF に入っている文字を読む。台紙ごとスキャンした資格証は文字を持たないので、
    画像にして OCR で読む（ADR-0096）。どちらでも読めなければ (None, None)。

    Args:
        source: パス、またはファイルのように読めるもの
    """
    acquired, expiry = parse_dates_from_text(_pdf_text(source))
    if acquired or expiry:
        return acquired, expiry
    return _ocr_dates(source)


def _ocr_dates(source):
    """OCR で読む。読み方を変えて何度か試し、**食い違ったら採らない**。

    OCR は数字を1文字読み違えることがある（2028 を 2026 と読むなど）。
    間違った期限が入ると、期限切れの警告が狂って気づけなくなる。
    そこで、読めた値がすべて同じときだけ採用する。
    """
    results = [parse_dates_from_text(text) for text in ocr_texts(source)]
    return _agree([r[0] for r in results]), _agree([r[1] for r in results])


def _agree(values):
    """読めた値のうち、いちばん多かったものを返す。

    同数で割れたときは None（読めなかった扱い）。OCR は1文字読み違えることがあるので、
    1つの読み方だけを信じない。
    """
    found = [value for value in values if value is not None]
    if not found:
        return None
    counts = Counter(found).most_common()
    if len(counts) > 1 and counts[0][1] == counts[1][1]:
        return None
    return counts[0][0]


def _pdf_text(source) -> str:
    """PDF に入っている文字。画像だけの PDF では空になる。"""
    if not _is_pdf(source):
        return ""
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - 依存が入っていない環境向け
        return ""

    try:
        if hasattr(source, "seek"):
            source.seek(0)
        with pdfplumber.open(source) as pdf:
            return "\n".join(
                page.extract_text() or "" for page in pdf.pages[:_MAX_PAGES]
            )
    except Exception:
        logger.info("資格証の PDF を読めませんでした", exc_info=True)
        return ""
    finally:
        if hasattr(source, "seek"):
            source.seek(0)


def _is_pdf(source) -> bool:
    name = getattr(source, "name", None) or str(source)
    return str(name).lower().endswith(".pdf")


def ocr_texts(source):
    """画像の資格証を文字にする。読み方を変えた分だけ返す（ADR-0096）。

    tesseract が入っていない環境では空の並びを返す。OCR が無くても取り込みは動く。
    """
    from django.conf import settings

    if not getattr(settings, "CERTIFICATE_OCR_ENABLED", True):
        return []

    try:
        import pytesseract
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover - 依存が入っていない環境向け
        return []

    command = getattr(settings, "TESSERACT_CMD", "")
    if command:
        pytesseract.pytesseract.tesseract_cmd = command
    language = getattr(settings, "TESSERACT_LANG", "jpn")

    found = []
    for resolution, scale, config in _OCR_VARIANTS:
        try:
            if hasattr(source, "seek"):
                source.seek(0)
            images = (
                _pdf_images(source, resolution) if _is_pdf(source)
                else [Image.open(source)]
            )

            text = []
            for image in images:
                prepared = ImageOps.autocontrast(ImageOps.grayscale(image))
                if scale != 1.0:
                    prepared = prepared.resize(
                        (int(prepared.width * scale), int(prepared.height * scale)),
                        Image.LANCZOS,
                    )
                text.append(
                    pytesseract.image_to_string(prepared, lang=language, config=config),
                )
            found.append("\n".join(text))
        except Exception:
            logger.info("資格証を OCR で読めませんでした", exc_info=True)
        finally:
            if hasattr(source, "seek"):
                source.seek(0)
    return found


def _pdf_images(source, resolution):
    """PDF のページを画像にする。カードの文字は小さいので細かめに描く。"""
    import pdfplumber

    with pdfplumber.open(source) as pdf:
        return [
            page.to_image(resolution=resolution).original
            for page in pdf.pages[:_MAX_PAGES]
        ]
