"""作業日報集計の PDF（ADR-0104）。

紙の「作業日報集計フォーマット」（Excel の 1 枚目）と同じ列・見出しで、A4 横 1 人 1 枚にする。
見出しは 2 段（労働時間の下に所定・早出・残業・深夜）、最後の行に合計と「実労働時間 計」。
列の幅は Excel の列幅の比を基本にする。行が多くて 1 枚に収まらなければ見出しを付けて続ける。
"""

from io import BytesIO

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table

from apps.reports.pdf import _FONT, _grid_style, _p, _style
from apps.reports.work_tally import format_hm

PAGE = landscape(A4)
MARGIN = 10 * mm
_WIDTH = PAGE[0] - 2 * MARGIN

# 列の幅の比（A～M）。Excel の列幅（10, 17, 6, 8, 8.43, 11, 8.43, 8.43, 8.43, 50, 12, 6, 30）を
# 基本に、PDF で折り返さないよう作業者名・所定～深夜・車両を広げ、作業内容・現場名を詰めた
_COLUMN_RATIOS = (12, 17, 5, 7, 7, 11, 11, 11, 11, 42, 13, 11, 26)
COL_WIDTHS = [_WIDTH * w / sum(_COLUMN_RATIOS) for w in _COLUMN_RATIOS]

HEADER_FILL = colors.HexColor("#D9E1F2")  # Excel の見出しの色
EXCLUDED_NOTE = "（集計から外した日は載せていません）"
_SIZE = 7.5


def reiwa_date(day):
    """「令和8年9月1日」（Excel の書式 ggge年m月d日 と同じ）。令和より前は西暦。"""
    if day.year >= 2019:
        return f"令和{day.year - 2018}年{day.month}月{day.day}日"
    return f"{day.year}年{day.month}月{day.day}日"


def reiwa_month(year, month):
    return f"令和{year - 2018}年{month}月" if year >= 2019 else f"{year}年{month}月"


def _cell(text, align=None):
    return _p(text, _SIZE, align)


def _two_lines(label):
    """「早出（～8時）」を「早出」と「（～8時）」の 2 行にする。

    列が細いので、途中で折り返さないようにかっこの前で改行する。
    """
    return label.replace("（", "\n（", 1)


def _header_rows(labels):
    center = TA_CENTER
    row1 = [
        _cell("作業者名", center), _cell("年月日", center), _cell("曜日", center),
        _cell("始業", center), _cell("終業", center),
        _cell("労働時間（実労働時間）", center), "", "", "",
        _cell("作業内容", center), _cell("使用材料", center), _cell("車両", center),
        _cell("現場名", center),
    ]
    row2 = [
        "", "", "", "", "",
        *[_p(_two_lines(labels[key]), 6.5, center)
          for key in ("regular", "early", "overtime", "night")],
        "", "", "", "",
    ]
    return [row1, row2]


def _clock(value):
    return f"{value.hour}:{value.minute:02d}" if value else ""


def _body_row(worker_name, row):
    center, right = TA_CENTER, TA_RIGHT
    return [
        _cell(worker_name),
        _cell(reiwa_date(row.day)),
        _cell(row.weekday, center),
        _cell(_clock(row.start), center),
        _cell(_clock(row.end), center),
        _cell(row.regular_hm, right),
        _cell(row.early_hm, right),
        _cell(row.overtime_hm, right),
        _cell(row.night_hm, right),
        _cell(row.work_description),
        _cell(row.materials),
        _cell(row.vehicle, center),
        _cell(row.site_names),
    ]


def _total_row(sheet):
    right = TA_RIGHT
    totals = sheet["totals"]
    return [
        "", "", "", "", _cell("合計", TA_CENTER),
        _cell(format_hm(totals["regular"]), right),
        _cell(format_hm(totals["early"]), right),
        _cell(format_hm(totals["overtime"]), right),
        _cell(format_hm(totals["night"]), right),
        _cell(f"実労働時間 計 {format_hm(sheet['total_all'])}"), "", "", "",
    ]


def sheet_elements(sheet):
    """1 人分の見出し・表。"""
    worker = sheet["worker"]
    title = Paragraph(
        f"作業日報集計　{reiwa_month(sheet['year'], sheet['month'])}　{worker.name}",
        _style(12),
    )
    rows = [row for row in sheet["rows"] if not row.excluded]
    data = _header_rows(sheet["labels"])
    data += [_body_row(worker.name, row) for row in rows]
    data.append(_total_row(sheet))
    last = len(data) - 1

    table = Table(data, colWidths=COL_WIDTHS, repeatRows=2)
    table.setStyle(_grid_style([
        # 見出し（Excel と同じく労働時間だけ 2 段、ほかは 2 段ぶんを 1 つに）
        *[("SPAN", (col, 0), (col, 1)) for col in (0, 1, 2, 3, 4, 9, 10, 11, 12)],
        ("SPAN", (5, 0), (8, 0)),
        ("BACKGROUND", (0, 0), (-1, 1), HEADER_FILL),
        ("VALIGN", (0, 2), (-1, last - 1), "TOP"),
        # 合計の行
        ("SPAN", (9, last), (12, last)),
        ("BACKGROUND", (0, last), (-1, last), colors.HexColor("#F1F5F9")),
    ]))
    elements = [title, Spacer(0, 3 * mm), table]
    if len(rows) != len(sheet["rows"]):
        elements += [Spacer(0, 2 * mm), Paragraph(EXCLUDED_NOTE, _style(7))]
    return elements


def generate_tally_pdf(sheets):
    """集計表（build_sheet の結果）のリストを、1 人 1 枚（収まらなければ続き）の PDF にする。"""
    buf = BytesIO()
    printed_at = timezone.localtime()

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(_FONT, 7)
        canvas.setFillColor(colors.HexColor("#475569"))
        canvas.drawRightString(
            PAGE[0] - MARGIN, 6 * mm, f"出力 {printed_at:%Y/%m/%d %H:%M}　{doc.page} ページ",
        )
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf, pagesize=PAGE,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=12 * mm,
        title="作業日報集計", author="KEM",
    )
    elements = []
    for index, sheet in enumerate(sheets):
        if index:
            elements.append(PageBreak())
        elements += sheet_elements(sheet)
    doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
