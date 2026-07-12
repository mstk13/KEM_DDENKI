"""発注書 PDF 生成"""
import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# 日本語フォント登録
pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))

FONT = "HeiseiKakuGo-W5"


def generate_order_pdf(site_title, item_name, item_spec, item_unit,
                       orders, supplier_name="", orderer_name="",
                       delivery_date="", delivery_place="", note=""):
    """発注書PDFをバイトストリームとして返す"""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=20*mm, bottomMargin=20*mm)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="JP", fontName=FONT, fontSize=10, leading=14))
    styles.add(ParagraphStyle(name="JPTitle", fontName=FONT, fontSize=16, leading=20, alignment=1))
    styles.add(ParagraphStyle(name="JPHeader", fontName=FONT, fontSize=12, leading=16))

    elements = []

    # タイトル
    elements.append(Paragraph("発 注 書", styles["JPTitle"]))
    elements.append(Spacer(1, 10*mm))

    # ヘッダ情報
    today_str = date.today().strftime("%Y年%m月%d日")
    header_data = [
        ["発注日", today_str, "", "発注番号", ""],
        ["発注者", orderer_name, "", "現場名", site_title],
        ["発注先", supplier_name, "", "", ""],
    ]
    header_table = Table(header_data, colWidths=[25*mm, 50*mm, 10*mm, 25*mm, 60*mm])
    header_table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), FONT, 9),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 8*mm))

    # 品目情報
    elements.append(Paragraph(f"品目: {item_name}", styles["JPHeader"]))
    if item_spec:
        elements.append(Paragraph(f"仕様: {item_spec}", styles["JP"]))
    elements.append(Spacer(1, 5*mm))

    # 納入条件
    cond_data = [
        ["納入場所", delivery_place or site_title],
        ["納入期限", delivery_date],
        ["備考", note],
    ]
    cond_table = Table(cond_data, colWidths=[25*mm, 145*mm])
    cond_table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), FONT, 9),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.95, 0.95, 0.95)),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(cond_table)
    elements.append(Spacer(1, 8*mm))

    # 発注明細テーブル
    table_data = [["#", "数量", "単位", "単価", "金額", "備考"]]
    total_qty = 0
    total_amount = 0
    for i, o in enumerate(orders, 1):
        table_data.append([
            str(i),
            f"{o['quantity']:.1f}",
            item_unit,
            f"¥{o['unit_price']:,.0f}",
            f"¥{o['amount']:,.0f}",
            o.get("memo", ""),
        ])
        total_qty += o["quantity"]
        total_amount += o["amount"]

    table_data.append(["", f"{total_qty:.1f}", "", "", f"¥{total_amount:,.0f}", "合計"])

    detail_table = Table(table_data, colWidths=[10*mm, 25*mm, 15*mm, 30*mm, 35*mm, 55*mm])
    detail_table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), FONT, 9),
        ("FONT", (0, 0), (-1, 0), FONT, 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.2, 0.2, 0.2)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (1, 0), (4, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        # 合計行
        ("BACKGROUND", (0, -1), (-1, -1), colors.Color(0.95, 0.95, 0.95)),
        ("FONT", (0, -1), (-1, -1), FONT, 9),
    ]))
    elements.append(detail_table)

    doc.build(elements)
    buf.seek(0)
    return buf
