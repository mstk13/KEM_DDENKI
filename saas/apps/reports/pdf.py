"""日報の PDF 出力（ADR-0049、様式は ADR-0053）。

紙の「作業日報 原本」と同じ様式で出す。原本は 1 枚が「1 現場 × 1 日」で、
その日に入った作業員全員を並べる。アプリの日報は 1 件＝作業員 1 人なので、
同じ日・同じ現場の日報を 1 枚にまとめる。

- 自社の作業員の表は 15 行。超えたら同じ見出しで次の用紙に続ける
- 協力会社（is_partner_worker）の欄は 3 社ぶん（3 行・2 行・2 行）。超えたら次の用紙に続ける
- アプリに無い項目（宿泊・交通手段・交通費・承認印・現場代理人）は手書き用に空けておく
- 原本に無いアプリの項目（工種・工程・天候・その他・使用材料）は作業内容の枠に書き込み、
  情報を落とさない。状態・承認者は枠の外の下余白に出す

日本語は reportlab 内蔵の CID フォント（HeiseiKakuGo-W5）を使う。フォントファイルは要らない。
"""

from collections import OrderedDict
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle

pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
_FONT = "HeiseiKakuGo-W5"

WEEKDAYS = ("月", "火", "水", "木", "金", "土", "日")

# 原本の行数
OWN_ROWS = 15
PARTNER_BLOCK_ROWS = (3, 2, 2)

_LINE = colors.black
_W = A4[0] - 24 * mm  # 用紙の左右 12mm を除いた幅（186mm）

TRANSPORT_OWN = (
    "交通手段等　□ 車（　　　台）　□ 電車　　○交通費　　　　　　円　※高速代・電車賃など"
)
TRANSPORT_PARTNER = (
    "交通手段　□ 車（　　台）　□ 乗合　　□ 電車　　○交通費：　　　　　円　高速代・電車賃等"
)


def _style(size=9, align=None, leading=None, color=None):
    return ParagraphStyle(
        f"r{size}{align}{leading}",
        fontName=_FONT, fontSize=size, leading=leading or size * 1.3,
        alignment=align if align is not None else 0,
        textColor=color or colors.black,
    )


def _p(text, size=9, align=None):
    """利用者が入れた文字は reportlab の書式として解釈されないようにエスケープし、改行を活かす。"""
    body = escape(str(text)) if text not in (None, "") else ""
    return Paragraph(body.replace("\n", "<br/>"), _style(size, align))


def _fit(text, width, height, max_size=9, min_size=6):
    """枠（width × height）に収まるよう文字を小さくする。最小でも入らなければ末尾を省略する。"""
    body = escape(text or "").replace("\n", "<br/>")
    for size in range(int(max_size * 2), int(min_size * 2) - 1, -1):
        para = Paragraph(body, _style(size / 2))
        _, h = para.wrap(width, height)
        if h <= height:
            return para
    # 最小の文字でも入らない: 行を後ろから削って「以下略」を付ける
    lines = (text or "").split("\n")
    while lines:
        lines.pop()
        body = escape("\n".join(lines) + "\n…（以下略。全文はアプリの日報を参照）")
        para = Paragraph(body.replace("\n", "<br/>"), _style(min_size))
        _, h = para.wrap(width, height)
        if h <= height:
            return para
    return Paragraph("…（全文はアプリの日報を参照）", _style(min_size))


def _num(value):
    """「45」「12.5」のように余計な 0 を付けない。"""
    if value is None:
        return ""
    return f"{value.normalize():f}" if hasattr(value, "normalize") else f"{value:g}"


def _time_range(report):
    """作業時間「08:00 ～ 18:00」。終了が開始日の翌日以降なら「翌」を付ける。"""
    if not report.start_time and not report.end_time:
        return ""
    start = f"{report.start_time:%H:%M}" if report.start_time else ""
    end = f"{report.end_time:%H:%M}" if report.end_time else ""
    period = report.work_period() if report.start_time and report.end_time else None
    if period and period[1].date() > (report.start_date or report.report_date):
        end = f"翌{end}"
    return f"{start}　～　{end}"


