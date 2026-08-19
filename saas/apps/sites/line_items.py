"""見積ファイルから明細行（材料・数量・単価）を抽出する。

importer.py が拾うのは見出し部（件名・宛名・合計金額など）だけで、明細行は
意図的に捨てている（ラベル/値の組を探す走査では、数量や単価がノイズになって
見出しが読めなくなるため）。こちらは逆に**明細だけ**を対象にする。

読み取りの考え方:

- **列位置は決め打ちしない。** ヘッダ行を探して「名称はこの列、数量はこの列」と
  対応付けてから本文を読む。ライデンの書き出しも見積書 PDF も版で列が動く。
- **ヘッダ行が見つからなければ何も返さない。** 推測で数字を拾うと、金額が
  1桁ずれた明細が黙って登録される。空で返して人に入力してもらうほうが安全。
- **合計行は明細ではない。** 「小計」「合計」「消費税」に当たったらそこで打ち切る。
  同じ表の下に付いてくる集計を明細として登録しないため。
- LLM は使わない。見積書の明細は表形式が保たれているので決定論的に読める。
  ADR-0010 でいう層0で片が付く範囲（labor_table.py と同じ判断）。

    from apps.sites.line_items import parse_estimate_lines
    lines = parse_estimate_lines(path, ".xlsx")
"""
from __future__ import annotations

import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

from apps.sites.importer import read_rows

# 列の意味とヘッダ表記の候補。実ファイルで表記が違っていたらここに足す。
COLUMN_LABELS: dict[str, tuple[str, ...]] = {
    "name": (
        "名称", "品名", "材料名", "品目", "商品名", "工事内容", "内容",
        "摘要", "名称・規格", "品名・規格", "工事名称", "項目",
    ),
    "spec": (
        "規格", "仕様", "型番", "品番", "規格・寸法", "サイズ", "メーカー",
    ),
    "quantity": ("数量", "員数", "数", "数 量"),
    "unit": ("単位", "単 位"),
    "unit_price": ("単価", "単 価", "見積単価", "定価"),
    "amount": ("金額", "見積金額", "小計金額"),
    "remarks": ("備考", "摘要欄", "note"),
}

# 明細として成立する最小条件。名称に加えてこのどれかが要る。
_VALUE_COLUMNS = ("quantity", "unit_price", "amount")

# ここに当たったら明細は終わり。集計行を明細として登録しないための打ち切り。
_TOTAL_MARKERS = (
    "小計", "合計", "総計", "計", "消費税", "税抜", "税込", "値引",
    "諸経費", "出精値引",
)

# ヘッダ探索の打ち切り。これより下にヘッダがある見積書は想定しない。
MAX_HEADER_SCAN_ROWS = 200

# 1ファイルから取り込む明細の上限。桁違いの行数は読み違いを疑う。
MAX_LINES = 500

# 名称がこれより長いものは明細ではなく文章を掴んでいる。
MAX_NAME_LENGTH = 200


def _nfkc(text) -> str:
    """全角/半角と空白のゆれを吸収する。importer と同じ正規化にそろえる。"""
    if text is None:
        return ""
    return unicodedata.normalize("NFKC", str(text)).strip()


def _key(text) -> str:
    """ヘッダ照合用のキー。空白と記号を落として比較する。"""
    return re.sub(r"[\s　・:：]", "", _nfkc(text)).lower()


def _to_decimal(text) -> Decimal | None:
    """「1,200」「¥1,200」「1200円」「3.5」を Decimal にする。読めなければ None。"""
    raw = _nfkc(text)
    if not raw:
        return None
    # 通貨記号・単位・桁区切りを落とす。小数点と符号だけ残す。
    cleaned = re.sub(r"[^\d.\-]", "", raw.replace(",", ""))
    if not cleaned or cleaned in ("-", ".", "-."):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _is_total_row(cells: list[str]) -> bool:
    """集計行か。

    部分一致では拾いすぎる。「一式計上」「設計変更」には「計」が含まれるが
    集計行ではない。**完全一致か、2文字以上の語で始まる場合**だけ集計とみなす。
    「合計金額」「消費税10%」は拾い、「一式計上」は拾わない。
    """
    for cell in cells[:3]:
        key = _key(cell)
        if not key:
            continue
        for marker in _TOTAL_MARKERS:
            marker_key = _key(marker)
            if key == marker_key:
                return True
            if len(marker_key) >= 2 and key.startswith(marker_key):
                return True
    return False


