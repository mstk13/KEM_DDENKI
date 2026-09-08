"""入札参加資格の Excel / PDF インポート。

Excel（.xlsx）: openpyxl でパースし、発注先・認定種目・等級・経審・総合・業者番号・
認定開始・申請区分・申請方法 を読み取る。
PDF（.pdf）: pdfplumber でテキスト抽出し、同様の表構造をパースする。

使い方:
    from importer import import_excel, import_pdf
    records = import_excel(filepath)  # -> list[dict]
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path


def _parse_valid_from(raw: str | None) -> str | None:
    """'2025/4/1～' のような文字列から ISO date を返す。"""
    if not raw:
        return None
    raw = str(raw).strip().rstrip("～〜")
    m = re.search(r"(\d{4})[/年.-](\d{1,2})[/月.-](\d{1,2})", raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            pass
    return None


def _parse_valid_until(valid_from: str | None, header_text: str) -> str | None:
    """ヘッダーの有効期限テキスト（例: '令和7年4月1日～令和9年3月31日'）から
    終了日を抽出する。見つからなければ valid_from + 2年 をデフォルトにする。"""
    # 西暦パターン
    dates = re.findall(r"(\d{4})[/年.-](\d{1,2})[/月.-](\d{1,2})", header_text)
    if len(dates) >= 2:
        y, m, d = (int(x) for x in dates[-1])
        try:
            return date(y, m, d).isoformat()
        except ValueError:
            pass
    # 令和パターン
    reiwa = re.findall(r"令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日", header_text)
    if len(reiwa) >= 2:
        y, m, d = (int(x) for x in reiwa[-1])
        try:
            return date(2018 + y, m, d).isoformat()
        except ValueError:
            pass
    # フォールバック: valid_from + 2年
    if valid_from:
        try:
            dt = date.fromisoformat(valid_from)
            return date(dt.year + 2, dt.month, dt.day).isoformat()
        except ValueError:
            pass
    return None


def _safe_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _safe_str(val) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def import_excel(filepath: str | Path) -> list[dict]:
    """Excel ファイルをパースして資格レコードのリストを返す。"""
    import openpyxl

    wb = openpyxl.load_workbook(filepath, data_only=True)
    # シート名に「官公庁」を含むものを優先、なければ最初のシート
    ws = None
    for name in wb.sheetnames:
        if "官公庁" in name or "資格" in name:
            ws = wb[name]
            break
    if ws is None:
        ws = wb[wb.sheetnames[-1] if len(wb.sheetnames) > 1 else wb.sheetnames[0]]

    # ヘッダーから有効期限テキストを取得（最初の数行）
    header_text = ""
    for row in ws.iter_rows(min_row=1, max_row=5, values_only=True):
        header_text += " ".join(str(c) for c in row if c) + " "

    records: list[dict] = []
    current_issuer: str | None = None

    for row in ws.iter_rows(min_row=6, values_only=False):
        cells = {c.column: c.value for c in row}
        # B=2: 発注先, C=3: 認定種目, D=4: 等級, E=5: 経審,
        # F=6: 総合, G=7: 業者番号, H=8: 認定開始
        # K=11: 申請区分, L=12: 申請方法

        issuer_raw = _safe_str(cells.get(2))
        category = _safe_str(cells.get(3))
        grade = _safe_str(cells.get(4))
        keisin = _safe_int(cells.get(5))
        total = _safe_int(cells.get(6))
        vendor = _safe_str(cells.get(7))
        valid_from_raw = _safe_str(cells.get(8))
        app_type = _safe_str(cells.get(11))
        app_method = _safe_str(cells.get(12))

        # 発注先が空なら直前の発注先を引き継ぐ
        if issuer_raw:
            cleaned = issuer_raw.replace("\u3000", " ").strip()
            # 管轄一覧行（「官会 北運 東運...」のような長い列挙）はスキップ
            if len(cleaned) > 50 and not cleaned.startswith("〃"):
                # 補足情報行として無視（issuerは更新しない）
                if not category:
                    continue
            elif cleaned.startswith("〃") or cleaned.startswith('"'):
                # 〃（同上マーク）の処理
                suffix = cleaned.lstrip("〃\"").strip().strip("()（）")
                if current_issuer and suffix:
                    current_issuer_base = current_issuer.split("(")[0].split("（")[0].strip()
                    current_issuer = f"{current_issuer_base}({suffix})"
            else:
                current_issuer = cleaned
        # カテゴリも発注先もなく、認定開始だけの行はスキップ
        if not category and not issuer_raw and not any(cells.get(c) for c in [3, 4, 5, 6, 7]):
            continue

        if not category:
            continue

        valid_from = _parse_valid_from(valid_from_raw)
        valid_until = _parse_valid_until(valid_from, header_text)

        records.append({
            "issuer": current_issuer or "不明",
            "category": category,
            "grade": grade,
            "keisin_score": keisin,
            "total_score": total,
            "vendor_number": vendor,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "application_type": app_type,
            "application_method": app_method,
        })

    return records


def import_pdf(filepath: str | Path) -> list[dict]:
    """PDF ファイルからテーブルを抽出して資格レコードのリストを返す。"""
    import pdfplumber

    records: list[dict] = []
    current_issuer: str | None = None
    header_text = ""

    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            # 最初のページからヘッダーテキストを取得
            if not header_text:
                text = page.extract_text() or ""
                header_text = text[:500]

            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row or len(row) < 5:
                        continue
                    # PDF のテーブルは列順がExcelと同じと仮定
                    issuer_raw = _safe_str(row[0]) if len(row) > 0 else None
                    category = _safe_str(row[1]) if len(row) > 1 else None
                    grade = _safe_str(row[2]) if len(row) > 2 else None
                    keisin = _safe_int(row[3]) if len(row) > 3 else None
                    total = _safe_int(row[4]) if len(row) > 4 else None
                    vendor = _safe_str(row[5]) if len(row) > 5 else None
                    valid_from_raw = _safe_str(row[6]) if len(row) > 6 else None

                    if issuer_raw:
                        current_issuer = issuer_raw
                    if not category:
                        continue

                    valid_from = _parse_valid_from(valid_from_raw)
                    valid_until = _parse_valid_until(valid_from, header_text)

                    records.append({
                        "issuer": current_issuer or "不明",
                        "category": category,
                        "grade": grade,
                        "keisin_score": keisin,
                        "total_score": total,
                        "vendor_number": vendor,
                        "valid_from": valid_from,
                        "valid_until": valid_until,
                        "application_type": None,
                        "application_method": None,
                    })

    return records


# ---------------------------------------------------------------------------
# 全省庁統一資格 省庁別許可内容一覧（Excel）
# ---------------------------------------------------------------------------

UNIFIED_SHEET_NAME = "省庁別許可内容一覧"
UNIFIED_AGENCY_HEADER = "省庁・機関名"
# 「―」「-」「－」は「資格なし」の意味で使われるので空扱いにする
_UNIFIED_BLANKS = {"", "―", "-", "－", "—"}


def _unified_str(val) -> str:
    text = str(val).strip() if val is not None else ""
    return "" if text in _UNIFIED_BLANKS else text


def _unified_int(val) -> int | None:
    text = _unified_str(val)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def import_unified_excel(filepath: str | Path) -> list[dict]:
    """全省庁統一資格の「省庁別許可内容一覧」シートを読み込む。

    見出し行（B列が「省庁・機関名」）を探し、その2行下から機関ごとの行を読む。
    列の位置は見出し行の文言から決めるので、列の並びが変わっても追従する。
    """
    import openpyxl

    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb[UNIFIED_SHEET_NAME] if UNIFIED_SHEET_NAME in wb.sheetnames else wb.worksheets[1]

    header_row = None
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 20)):
        if any(_unified_str(c.value) == UNIFIED_AGENCY_HEADER for c in row):
            header_row = row[0].row
            break
    if header_row is None:
        raise ValueError(f"見出し行（{UNIFIED_AGENCY_HEADER}）が見つかりません")

    # 見出し行: 大項目（物品の販売 など）。その下の行: 等級 / 点数
    top = {c.column: _unified_str(c.value) for c in ws[header_row]}
    sub = {c.column: _unified_str(c.value) for c in ws[header_row + 1]}

    def find(label: str, sub_label: str | None = None) -> int | None:
        for col, text in top.items():
            if text != label:
                continue
            if sub_label is None:
                return col
            # 結合セルの直下（等級）と、その右隣（点数）を見る
            for offset in (0, 1):
                if sub.get(col + offset) == sub_label:
                    return col + offset
        return None

    cols = {
        "agency": find(UNIFIED_AGENCY_HEADER),
        "goods_sales_grade": find("物品の販売", "等級"),
        "goods_sales_score": find("物品の販売", "点数"),
        "goods_sales_items": find("物品の販売:営業品目(できること)"),
        "services_grade": find("役務の提供等", "等級"),
        "services_score": find("役務の提供等", "点数"),
        "services_items": find("役務の提供等:営業品目(できること)"),
        "purchase_grade": find("物品の買受け", "等級"),
        "purchase_score": find("物品の買受け", "点数"),
    }
    missing = [k for k, v in cols.items() if v is None]
    if missing:
        raise ValueError(f"列が見つかりません: {', '.join(missing)}")

    records = []
    for row in ws.iter_rows(min_row=header_row + 2, max_row=ws.max_row):
        cell = {c.column: c.value for c in row}
        agency = _unified_str(cell.get(cols["agency"]))
        # 機関名が無い行（注記・空行）は終わり
        if not agency:
            continue
        records.append({
            "sort_order": len(records) + 1,
            "agency": agency,
            "goods_sales_grade": _unified_str(cell.get(cols["goods_sales_grade"])),
            "goods_sales_score": _unified_int(cell.get(cols["goods_sales_score"])),
            "goods_sales_items": _unified_str(cell.get(cols["goods_sales_items"])),
            "services_grade": _unified_str(cell.get(cols["services_grade"])),
            "services_score": _unified_int(cell.get(cols["services_score"])),
            "services_items": _unified_str(cell.get(cols["services_items"])),
            "purchase_grade": _unified_str(cell.get(cols["purchase_grade"])),
            "purchase_score": _unified_int(cell.get(cols["purchase_score"])),
        })
    return records
