"""見積ファイル（ライデンの CSV / Excel / 見積書の PDF）から現場の初期値を読み取る。

CSV(.csv): cp932 → utf-8-sig → utf-8 の順に試す。ライデンの書き出しは CP932 の
ことが多いが、版や書き出し方で変わるため決め打ちしない。
Excel(.xlsx/.xlsm): openpyxl で全シートのセルを取り出す。
PDF(.pdf): pdfplumber で表とテキスト行を取り出し、CSV と同じ走査をかける。

見出し部は「ラベルのセル + 値のセル」で並ぶ。**列位置は版によって動くので
位置では拾わず、ラベル名で探す**。ラベルが見つからなければ None を返し、
確認画面で人が入力する前提とする。読み違えて登録するより空欄のほうが安全。

    from apps.sites.importer import parse_estimate_file
    data = parse_estimate_file(path, ".csv")
"""
from __future__ import annotations

import csv
import re
import unicodedata
from datetime import date
from pathlib import Path

# 拾いたい項目とラベルの候補。実ファイルで表記が違っていたらここに足す。
LABELS: dict[str, tuple[str, ...]] = {
    "code": (
        "見積番号", "見積no", "見積書番号", "見積書no", "御見積番号",
        "御見積no", "見積書き番号", "文書番号", "伝票番号",
    ),
    "name": (
        "件名", "工事件名", "工事名", "工事名称", "物件名", "現場名", "工事内容",
    ),
    "payment_terms": (
        "支払条件", "お支払条件", "お支払い条件", "御支払条件", "御支払い条件",
        "支払方法", "お支払方法", "お支払い方法", "支払期日", "決済条件",
    ),
    "address": (
        "工事場所", "施工場所", "現場住所", "工事住所", "施工住所", "所在地",
    ),
    "amount": (
        "見積金額", "御見積金額", "お見積金額", "工事金額", "合計金額",
        "見積合計", "総額", "御見積額",
    ),
    "period": (
        "工期", "工事期間", "施工期間", "工事工期",
    ),
    "valid_until": (
        "見積有効期限", "御見積有効期限", "お見積有効期限", "見積の有効期限",
        "有効期限", "有効期間",
    ),
    "note": (
        "備考", "摘要", "特記事項", "注記", "コメント", "その他",
    ),
}

# 画面に出すときの日本語名。並び順もこの通りに表示する。
FIELD_LABELS: dict[str, str] = {
    "code": "見積番号（現場コード）",
    "name": "工事件名（現場名）",
    "customer_name": "取引先（御中）",
    "payment_terms": "支払条件",
    "contract_amount": "見積金額",
    "address": "施工場所",
    "start_date": "工期開始",
    "end_date": "工期終了",
    "estimate_valid_until": "見積有効期限",
    "note": "備考",
}

# 値として長すぎるものは拾い間違い（明細行を掴んだ等）とみなして捨てる。
MAX_VALUE_LENGTH = 200

# Excel の1シートあたり読む行数の上限。見出しは表紙の先頭にあるので、
# 数万行の明細シートを最後まで舐めないための歯止め。
EXCEL_MAX_ROWS = 2000

# 決め打ちのラベル以外も拾う「その他の読み取り項目」の制限。
MAX_DETAIL_PAIRS = 40
MAX_LABEL_LENGTH = 30
# 非空セルがこれ以上ある行は明細行とみなし、ラベル/値の組としては拾わない。
# 数量・単価まで拾うとノイズに埋もれて読めなくなる。
DETAIL_ROW_MIN_CELLS = 4
# 値の側に来たら組として意味を成さない語。
_VALUE_STOPWORDS = frozenset({"御中", "様", "殿"})

_SEPARATORS = " \t：:＝=｜|・"
# 「見積No.」の末尾のようにラベル側に付く記号。値と一緒に拾わないよう落とす。
_TRIMMABLE = _SEPARATORS + ".．,，、;；#＃"