def detect_header(rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    """ヘッダ行を探して (行番号, {列の意味: 列番号}) を返す。無ければ None。

    「名称に当たる列」と「数量・単価・金額のいずれか」が両方ある行だけを
    ヘッダとみなす。項目名が1つ当たっただけの行を拾うと、見出し部の
    「工事名称」などをヘッダと誤認する。
    """
    for r, row in enumerate(rows[:MAX_HEADER_SCAN_ROWS]):
        mapping: dict[str, int] = {}
        for c, cell in enumerate(row):
            key = _key(cell)
            if not key:
                continue
            for field, variants in COLUMN_LABELS.items():
                if field in mapping:
                    continue
                if any(key == _key(v) for v in variants):
                    mapping[field] = c
                    break
        if "name" in mapping and any(f in mapping for f in _VALUE_COLUMNS):
            return r, mapping
    return None


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return _nfkc(row[index])


def extract_lines(rows: list[list[str]]) -> list[dict]:
    """行の二次元リストから明細を抽出する。ヘッダが無ければ空リスト。"""
    found = detect_header(rows)
    if found is None:
        return []
    header_row, columns = found

    lines: list[dict] = []
    blank_streak = 0

    for row in rows[header_row + 1:]:
        if len(lines) >= MAX_LINES:
            break

        cells = [_nfkc(c) for c in row]
        if not any(cells):
            # 表の途中の空行では止めない。ページ跨ぎで空行が入る PDF がある。
            blank_streak += 1
            if blank_streak >= 3:
                break
            continue
        blank_streak = 0

        if _is_total_row(cells):
            break

        name = _cell(row, columns.get("name"))
        if not name or len(name) > MAX_NAME_LENGTH:
            continue

        quantity = _to_decimal(_cell(row, columns.get("quantity")))
        unit_price = _to_decimal(_cell(row, columns.get("unit_price")))
        amount = _to_decimal(_cell(row, columns.get("amount")))

        # 名称だけの行は小見出し（「1. 電気設備工事」等）。明細ではない。
        if quantity is None and unit_price is None and amount is None:
            continue

        # 金額が空なら数量×単価で補う。逆は補わない（単価を割り戻すと
        # 端数処理で元の単価と変わることがあり、根拠のない数字になる）。
        if amount is None and quantity is not None and unit_price is not None:
            amount = quantity * unit_price

        lines.append({
            "name": name,
            "spec": _cell(row, columns.get("spec")),
            "unit": _cell(row, columns.get("unit")),
            "quantity": quantity,
            "unit_price": unit_price,
            "amount": amount,
            "remarks": _cell(row, columns.get("remarks")),
        })

    return lines


def parse_estimate_lines(filepath: str | Path, suffix: str) -> list[dict]:
    """見積ファイルを読んで明細のリストを返す。

    見出し項目の読み取り（importer.parse_estimate_file）とは独立して呼べる。
    ヘッダ行を判別できなければ空リストを返す（例外は投げない）。
    """
    return extract_lines(read_rows(filepath, suffix))


# ---------------------------------------------------------------------------
# 確認画面との往復
# ---------------------------------------------------------------------------
#
# 確認画面を挟むため、読み取った明細は一度ブラウザへ渡して戻ってくる。
# アップロードしたファイルは確認時にはもう手元に無いので、読み直せない。


def serialize_lines(lines: list[dict]) -> str:
    """明細を hidden 項目に載せる JSON にする。Decimal は文字列で持つ。"""
    return json.dumps([
        {
            "name": line.get("name") or "",
            "spec": line.get("spec") or "",
            "unit": line.get("unit") or "",
            "quantity": _decimal_str(line.get("quantity")),
            "unit_price": _decimal_str(line.get("unit_price")),
            "amount": _decimal_str(line.get("amount")),
            "remarks": line.get("remarks") or "",
        }
        for line in lines
    ], ensure_ascii=False)


def _decimal_str(value) -> str:
    return "" if value is None else str(value)


def deserialize_lines(raw: str) -> list[dict]:
    """hidden 項目の JSON を明細に戻す。壊れていれば空リスト。

    **ブラウザから戻ってきた値なので、ここで必ず検証し直す。** 件数と
    文字数を読み取り時と同じ上限で切り、数値は Decimal に通し直す。
    材料マスタの引き当ては**ここではやらない** — pk を持ち回ると他社の
    材料を指す値を送られたときに紐づいてしまうので、名称から
    サーバ側で引き直す（materials.services.match_lines_to_materials）。
    """
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(payload, list):
        return []

    lines: list[dict] = []
    for entry in payload[:MAX_LINES]:
        if not isinstance(entry, dict):
            continue
        name = _nfkc(entry.get("name"))[:MAX_NAME_LENGTH]
        if not name:
            continue
        lines.append({
            "name": name,
            "spec": _nfkc(entry.get("spec"))[:300],
            "unit": _nfkc(entry.get("unit"))[:50],
            "quantity": _to_decimal(entry.get("quantity")),
            "unit_price": _to_decimal(entry.get("unit_price")),
            "amount": _to_decimal(entry.get("amount")),
            "remarks": _nfkc(entry.get("remarks"))[:300],
        })
    return lines