def _overtime(report):
    value = report.overtime_hours
    return f"{_num(value)} h" if value else "h"


def _reiwa_date(day):
    """「令和 8 年 9 月 10 日　木 曜日」。令和より前の日付は西暦で出す。"""
    wd = WEEKDAYS[day.weekday()]
    if day.year >= 2019:
        return f"令和 {day.year - 2018} 年　{day.month} 月　{day.day} 日　　{wd} 曜日"
    return f"{day.year} 年　{day.month} 月　{day.day} 日　　{wd} 曜日"


def _work_summary(reports):
    """作業内容・使用材料の枠に書く文。同じ内容は 1 回だけにする。"""
    lines = []
    seen = set()
    for r in reports:
        head = "／".join(x for x in (
            str(r.work_type) if r.work_type_id else "",
            r.process.name if r.process_id else "",
        ) if x)
        key = (head, (r.work_description or "").strip())
        if key in seen:
            continue
        seen.add(key)
        if head:
            lines.append(f"【{head}】")
        if key[1]:
            lines.append(key[1])

    materials = OrderedDict()
    for r in reports:
        for item in r.materials_used.select_related("material").all():
            name = item.material.name if item.material_id else item.material_name
            unit_key = (name, item.unit)
            materials[unit_key] = materials.get(unit_key, 0) + (item.quantity_used or 0)
    if materials:
        lines.append("")
        lines.append("使用材料: " + "、".join(
            f"{name} {_num(qty)}{unit}" for (name, unit), qty in materials.items()
        ))

    weathers = list(OrderedDict.fromkeys(
        r.get_weather_display() for r in reports if r.weather
    ))
    if weathers:
        lines.append("天候: " + "・".join(weathers))
    memos = list(OrderedDict.fromkeys((r.memo or "").strip() for r in reports if r.memo))
    if memos:
        lines.append("その他: " + " ／ ".join(memos))
    return "\n".join(lines)


def _grid_style(extra=()):
    return TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, _LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), _FONT),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        *extra,
    ])


def _header_tables(site, day, page_no, pages):
    title = "作　　業　　日　　報" + (f"　（{page_no}/{pages}）" if pages > 1 else "")
    orderer = str(site.customer) if site.customer_id else ""
    return [
        Table([[_p(title, 16, TA_CENTER)]], colWidths=[_W], rowHeights=[12 * mm],
              style=_grid_style()),
        Table(
            [[_p("現場名", 10, TA_CENTER), _fit(site.name, 92 * mm, 8 * mm, 11, 7),
              _p("発注先", 10, TA_CENTER), _fit(orderer, 52 * mm, 8 * mm, 10, 6)],
             [_p("年月日", 10, TA_CENTER), _p(_reiwa_date(day), 11), "", ""]],
            colWidths=[30 * mm, 98 * mm, 24 * mm, 34 * mm], rowHeights=[9 * mm, 9 * mm],
            style=_grid_style([("SPAN", (1, 1), (3, 1))]),
        ),
    ]