# 得意先マスタと突き合わせる際に無視する法人格。NFKC 後の表記で持つ。
_CORP_TOKENS = (
    "株式会社", "有限会社", "合同会社", "合資会社", "合名会社",
    "(株)", "(有)", "(名)", "(資)", "(同)",
)


def _nfkc(text) -> str:
    """全角英数・㈱ 等をそろえ、全角スペースを半角にして前後を落とす。"""
    if text is None:
        return ""
    s = unicodedata.normalize("NFKC", str(text))
    return s.replace("　", " ").strip()


def _key(text) -> str:
    """ラベル比較用のキー。空白を全部落として小文字化する。"""
    return re.sub(r"\s+", "", _nfkc(text)).lower()


# 全ラベルの比較キー。値を探すときに「隣もラベルだった」を弾くのに使う。
_ALL_LABEL_KEYS: tuple[str, ...] = tuple(
    {_key(v) for variants in LABELS.values() for v in variants}
)


# ---------------------------------------------------------------------------
# 読み込み
# ---------------------------------------------------------------------------

def _read_csv_rows(filepath: str | Path) -> list[list[str]]:
    """CSV を文字コードを試しながら読み、セルの二次元リストにする。"""
    last_error: UnicodeDecodeError | None = None
    for encoding in ("cp932", "utf-8-sig", "utf-8"):
        try:
            with open(filepath, encoding=encoding, newline="") as f:
                return [[c for c in row] for row in csv.reader(f)]
        except UnicodeDecodeError as e:
            last_error = e
            continue
    raise ValueError(
        "文字コードを判別できませんでした（CP932 / UTF-8 を試しました）。"
    ) from last_error


def _read_excel_rows(filepath: str | Path) -> list[list[str]]:
    """Excel の全シートをセルの二次元リストにする。

    見出しが「表紙」シートにあり明細が別シート、という作りが多いので
    シートを順につないで返す。ラベル走査は最初に当たった値を採るため、
    先頭シートの見出しが優先される。

    data_only=True で数式ではなく計算結果を読む。合計金額が数式のまま
    保存されている（Excel で一度も開かれていない）ファイルでは値が空に
    なるが、その場合は読めなかった項目として確認画面で入力してもらう。
    """
    import openpyxl

    workbook = openpyxl.load_workbook(filepath, data_only=True, read_only=True)
    rows: list[list[str]] = []
    try:
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows(max_row=EXCEL_MAX_ROWS, values_only=True):
                rows.append(["" if v is None else str(v) for v in row])
    finally:
        workbook.close()
    return rows


def _read_pdf_rows(filepath: str | Path) -> list[list[str]]:
    """PDF から表とテキスト行の両方を取り出す。

    見出し部が表になっていない見積書もあるため、表だけでは足りない。
    テキスト行は空白2つ以上で区切って擬似的なセルに割る。
    """
    import pdfplumber

    rows: list[list[str]] = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for row in table:
                    rows.append([(c or "") for c in row])
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()
                if line:
                    rows.append(re.split(r"[ 　]{2,}|\t", line))
    return rows


# ---------------------------------------------------------------------------
# 走査
# ---------------------------------------------------------------------------

def _inline_value(cell: str, variant_key: str) -> str | None:
    """「見積番号：12345」のように同じセルに値が入っている場合の値を返す。

    variant_key は空白を除いた比較用キーなので、元の文字列側では空白を
    読み飛ばしながら同じ文字数ぶん進めてラベル部分を切り落とす。
    「見積No.」のようにラベル側の記号が残ることがあるので前後を削る。
    """
    nfkc = _nfkc(cell)
    seen = 0
    for i, ch in enumerate(nfkc):
        if ch.isspace():
            continue
        seen += 1
        if seen == len(variant_key):
            return nfkc[i + 1:].strip(_TRIMMABLE) or None
    return None


def _looks_like_label(text: str) -> bool:
    """そのセル自体が別のラベルか。ラベルの隣がラベルの表を値と誤読しない。"""
    key = _key(text)
    return bool(key) and any(key.startswith(v) for v in _ALL_LABEL_KEYS)


