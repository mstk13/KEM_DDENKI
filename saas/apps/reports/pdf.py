"""日報の PDF 出力（ADR-0049）。

日報 1 件を A4 縦 1 ページにする。一覧から出すときは、並んでいる日報を
1 件ずつページを分けて 1 つの PDF にまとめる。

日本語は reportlab 内蔵の CID フォント（HeiseiKakuGo-W5）を使う。
人材評価の PDF（apps/workers/pdf_template.py）と同じで、フォントファイルは要らない。
"""

from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
_FONT = "HeiseiKakuGo-W5"

WEEKDAYS = ("月", "火", "水", "木", "金", "土", "日")

_BORDER = colors.HexColor("#94a3b8")
_LABEL_BG = colors.HexColor("#eef2f7")

STYLE_TITLE = ParagraphStyle("RptTitle", fontName=_FONT, fontSize=18, leading=24)
STYLE_SUB = ParagraphStyle(
    "RptSub", fontName=_FONT, fontSize=9, leading=13, textColor=colors.HexColor("#475569"),
)
STYLE_LABEL = ParagraphStyle(
    "RptLabel", fontName=_FONT, fontSize=9, leading=13, textColor=colors.HexColor("#334155"),
)
STYLE_VALUE = ParagraphStyle("RptValue", fontName=_FONT, fontSize=10.5, leading=15)
STYLE_TEXT = ParagraphStyle("RptText", fontName=_FONT, fontSize=10.5, leading=16)
STYLE_H = ParagraphStyle(
    "RptH", fontName=_FONT, fontSize=11, leading=15, spaceBefore=10, spaceAfter=4,
)
STYLE_SMALL = ParagraphStyle(
    "RptSmall", fontName=_FONT, fontSize=8, leading=11, textColor=colors.HexColor("#64748b"),
)


def _p(text, style=STYLE_VALUE):
    """利用者が入れた文字は reportlab の書式として解釈されないようにエスケープし、改行を活かす。"""
    body = escape(str(text)) if text not in (None, "") else "-"
    return Paragraph(body.replace("\n", "<br/>"), style)


def _date_label(day):
    if not day:
        return "-"
    return f"{day.year}年{day.month}月{day.day}日（{WEEKDAYS[day.weekday()]}）"


def _time_label(day, time):
    if not time:
        return ""
    return f"{day.month}/{day.day} {time:%H:%M}" if day else f"{time:%H:%M}"


def _hours(value):
    return f"{value:.2f} 時間" if value is not None else "-"


def _period_label(report):
    """開始・終了の表示。日をまたぐときは日付も付ける。"""
    if not report.start_time and not report.end_time:
        return "-"
    start_day = report.start_date or report.report_date
    end_day = report.end_date or start_day
    same_day = start_day == end_day == report.report_date
    start = f"{report.start_time:%H:%M}" if report.start_time else "?"
    end = f"{report.end_time:%H:%M}" if report.end_time else "?"
    if same_day:
        return f"{start} 〜 {end}"
    start_label = _time_label(start_day, report.start_time) or start
    end_label = _time_label(end_day, report.end_time) or end
    return f"{start_label} 〜 {end_label}"


def _person(user):
    if not user:
        return "-"
    return user.get_full_name() or user.first_name or user.username


def _grid(rows, col_widths):
    """見出し（薄い地色）＋値 の表。rows は [(見出し, 値), ...] を 1 行 2 組まで。"""
    data = []
    for row in rows:
        cells = []
        for label, value in row:
            cells.append(_p(label, STYLE_LABEL))
            cells.append(value if isinstance(value, Paragraph) else _p(value))
        data.append(cells)
    table = Table(data, colWidths=col_widths)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.6, _BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    for col in range(0, len(col_widths), 2):
        style.append(("BACKGROUND", (col, 0), (col, -1), _LABEL_BG))
    table.setStyle(TableStyle(style))
    return table


def _box(label, text, width):
    """見出し＋自由記述の枠（作業内容・その他）。"""
    table = Table(
        [[_p(label, STYLE_LABEL)], [_p(text, STYLE_TEXT)]],
        colWidths=[width],
        # 作業内容は短くても書き込める余白が残るよう、本文の行に最小の高さを持たせる
        minRowHeights=[0, 34 * mm] if label == "作業内容" else None,
    )
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, _BORDER),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, _BORDER),
        ("BACKGROUND", (0, 0), (-1, 0), _LABEL_BG),
        ("VALIGN", (0, 1), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _materials_table(report, width):
    materials = list(report.materials_used.select_related("material").all())
    if not materials:
        return None
    data = [[_p("材料", STYLE_LABEL), _p("数量", STYLE_LABEL), _p("単位", STYLE_LABEL)]]
    for item in materials:
        name = item.material.name if item.material_id else item.material_name
        data.append([_p(name), _p(f"{item.quantity_used:g}"), _p(item.unit)])
    table = Table(data, colWidths=[width - 50 * mm, 28 * mm, 22 * mm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, _BORDER),
        ("BACKGROUND", (0, 0), (-1, 0), _LABEL_BG),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _report_elements(report, width):
    site = report.site
    orderer = str(site.customer) if site and site.customer_id else "-"
    partner = str(report.partner) if report.is_partner_worker and report.partner_id else "-"
    status = report.get_status_display()
    approval = "-"
    if report.approved_by_id:
        when = timezone.localtime(report.approved_at) if report.approved_at else None
        approval = _person(report.approved_by)
        if when:
            approval += f"（{when:%Y/%m/%d %H:%M}）"

    label_w = 24 * mm
    value_w = (width - label_w * 2) / 2
    cols = [label_w, value_w, label_w, value_w]

    elements = [
        Table(
            [[_p("作業日報", STYLE_TITLE), _p(f"状態: {status}", STYLE_SUB)]],
            colWidths=[width - 40 * mm, 40 * mm],
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]),
        ),
        _p(report.company.name if report.company_id else "", STYLE_SUB),
        Spacer(1, 6),
        _grid([
            [("日付", _date_label(report.report_date)),
             ("天候", report.get_weather_display() or "-")],
            [("作業員", str(report.worker)), ("協力会社", partner)],
            [("現場", str(site) if site else "-"), ("発注先", orderer)],
            [("工程", str(report.process) if report.process_id else "-"),
             ("工種", str(report.work_type) if report.work_type_id else "-")],
            [("開始〜終了", _period_label(report)), ("作業時間", _hours(report.work_hours))],
            [("通常時間", _hours(report.regular_hours)),
             ("残業時間", _hours(report.overtime_hours))],
        ], cols),
        Spacer(1, 8),
        _box("作業内容", report.work_description, width),
    ]

    materials = _materials_table(report, width)
    if materials is not None:
        elements += [_p("使用材料", STYLE_H), materials]

    elements += [
        Spacer(1, 8),
        KeepTogether(_box("その他", report.memo, width)),
        Spacer(1, 10),
        _grid([
            [("作成者", _person(report.created_by)), ("承認", approval)],
        ], cols),
    ]
    return elements


def generate_reports_pdf(reports):
    """日報のリストを 1 件 1 ページの PDF にしてバイト列で返す。"""
    buf = BytesIO()
    printed_at = timezone.localtime()

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(_FONT, 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(18 * mm, 10 * mm, f"出力 {printed_at:%Y/%m/%d %H:%M}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"{doc.page} ページ")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
        title="作業日報", author="KEM",
    )
    width = A4[0] - doc.leftMargin - doc.rightMargin

    elements = []
    for index, report in enumerate(reports):
        if index:
            elements.append(PageBreak())
        elements += _report_elements(report, width)
    doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