def _own_table(rows, summary, total):
    cols = [6 * mm, 30 * mm, 44 * mm, 16 * mm, 14 * mm, 76 * mm]
    data = [[
        _p("作業員名", 9, TA_CENTER), "", _p("作業時間", 9, TA_CENTER),
        _p("残業", 9, TA_CENTER), _p("宿泊", 9, TA_CENTER), _p("作業内容・使用材料", 9, TA_CENTER),
    ]]
    content = _fit(summary, cols[5] - 6, OWN_ROWS * 7 * mm - 4, max_size=9, min_size=5.5)
    for i in range(OWN_ROWS):
        r = rows[i] if i < len(rows) else None
        data.append([
            "",
            _fit(str(r.worker), cols[1] - 6, 6.5 * mm, 9, 6) if r else "",
            _p(_time_range(r), 9, TA_CENTER) if r else _p("：　　～　　：", 9, TA_CENTER),
            _p(_overtime(r) if r else "h", 9, TA_RIGHT),
            "",
            content if i == 0 else "",
        ])
    data.append([_p("合計", 9, TA_CENTER), "", _p(f"{total}　人", 10, TA_RIGHT), "", "", ""])
    data.append([_p(TRANSPORT_OWN, 9), "", "", "", "", ""])
    last = OWN_ROWS
    return Table(
        data, colWidths=cols,
        rowHeights=[7 * mm] + [7 * mm] * OWN_ROWS + [7 * mm, 7 * mm],
        style=_grid_style([
            ("SPAN", (0, 0), (1, 0)),
            ("SPAN", (5, 1), (5, last)),
            ("VALIGN", (5, 1), (5, last), "TOP"),
            ("SPAN", (0, last + 1), (1, last + 1)),
            ("SPAN", (2, last + 1), (3, last + 1)),
            ("SPAN", (4, last + 1), (5, last + 1)),
            ("SPAN", (0, last + 2), (5, last + 2)),
        ]),
    )


def _partner_table(blocks, total):
    """blocks は [(会社名, [日報...], 会社の人数) を最大 3 つ]。空の枠も原本どおり描く。"""
    cols = [30 * mm, 30 * mm, 18 * mm, 44 * mm, 44 * mm, 20 * mm]
    row_h = 6.5 * mm
    heads = ("会社名", "作業員名", "人数", "作業時間", "作業内容", "承認印")
    data = [[_p(t, 9, TA_CENTER) for t in heads]]
    heights = [7 * mm]
    spans = []
    for index, cap in enumerate(PARTNER_BLOCK_ROWS):
        company, rows, count = blocks[index] if index < len(blocks) else ("", [], 0)
        top = len(data)
        for i in range(cap):
            r = rows[i] if i < len(rows) else None
            data.append([
                _fit(company, cols[0] - 6, cap * row_h - 4, 9, 6) if i == 0 else "",
                _fit(str(r.worker), cols[1] - 6, row_h - 2, 9, 6) if r else "",
                _p(f"{count}　人" if count else "人", 9, TA_RIGHT) if i == 0 else "",
                _p(_time_range(r) if r else "～", 8.5, TA_CENTER),
                _fit((r.work_description or "").replace("\n", " "), cols[4] - 6, row_h - 2, 8, 5.5)
                if r else "",
                "",
            ])
            heights.append(row_h)
        bottom = len(data) - 1
        spans += [("SPAN", (0, top), (0, bottom)), ("SPAN", (2, top), (2, bottom)),
                  ("SPAN", (5, top), (5, bottom)), ("VALIGN", (0, top), (0, bottom), "TOP")]
        data.append([_p(TRANSPORT_PARTNER, 8.5), "", "", "", "", ""])
        heights.append(row_h)
        spans.append(("SPAN", (0, len(data) - 1), (5, len(data) - 1)))
    data.append([_p("合計", 9, TA_CENTER), "", _p(f"{total}　人", 10, TA_RIGHT), "", "", ""])
    heights.append(7 * mm)
    last = len(data) - 1
    spans += [("SPAN", (0, last), (1, last)), ("SPAN", (3, last), (5, last))]
    return Table(data, colWidths=cols, rowHeights=heights, style=_grid_style(spans))


def _signature_table():
    return Table(
        [["", _p("現場代理人又は責任者", 10, TA_CENTER)], ["", ""]],
        colWidths=[_W - 80 * mm, 80 * mm], rowHeights=[8 * mm, 7 * mm],
        style=TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, _LINE),
            # 原本は「現場代理人又は責任者」の文字の下に署名用の線がある
            ("LINEBELOW", (1, 0), (1, 0), 0.6, _LINE),
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ]),
    )