def _value_to_the_right(rows: list[list[str]], r: int, c: int) -> str | None:
    for cell in rows[r][c + 1:]:
        value = _nfkc(cell)
        if value and not _looks_like_label(value):
            return value
    return None


def _value_below(rows: list[list[str]], r: int, c: int) -> str | None:
    """真下のセル。ラベルが見出し行にあり値が次行にある形に対応する。"""
    for rr in (r + 1, r + 2):
        if rr >= len(rows) or c >= len(rows[rr]):
            continue
        value = _nfkc(rows[rr][c])
        if value and not _looks_like_label(value):
            return value
    return None


def _find_labeled_value(rows: list[list[str]], variants: tuple[str, ...]) -> str | None:
    """ラベルに対応する値を、同セル → 右 → 下 の順に探す。最初の1件を返す。

    長いラベルから先に試す。「工事名称」を「工事名」で拾ってしまうと、
    残りの「称」を値と誤読するため。
    """
    variant_keys = sorted((_key(v) for v in variants), key=len, reverse=True)
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            cell_key = _key(cell)
            if not cell_key:
                continue
            for variant_key in variant_keys:
                if not cell_key.startswith(variant_key):
                    continue
                value = (
                    _inline_value(cell, variant_key)
                    or _value_to_the_right(rows, r, c)
                    or _value_below(rows, r, c)
                )
                if value and len(value) <= MAX_VALUE_LENGTH:
                    return value
    return None


def _extract_all_pairs(
    rows: list[list[str]], exclude: set[str]
) -> list[tuple[str, str]]:
    """「ラベル, 値」に見える組をすべて拾う。

    見出し部には工事区分・担当者・電話番号・値引きなど、こちらが名前を
    知らない項目も並ぶ。決め打ちのラベルだけでは取りこぼすため、
    「非空セルが2〜3個の行」を見出し行とみなし、先頭を項目名・次を値として
    機械的に集める。1セルに「項目：値」と入っている形も拾う。

    明細行（非空セルが多い行）は対象外。数量や単価まで集めるとノイズに
    埋もれる。exclude には既に現場の項目へ入れた値を渡して重複を防ぐ。
    """
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()

    for row in rows:
        filled = [c for c in (_nfkc(cell) for cell in row) if c]
        if not filled or len(filled) >= DETAIL_ROW_MIN_CELLS:
            continue

        if len(filled) == 1:
            label, sep, value = filled[0].partition("：")
            if not sep:
                label, sep, value = filled[0].partition(":")
            if not sep:
                continue
        else:
            label, value = filled[0], filled[1]

        label = label.strip(_TRIMMABLE)
        value = value.strip(_TRIMMABLE)
        if not label or not value or label.isdigit():
            continue
        if len(label) > MAX_LABEL_LENGTH or len(value) > MAX_VALUE_LENGTH:
            continue
        if value in _VALUE_STOPWORDS or value in exclude:
            continue

        key = _key(label)
        if key in seen:
            continue
        seen.add(key)
        pairs.append((label, value))
        if len(pairs) >= MAX_DETAIL_PAIRS:
            break

    return pairs


def clean_company_name(raw: str) -> str:
    """「株式会社○○ 御中」から会社名だけを取り出す。"""
    name = _nfkc(raw)
    name = re.split(r"御中|様|殿", name)[0]
    return name.strip(" 　\t【】[]()（）:：")


def _find_customer_name(rows: list[list[str]]) -> str | None:
    """「御中」が書かれたセルから宛先の会社名を取り出す。

    「株式会社○○ 御中」と1セルに入る場合と、会社名と「御中」が隣り合う
    セルに分かれる場合の両方がある。
    """
    for row in rows:
        for c, cell in enumerate(row):
            text = _nfkc(cell)
            if "御中" not in text:
                continue
            name = clean_company_name(text)
            if name:
                return name
            # 「御中」だけのセル → 左隣にさかのぼる
            for cc in range(c - 1, -1, -1):
                left = clean_company_name(row[cc])
                if left:
                    return left
    return None


