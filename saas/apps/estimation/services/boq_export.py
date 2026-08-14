"""内訳書の Excel 出力サービス。

公共建築工事内訳書標準書式に沿った Excel を生成する。
テンプレートベースで発注者ごとの様式差に対応。
"""

import io

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from apps.estimation.models import BoqLine, EstimationProject


def _apply_header_style(ws, row, max_col):
    """ヘッダー行にスタイルを適用する。"""
    header_font = Font(bold=True, size=10)
    header_fill = PatternFill(start_color="D9E2F3", end_color="D9E2F3", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    for col in range(1, max_col + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _level_indent(level: str) -> str:
    """階層に応じたインデント文字列。"""
    indents = {
        "shumoku": "",
        "kamoku": "  ",
        "chukamoku": "    ",
        "saimoku": "      ",
    }
    return indents.get(level, "")


def export_boq_to_excel(project: EstimationProject) -> bytes:
    """積算案件の内訳書を Excel に出力する。

    Returns:
        Excel ファイルのバイト列
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "内訳書"

    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    number_format = "#,##0"
    qty_format = "#,##0.000"

    # --- 表紙情報 ---
    ws["A1"] = "工事名称"
    ws["B1"] = project.name
    ws["A2"] = "発注機関"
    ws["B2"] = project.orderer.name
    ws["A3"] = "入札公告日"
    ws["B3"] = str(project.bid_announcement_date or "")
    ws["A4"] = "主たる工事種別"
    ws["B4"] = project.get_primary_work_category_display()

    for r in range(1, 5):
        ws.cell(row=r, column=1).font = Font(bold=True, size=10)

    # --- 内訳書本体 ---
    header_row = 6
    headers = ["階層", "名称", "仕様", "単位", "数量", "単価", "金額", "備考"]
    for col, h in enumerate(headers, 1):
        ws.cell(row=header_row, column=col, value=h)
    _apply_header_style(ws, header_row, len(headers))

    # 明細行の出力（ツリー順）
    lines = BoqLine.objects.filter(
        project=project,
    ).select_related("estimation_item").order_by("sort_order")

    # ツリー構造を平坦化（parent=None が最上位）
    def _flatten_tree(parent_id=None):
        result = []
        children = [line for line in lines if line.parent_id == parent_id]
        for child in children:
            result.append(child)
            result.extend(_flatten_tree(child.pk))
        return result

    flat_lines = _flatten_tree()

    row = header_row + 1
    for line in flat_lines:
        indent = _level_indent(line.level)
        is_summary = line.level in ("shumoku", "kamoku")

        ws.cell(row=row, column=1, value=line.get_level_display())
        ws.cell(row=row, column=2, value=f"{indent}{line.name}")
        ws.cell(row=row, column=3, value=line.spec)
        ws.cell(row=row, column=4, value=line.unit)

        if line.quantity is not None:
            c = ws.cell(row=row, column=5, value=float(line.quantity))
            c.number_format = qty_format
        if line.unit_price is not None:
            c = ws.cell(row=row, column=6, value=int(line.unit_price))
            c.number_format = number_format
        if line.amount is not None:
            c = ws.cell(row=row, column=7, value=int(line.amount))
            c.number_format = number_format

        ws.cell(row=row, column=8, value=line.remarks)

        # スタイル
        for col in range(1, len(headers) + 1):
            cell = ws.cell(row=row, column=col)
            cell.border = thin_border
            if is_summary:
                cell.font = Font(bold=True, size=10)

        row += 1

    # --- 合計行 ---
    total = sum(
        line.amount for line in flat_lines
        if line.amount and line.level == "shumoku"
    )
    ws.cell(row=row + 1, column=2, value="合計").font = Font(bold=True, size=11)
    c = ws.cell(row=row + 1, column=7, value=int(total))
    c.number_format = number_format
    c.font = Font(bold=True, size=11)

    # 列幅
    col_widths = [12, 40, 30, 8, 12, 14, 16, 20]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