def _partner_pages(partner_reports):
    """協力会社の日報を 3 社ぶんの枠（3 行・2 行・2 行）に順に詰め、用紙ごとの枠のリストにする。

    1 社の人数が枠の行数より多いときは、次の枠（足りなければ次の用紙）に同じ会社名で続ける。
    """
    by_company = OrderedDict()
    for r in partner_reports:
        name = str(r.partner) if r.partner_id else "（会社名なし）"
        by_company.setdefault(name, []).append(r)

    queue = [(name, list(rows), len(rows)) for name, rows in by_company.items()]
    pages, blocks = [], []
    while queue:
        name, rows, count = queue[0]
        cap = PARTNER_BLOCK_ROWS[len(blocks)]
        blocks.append((name, rows[:cap], count))
        rest = rows[cap:]
        if rest:
            queue[0] = (name, rest, count)
        else:
            queue.pop(0)
        if len(blocks) == len(PARTNER_BLOCK_ROWS):
            pages.append(blocks)
            blocks = []
    if blocks:
        pages.append(blocks)
    return pages


def _sort_key(report):
    from apps.workers.models import employee_code_sort_key

    return (employee_code_sort_key(report.worker.employee_code), report.worker.name, report.pk)


def group_reports(reports):
    """同じ日・同じ現場の日報をまとめる。並びは渡された順（最初に出た日・現場の順）。"""
    groups = OrderedDict()
    for r in reports:
        groups.setdefault((r.report_date, r.site_id), []).append(r)
    return list(groups.values())


def _sheet_pages(reports):
    """1 まとまり（同じ日・同じ現場）の日報を、用紙ごとの要素のリストにする。"""
    reports = sorted(reports, key=_sort_key)
    own = [r for r in reports if not r.is_partner_worker]
    partners = [r for r in reports if r.is_partner_worker]
    own_pages = [own[i:i + OWN_ROWS] for i in range(0, len(own), OWN_ROWS)] or [[]]
    partner_pages = _partner_pages(partners) or [[]]
    total_pages = max(len(own_pages), len(partner_pages))
    summary = _work_summary(own)

    site, day = reports[0].site, reports[0].report_date
    pages = []
    for n in range(total_pages):
        rows = own_pages[n] if n < len(own_pages) else []
        blocks = partner_pages[n] if n < len(partner_pages) else []
        pages.append([
            *_header_tables(site, day, n + 1, total_pages),
            _own_table(rows, summary if n == 0 else "（1 枚目に記載）", len(own)),
            _partner_table(blocks, len(partners)),
            _signature_table(),
        ])
    return pages, reports


def _status_line(reports):
    counts = OrderedDict()
    for r in reports:
        label = r.get_status_display()
        counts[label] = counts.get(label, 0) + 1
    parts = [f"{label} {n}件" for label, n in counts.items()]
    approvers = OrderedDict()
    for r in reports:
        if r.approved_by_id:
            user = r.approved_by
            approvers[user.get_full_name() or user.first_name or user.username] = True
    text = "状態: " + "・".join(parts)
    if approvers:
        text += "　承認: " + "・".join(approvers)
    return text


def generate_reports_pdf(reports):
    """日報のリストを、同じ日・同じ現場ごとに原本の様式の用紙にした PDF のバイト列で返す。"""
    buf = BytesIO()
    printed_at = timezone.localtime()
    notes = {}  # 用紙番号 → 下余白に出す状態・承認

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(_FONT, 7.5)
        canvas.setFillColor(colors.HexColor("#475569"))
        canvas.drawString(12 * mm, 8 * mm, notes.get(doc.page, ""))
        canvas.drawRightString(
            A4[0] - 12 * mm, 8 * mm, f"出力 {printed_at:%Y/%m/%d %H:%M}　{doc.page} ページ",
        )
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
        title="作業日報", author="KEM",
    )

    elements = []
    page = 0
    for group in group_reports(reports):
        pages, ordered = _sheet_pages(group)
        line = _status_line(ordered)
        for page_elements in pages:
            if page:
                elements.append(PageBreak())
            page += 1
            notes[page] = line
            elements += page_elements
    doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
