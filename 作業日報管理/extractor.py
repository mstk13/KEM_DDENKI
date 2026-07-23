"""作業日報テキストからの自動抽出エンジン。

入力された日報(自由記述・メール・LINE転記・音声入力の書き起こし等)を解析し、
日付 / 現場名 / 社員名 / 出勤時刻 / 退勤時刻 / 休憩 / 作業内容 / 備考 を抽出する。

対応フォーマット例::

    2026/07/21(火) 現場: A様邸 新築工事
    作業内容: 1F配線工事、分電盤取付
    田中太郎 7:30〜19:00 休憩60分
    佐藤花子 出勤 8:00 退勤 17:00
    備考: 材料追加発注あり

    ---
    7月22日 現場:B工場 改修
    作業員: 田中太郎、鈴木一郎
    8:00-20:30 休憩1時間
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

# --- 正規表現パーツ -------------------------------------------------------
# ':' 形式か '時' 形式のどちらかを必須にして、単なる数値の誤検出を防ぐ
_TIME = r"(?:[0-2]?\d)(?:\s*[:：]\s*\d{1,2}|\s*時\s*(?:\d{1,2}\s*分?)?)"
_DASH = r"[~〜～\-‐‑–—―ー－]|から|より"

RE_TIME_RANGE = re.compile(rf"({_TIME})\s*(?:{_DASH})\s*({_TIME})")
RE_TIME_IN = re.compile(rf"(?:出勤|始業|開始|入場|IN|in)\s*(?:時刻)?\s*[:：]?\s*({_TIME})")
RE_TIME_OUT = re.compile(rf"(?:退勤|終業|終了|退場|OUT|out)\s*(?:時刻)?\s*[:：]?\s*({_TIME})")
RE_ANY_TIME = re.compile(_TIME)

RE_BREAK = re.compile(
    r"(?:休憩|休息)\s*(?:時間)?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(時間|時|分|h|H|min|m)?"
)
RE_BREAK_NONE = re.compile(r"休憩\s*[:：]?\s*(?:なし|無し|無|0)")

# 現場名は日付と同じ行に書かれることが多いため、行頭固定にしない
RE_LABEL_SITE = re.compile(r"(?:現場名?|工事名|物件名?|作業場所|工事場所|場所)\s*[:：]\s*(.+)$")
RE_LABEL_CONTENT = re.compile(r"^\s*(?:作業内容|業務内容|作業|内容|工事内容)\s*[:：]\s*(.+)$")
RE_LABEL_NOTE = re.compile(r"^\s*(?:備考|特記事項|特記|連絡事項|申し送り)\s*[:：]\s*(.+)$")
RE_LABEL_WORKERS = re.compile(r"^\s*(?:作業員|作業者|社員|従業員|出勤者|担当者?|氏名|名前|メンバー)\s*[:：]\s*(.+)$")
RE_LABEL_DATE = re.compile(r"^\s*(?:日付|年月日|作業日|日時)\s*[:：]\s*(.+)$")

RE_DATE_YMD = re.compile(r"(\d{4})\s*[/\-年\.]\s*(\d{1,2})\s*[/\-月\.]\s*(\d{1,2})\s*日?")
RE_DATE_MD = re.compile(r"(?<!\d)(\d{1,2})\s*[/\-月]\s*(\d{1,2})\s*日?(?!\d)")
RE_DATE_WAREKI = re.compile(r"(令和|R|r)\s*(\d{1,2})\s*[年\.\-/]\s*(\d{1,2})\s*[月\.\-/]\s*(\d{1,2})\s*日?")

RE_SEPARATOR = re.compile(r"^\s*(?:[-=＝*＊_〜~─━■□◆◇#]{3,}|【[^】]*】)\s*$")

# 名前の前後から取り除く飾り
RE_NAME_PREFIX = re.compile(r"^[\s　\d]*[.)．）、,・\-*●○■□◆◇▲△>＞]*\s*")
RE_NAME_LABEL = re.compile(r"(?:氏名|名前|作業員|作業者|社員|従業員|担当者|担当|出勤者)\s*[:：]?\s*")
NAME_SPLIT = re.compile(r"[、,，/／・&＆\+]|\sと\s")

_NOISE_WORDS = {
    "現場", "作業", "内容", "備考", "合計", "計", "以上", "報告", "日報", "作業日報",
    "天気", "天候", "出勤", "退勤", "休憩", "残業", "早朝", "時間", "本日", "明日",
}


def normalize(text: str) -> str:
    """全角英数・記号を半角に寄せ、表記ゆれを吸収する。"""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("〜", "~").replace("～", "~")
    return t


def _to_hhmm(token: str) -> str:
    """'7:30' '7時30分' '07：5' → 'HH:MM'。"""
    if not token:
        return ""
    t = normalize(token).strip()
    m = re.match(r"^(\d{1,2})\s*[:：]\s*(\d{1,2})$", t)
    if not m:
        m = re.match(r"^(\d{1,2})\s*時\s*(\d{1,2})?\s*分?$", t)
    if not m:
        return ""
    h = int(m.group(1))
    mi = int(m.group(2) or 0)
    if not (0 <= h <= 47 and 0 <= mi <= 59):
        return ""
    return f"{h:02d}:{mi:02d}"


def _parse_break(line: str) -> int | None:
    """行から休憩時間(分)を抽出。記載なしは None。"""
    if RE_BREAK_NONE.search(line):
        return 0
    m = RE_BREAK.search(line)
    if not m:
        return None
    value = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit in ("時間", "時", "h"):
        return int(round(value * 60))
    if unit in ("分", "min", "m"):
        return int(round(value))
    # 単位省略: 3以下なら時間、それ以上は分とみなす
    return int(round(value * 60)) if value <= 3 else int(round(value))


def _find_date(text: str, default_year: int | None = None) -> tuple[str, int, int]:
    """テキスト中の最初の日付を ('YYYY-MM-DD', 開始位置, 終了位置) で返す。"""
    year = default_year or date.today().year
    m = RE_DATE_WAREKI.search(text)
    if m:
        try:  # 令和1年 = 2019
            iso = date(2018 + int(m.group(2)), int(m.group(3)), int(m.group(4))).isoformat()
            return iso, m.start(), m.end()
        except ValueError:
            pass
    m = RE_DATE_YMD.search(text)
    if m:
        try:
            iso = date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
            return iso, m.start(), m.end()
        except ValueError:
            pass
    m = RE_DATE_MD.search(text)
    if m:
        try:
            iso = date(year, int(m.group(1)), int(m.group(2))).isoformat()
            return iso, m.start(), m.end()
        except ValueError:
            pass
    return "", -1, -1


def _parse_date(text: str, default_year: int | None = None) -> str:
    """テキストから最初に見つかった日付を 'YYYY-MM-DD' で返す。"""
    return _find_date(text, default_year)[0]


def _strip_date(text: str, default_year: int | None = None) -> str:
    """行から日付表記(と直後の曜日)を取り除いた残りを返す。"""
    iso, s, e = _find_date(text, default_year)
    if not iso:
        return text
    rest = text[e:]
    rest = re.sub(r"^\s*[(\[]?\s*[月火水木金土日]\s*曜?日?\s*[)\]]?", "", rest)
    return (text[:s] + " " + rest).strip(" 　:：|/\t")


def _clean_name(raw: str) -> str:
    name = RE_NAME_PREFIX.sub("", normalize(raw))
    name = RE_NAME_LABEL.sub("", name)
    name = re.sub(r"[(（\[][^)）\]]*[)）\]]", "", name)          # (職長) などを除去
    name = re.sub(r"(さん|サン|君|くん|氏|様)$", "", name.strip())
    name = name.strip(" 　:：|/\\\t.,、。-")
    if not name or len(name) > 20:
        return ""
    if name in _NOISE_WORDS or name.isdigit():
        return ""
    if re.fullmatch(r"[\d\W_]+", name):
        return ""
    return re.sub(r"[ 　]+", " ", name)


def _split_names(raw: str) -> list[str]:
    parts = [p for p in NAME_SPLIT.split(raw) if p and p.strip()]
    names = []
    for p in parts:
        n = _clean_name(p)
        if n and n not in names:
            names.append(n)
    return names


def split_blocks(text: str) -> list[str]:
    """テキストを日報1件ごとのブロックに分割する。

    区切りは (1)'---' 等のセパレータ行 (2)空行 (3)行頭の日付。
    """
    lines = normalize(text).split("\n")
    blocks: list[list[str]] = []
    current: list[str] = []

    def flush():
        if any(l.strip() for l in current):
            blocks.append(list(current))
        current.clear()

    for line in lines:
        stripped = line.strip()
        if RE_SEPARATOR.match(stripped):
            flush()
            continue
        if not stripped:
            flush()
            continue
        # 行頭が日付 かつ すでに時刻行を含むブロック → 新しい日報とみなす
        head_date = _parse_date(stripped[:14])
        starts_with_date = bool(head_date) and (
            RE_DATE_YMD.match(stripped) or RE_DATE_MD.match(stripped)
            or RE_DATE_WAREKI.match(stripped) or RE_LABEL_DATE.match(stripped)
        )
        if starts_with_date and any(RE_ANY_TIME.search(l) for l in current):
            flush()
        current.append(line)
    flush()
    return ["\n".join(b) for b in blocks]


def parse_block(block: str, default_year: int | None = None) -> dict:
    """日報ブロック1件を解析して構造化する。"""
    lines = [l for l in block.split("\n") if l.strip()]
    header = {"date": "", "site": "", "content": "", "note": "", "raw": block}
    block_break: int | None = None
    pending_names: list[str] = []
    entries: list[dict] = []
    warnings: list[str] = []
    content_parts: list[str] = []
    note_parts: list[str] = []

    for line in lines:
        text = line.strip()

        # 1) 日付(「日付:」ラベル / 行中の日付表記)。同じ行の残りは続けて解析する
        m = RE_LABEL_DATE.match(text)
        if m:
            if not header["date"]:
                header["date"] = _parse_date(m.group(1), default_year)
            text = _strip_date(m.group(1), default_year).strip()
        elif not header["date"]:
            tm = RE_ANY_TIME.search(text)
            scan = text[: tm.start()] if tm else text
            iso = _parse_date(scan, default_year)
            if iso:
                header["date"] = iso
                text = (_strip_date(scan, default_year) + " " + text[len(scan):]).strip()
        if not text:
            continue

        # 2) ラベル付き項目
        m = RE_LABEL_CONTENT.match(text)
        if m:
            content_parts.append(m.group(1).strip())
            continue
        m = RE_LABEL_NOTE.match(text)
        if m:
            note_parts.append(m.group(1).strip())
            continue
        m = RE_LABEL_SITE.search(text)
        if m:
            if not header["site"]:
                header["site"] = m.group(1).strip()
            text = text[: m.start()].strip(" 　:：|/\t")
            if not text:
                continue

        # 3) 時刻を含む行 → 勤怠行
        start = end = ""
        cut = len(text)
        rng = RE_TIME_RANGE.search(text)
        if rng:
            start, end = _to_hhmm(rng.group(1)), _to_hhmm(rng.group(2))
            cut = rng.start()
        else:
            m_in, m_out = RE_TIME_IN.search(text), RE_TIME_OUT.search(text)
            if m_in or m_out:
                start = _to_hhmm(m_in.group(1)) if m_in else ""
                end = _to_hhmm(m_out.group(1)) if m_out else ""
                cut = min(x.start() for x in (m_in, m_out) if x)

        line_break = _parse_break(text)

        if start or end:
            head = text[:cut]
            names = _split_names(head) or list(pending_names)
            if not names:
                names = [""]
                warnings.append(f"社員名を特定できませんでした: 「{text}」")
            for name in names:
                entries.append({
                    "name": name,
                    "start": start,
                    "end": end,
                    "break_minutes": line_break if line_break is not None else block_break,
                    "note": "",
                })
            if names and names != [""] and head.strip():
                pending_names = []
            continue

        # 作業員ラベル行(時刻なし) → 後続/ブロック時刻に紐づける
        m = RE_LABEL_WORKERS.match(text)
        if m:
            found = _split_names(m.group(1))
            if found:
                pending_names.extend(n for n in found if n not in pending_names)
                continue

        if line_break is not None and not entries:
            block_break = line_break
            continue
        if line_break is not None:
            block_break = line_break

        # 現場名がラベルなしで書かれているケース(先頭行など)
        if not header["site"] and re.search(r"(現場|工事|邸|ビル|工場|様方|マンション|倉庫|センター)", text):
            cleaned = re.sub(r"^(?:現場名?|工事名|物件名?)\s*", "", text).strip(" 　:：")
            if cleaned:
                header["site"] = cleaned
                continue

        content_parts.append(text)

    header["content"] = " / ".join(p for p in content_parts if p)
    header["note"] = " / ".join(p for p in note_parts if p)

    # 名前だけ判明していて勤怠行が無い場合も1件として拾う
    if not entries and pending_names:
        for name in pending_names:
            entries.append({"name": name, "start": "", "end": "",
                            "break_minutes": block_break, "note": ""})

    if not header["date"]:
        warnings.append("日付を抽出できませんでした")
    if not entries:
        warnings.append("勤怠情報(社員名・時刻)を抽出できませんでした")
    for e in entries:
        if not e["start"] or not e["end"]:
            warnings.append(f"出退勤時刻が不完全です: 「{e['name'] or '(氏名不明)'}」")

    header["entries"] = entries
    header["warnings"] = warnings
    return header


def extract(text: str, default_year: int | None = None) -> list[dict]:
    """日報テキスト全体を解析し、日報ブロックのリストを返す。"""
    if not text or not text.strip():
        return []
    return [parse_block(b, default_year) for b in split_blocks(text)]


def to_rows(blocks: list[dict]) -> list[dict]:
    """解析結果を「1行 = 社員 × 1日」のフラットな明細に変換する。"""
    rows: list[dict] = []
    for b in blocks:
        for e in b.get("entries", []):
            rows.append({
                "日付": b.get("date", ""),
                "現場名": b.get("site", ""),
                "社員名": e.get("name", ""),
                "出勤": e.get("start", ""),
                "退勤": e.get("end", ""),
                "休憩(分)": e.get("break_minutes"),
                "作業内容": b.get("content", ""),
                "備考": b.get("note", ""),
            })
    return rows


if __name__ == "__main__":  # 簡易動作確認
    sample = """
    2026/07/21(火) 現場: A様邸 新築工事
    作業内容: 1F配線工事、分電盤取付
    田中太郎 7:30〜19:00 休憩60分
    佐藤花子 出勤 8:00 退勤 17:00
    備考: 材料追加発注あり
    ---
    7月22日 現場:B工場 改修工事
    作業員: 田中太郎、鈴木一郎
    8:00-20:30 休憩1時間
    """
    for row in to_rows(extract(sample)):
        print(row)
