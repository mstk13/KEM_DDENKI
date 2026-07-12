"""発注書 PDF パーサー — テーブル形式のPDFから品目・数量・単価・金額を抽出"""
import pdfplumber


def parse_order_pdf(file_path, col_map=None, start_row=1):
    """PDFからテーブルを抽出し、発注明細リストを返す

    Args:
        file_path: PDFファイルのパス
        col_map: 列マッピング辞書 {name: 0, qty: 2, unit: 3, price: 4, amount: 5, ...}
                 Noneの場合は自動推定
        start_row: データ開始行（0-indexed, ヘッダを除いた行）

    Returns:
        list of dict: [{name, spec, qty, unit, unit_price, amount, supplier, order_date, orderer}, ...]
        metadata: {supplier, order_date, orderer} (PDFヘッダから抽出できた場合)
    """
    if col_map is None:
        col_map = {"name": 0, "qty": 1, "unit": 2, "price": 3, "amount": 4}

    items = []
    metadata = {"supplier": "", "order_date": "", "orderer": ""}

    with pdfplumber.open(file_path) as pdf:
        full_text = ""
        all_tables = []

        for page in pdf.pages:
            # テキストからメタデータ抽出
            text = page.extract_text() or ""
            full_text += text + "\n"

            # テーブル抽出
            tables = page.extract_tables()
            for table in tables:
                all_tables.extend(table)

        # メタデータをテキストから推定
        for line in full_text.split("\n"):
            line_lower = line.strip()
            if "発注先" in line_lower or "御中" in line_lower:
                # 発注先を抽出
                parts = line_lower.replace("発注先", "").replace("御中", "").replace(":", "").replace("：", "").strip()
                if parts:
                    metadata["supplier"] = parts
            elif "発注日" in line_lower or "日付" in line_lower:
                import re
                date_match = re.search(r'(\d{4}[/\-年]\d{1,2}[/\-月]\d{1,2})', line_lower)
                if date_match:
                    metadata["order_date"] = date_match.group(1).replace("年", "-").replace("月", "-").replace("日", "")
            elif "発注者" in line_lower or "担当" in line_lower:
                parts = line_lower.replace("発注者", "").replace("担当", "").replace(":", "").replace("：", "").strip()
                if parts:
                    metadata["orderer"] = parts

        # テーブルデータを処理
        for i, row in enumerate(all_tables):
            if i < start_row:
                continue
            if row is None or all(cell is None or str(cell).strip() == "" for cell in row):
                continue

            # 品目名の取得
            name_idx = col_map.get("name", 0)
            if name_idx >= len(row) or row[name_idx] is None:
                continue
            name = str(row[name_idx]).strip()
            if not name or name in ["品名", "品目", "品目名", "名称", "摘要"]:
                continue

            # 数量
            qty_idx = col_map.get("qty", 1)
            try:
                qty = float(str(row[qty_idx]).replace(",", "").strip()) if qty_idx < len(row) and row[qty_idx] else 0
            except (ValueError, TypeError):
                continue
            if qty == 0:
                continue

            # 単位
            unit_idx = col_map.get("unit", 2)
            unit = str(row[unit_idx]).strip() if unit_idx < len(row) and row[unit_idx] else "式"

            # 単価
            price_idx = col_map.get("price", 3)
            try:
                price = int(float(str(row[price_idx]).replace(",", "").replace("¥", "").strip())) if price_idx < len(row) and row[price_idx] else 0
            except (ValueError, TypeError):
                price = 0

            # 金額
            amount_idx = col_map.get("amount", 4)
            try:
                amount = int(float(str(row[amount_idx]).replace(",", "").replace("¥", "").strip())) if amount_idx < len(row) and row[amount_idx] else 0
            except (ValueError, TypeError):
                amount = int(qty * price) if price else 0

            if amount == 0 and price > 0:
                amount = int(qty * price)

            # 仕様（あれば）
            spec_idx = col_map.get("spec")
            spec = str(row[spec_idx]).strip() if spec_idx is not None and spec_idx < len(row) and row[spec_idx] else ""

            items.append({
                "name": name,
                "spec": spec,
                "qty": qty,
                "unit": unit,
                "unit_price": price,
                "amount": amount,
            })

    return items, metadata
