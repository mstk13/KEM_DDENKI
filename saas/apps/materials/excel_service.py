"""発注書・発注請書の Excel 生成サービス。

テンプレート xlsx を読み込み、PurchaseOrder データを注入して返す。
"""

import io
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

TEMPLATE_PATH = Path(__file__).parent / "excel_templates" / "po_template.xlsx"

# テンプレートのセルマッピング（発注書シート / 発注請書シート共通）
# 明細行: rows 17–31 (最大15行)
ITEM_START_ROW = 17
ITEM_END_ROW = 31
MAX_ITEMS = ITEM_END_ROW - ITEM_START_ROW + 1


def _fill_common(ws, po, items, company):
    """発注書・発注請書の共通セルにデータを注入する。"""
    # 宛先: A4 — "〇〇〇〇　御中"
    supplier_name = po.supplier.name if po.supplier else ""
    ws["A4"] = f"　{supplier_name}　御中"

    # No: G4
    ws["G4"] = f"PO-{po.pk:05d}"

    # 発注日 / 発行日: G5
    ws["G5"] = po.order_date

    # 件名: B8 (merged B8:D8)
    subject = po.subject or (po.site.name if po.site else "")
    ws["B8"] = subject

    # 納期: B10 (merged B10:D10)
    if po.delivery_date:
        ws["B10"] = po.delivery_date

    # 支払条件: B11 (merged B11:D11)
    ws["B11"] = po.payment_terms or "月末締翌月末払"

    # 明細行
    for i, item in enumerate(items[:MAX_ITEMS]):
        row = ITEM_START_ROW + i

        # 摘要 (A列 — merged A:C)
        name = item.display_name
        ws.cell(row=row, column=1, value=name)

        # 税率 (D列)
        ws.cell(row=row, column=4, value=float(item.tax_rate))

        # 数量 (E列)
        ws.cell(row=row, column=5, value=float(item.quantity))

        # 単位 (F列)
        unit = item.unit or (item.material.unit if item.material else "")
        ws.cell(row=row, column=6, value=unit)

        # 単価 (G列)
        ws.cell(row=row, column=7, value=float(item.unit_price))

        # 金額 (H列) — 数式がテンプレートにあるが、値も入れておく
        # テンプレートに =ROUND(E*G,0) の数式があるのでそのまま残す

    # 仕様・特記事項
    # A37: 見積番号
    if po.quotation:
        ws["A37"] = f"見積番号：{po.quotation.pk}"

    # A38: 工事場所
    if po.site:
        ws["A38"] = f"工事場所：{po.site.name}"

    # A39: 工事場所住所
    if po.site and hasattr(po.site, "address") and po.site.address:
        ws["A39"] = f"工事場所住所：{po.site.address}"

    # A40: 工事予定日
    if po.delivery_date:
        ws["A40"] = f"工事予定日：{po.delivery_date}"

    # 備考（特記事項追加）
    if po.notes:
        ws["A41"] = po.notes


def generate_purchase_order_excel(po, items):
    """発注書 Excel を生成して BytesIO で返す。

    Args:
        po: PurchaseOrder instance (select_related site, supplier, quotation)
        items: PurchaseOrderItem queryset

    Returns:
        io.BytesIO: Excel ファイルの内容
    """
    wb = load_workbook(str(TEMPLATE_PATH))
    ws = wb["発注書"]

    company = po.company
    _fill_common(ws, po, items, company)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def generate_purchase_order_acceptance_excel(po, items):
    """発注請書 Excel を生成して BytesIO で返す。

    Args:
        po: PurchaseOrder instance (select_related site, supplier, quotation)
        items: PurchaseOrderItem queryset

    Returns:
        io.BytesIO: Excel ファイルの内容
    """
    wb = load_workbook(str(TEMPLATE_PATH))
    ws = wb["発注請書"]

    company = po.company
    _fill_common(ws, po, items, company)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def parse_supplier_csv(csv_file, encoding="utf-8"):
    """仕入先から届いた見積もりCSVをパースする。

    想定カラム（柔軟にマッピング）:
      品名/材料名, 数量, 単位, 単価, 税率(任意)

    Returns:
        list[dict]: [{"name": str, "quantity": Decimal, "unit": str,
                      "unit_price": Decimal, "tax_rate": Decimal}, ...]
    """
    import csv

    content = csv_file.read()
    # BOM 対応
    if isinstance(content, bytes):
        for enc in [encoding, "utf-8-sig", "cp932", "shift_jis"]:
            try:
                text = content.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            text = content.decode("utf-8", errors="replace")
    else:
        text = content

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)

    if not rows:
        return []

    # ヘッダー行を検出（品名/材料名/摘要 を含む行）
    header_row = None
    header_idx = 0
    name_keywords = {"品名", "材料名", "摘要", "品目", "商品名", "名称", "item", "name"}
    for i, row in enumerate(rows):
        for cell in row:
            if cell.strip().lower() in name_keywords or any(k in cell for k in name_keywords):
                header_row = row
                header_idx = i
                break
        if header_row:
            break

    if header_row is None:
        # ヘッダーが見つからない場合、1行目をヘッダーとみなす
        header_row = rows[0]
        header_idx = 0

    # カラムマッピング
    col_map = {}
    qty_keywords = {"数量", "qty", "quantity"}
    unit_keywords = {"単位", "unit"}
    price_keywords = {"単価", "unit_price", "価格"}
    tax_keywords = {"税率", "tax", "tax_rate"}
    amount_keywords = {"金額", "amount", "合計"}

    for j, cell in enumerate(header_row):
        c = cell.strip().lower()
        if any(k in c for k in name_keywords):
            col_map["name"] = j
        elif any(k in c for k in qty_keywords):
            col_map["quantity"] = j
        elif any(k in c for k in unit_keywords):
            col_map["unit"] = j
        elif any(k in c for k in price_keywords):
            col_map["price"] = j
        elif any(k in c for k in tax_keywords):
            col_map["tax_rate"] = j
        elif any(k in c for k in amount_keywords):
            col_map["amount"] = j

    if "name" not in col_map:
        # 最低限の名前列がなければ、列番号でフォールバック
        col_map["name"] = 0
        if len(header_row) > 1:
            col_map["quantity"] = 1
        if len(header_row) > 2:
            col_map["unit"] = 2
        if len(header_row) > 3:
            col_map["price"] = 3

    items = []
    for row in rows[header_idx + 1:]:
        if not row or all(not c.strip() for c in row):
            continue

        name_idx = col_map.get("name")
        name = (
            row[name_idx].strip()
            if name_idx is not None and name_idx < len(row)
            else ""
        )
        if not name:
            continue

        def _decimal(idx_key, default="0", row=row):
            # row を既定引数で束縛する。ループ内で定義したクロージャが
            # 最後の行を参照しないようにするため（現状は同じ周回で呼んでいるので
            # 動作は同じだが、後から遅延評価に変えたときに壊れる）。
            idx = col_map.get(idx_key)
            if idx is None or idx >= len(row):
                return Decimal(default)
            val = row[idx].strip().replace(",", "").replace("¥", "").replace("￥", "")
            try:
                return Decimal(val)
            except Exception:
                return Decimal(default)

        quantity = _decimal("quantity", "1")
        unit_price = _decimal("price", "0")
        tax_rate = _decimal("tax_rate", "0.10")

        unit_idx = col_map.get("unit")
        unit = row[unit_idx].strip() if unit_idx is not None and unit_idx < len(row) else ""

        items.append({
            "name": name,
            "quantity": quantity,
            "unit": unit,
            "unit_price": unit_price,
            "tax_rate": tax_rate,
        })

    return items