def normalize_company_name(name: str) -> str:
    """得意先マスタと突き合わせるためのキー。法人格と空白の違いを吸収する。

    「株式会社ABC」「(株)ABC」「㈱ ABC」「ABC株式会社」がすべて "abc" になる。
    """
    s = _nfkc(name)
    for token in _CORP_TOKENS:
        s = s.replace(token, "")
    return re.sub(r"\s+", "", s).lower()


# ---------------------------------------------------------------------------
# 値の変換
# ---------------------------------------------------------------------------

def _parse_amount(text: str | None) -> int | None:
    """「1,234,567円(税抜)」→ 1234567。数字が無ければ None。"""
    if not text:
        return None
    s = re.sub(r"[,，\s円¥￥]", "", _nfkc(text))
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None


def _extract_dates(text: str) -> list[str]:
    """文字列から日付をすべて拾って ISO 形式で返す。西暦と令和に対応する。"""
    found: list[str] = []
    s = _nfkc(text)

    for y, m, d in re.findall(r"(\d{4})[/年.\-](\d{1,2})[/月.\-](\d{1,2})", s):
        try:
            found.append(date(int(y), int(m), int(d)).isoformat())
        except ValueError:
            continue
    if found:
        return found

    for y, m, d in re.findall(r"令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日", s):
        try:
            found.append(date(2018 + int(y), int(m), int(d)).isoformat())
        except ValueError:
            continue
    return found


def _parse_period(text: str | None) -> tuple[str | None, str | None]:
    """「2026/4/1〜2026/6/30」→ (開始, 終了)。片方しか無ければ終了は None。"""
    if not text:
        return None, None
    dates = _extract_dates(text)
    if len(dates) >= 2:
        return dates[0], dates[1]
    if len(dates) == 1:
        return dates[0], None
    return None, None


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def parse_estimate_file(filepath: str | Path, suffix: str) -> dict:
    """見積ファイルを読み、現場の初期値の候補を返す。

    読めなかった項目は None のまま返す（推測で埋めない）。
    found / missing は確認画面で「何が読めて何が手入力か」を出すために使う。
    """
    suffix = (suffix or "").lower()
    if suffix == ".csv":
        rows = _read_csv_rows(filepath)
    elif suffix in (".xlsx", ".xlsm"):
        rows = _read_excel_rows(filepath)
    elif suffix == ".pdf":
        rows = _read_pdf_rows(filepath)
    elif suffix == ".xls":
        # openpyxl は旧形式を読めない。変換してもらうほうが確実。
        raise ValueError(
            "古い Excel 形式(.xls)は読めません。"
            "Excel で開いて .xlsx で保存し直してください。"
        )
    else:
        raise ValueError(
            "CSV(.csv) / Excel(.xlsx, .xlsm) / PDF(.pdf) のみ対応しています。"
        )

    start_date, end_date = _parse_period(_find_labeled_value(rows, LABELS["period"]))

    data: dict = {
        "code": _find_labeled_value(rows, LABELS["code"]),
        "name": _find_labeled_value(rows, LABELS["name"]),
        "customer_name": _find_customer_name(rows),
        "payment_terms": _find_labeled_value(rows, LABELS["payment_terms"]),
        "contract_amount": _parse_amount(_find_labeled_value(rows, LABELS["amount"])),
        "address": _find_labeled_value(rows, LABELS["address"]),
        "start_date": start_date,
        "end_date": end_date,
        "estimate_valid_until": _find_labeled_value(rows, LABELS["valid_until"]),
        "note": _find_labeled_value(rows, LABELS["note"]),
    }
    data["found"] = [k for k in FIELD_LABELS if data.get(k) not in (None, "")]
    data["missing"] = [k for k in FIELD_LABELS if data.get(k) in (None, "")]

    # 決め打ちのラベル以外も取りこぼさない。既に項目へ入れた値は除く。
    captured = {str(data[k]) for k in FIELD_LABELS if data.get(k) not in (None, "")}
    data["details"] = _extract_all_pairs(rows, captured)
    return data
