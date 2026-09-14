"""日報の PDF 出力（ADR-0049、様式は ADR-0053）。

紙の「作業日報 原本」と同じ様式で出す。原本は 1 枚が「1 現場 × 1 日」で、
その日に入った作業員全員を並べる。アプリの日報は 1 件＝作業員 1 人なので、
同じ日・同じ現場の日報を 1 枚にまとめる。

- 自社の作業員の表は 9 行（作業員名・作業時間・通常時間・残業時間・宿泊）。超えたら次の用紙に続ける
- 作業内容は作業員の表の下に横幅いっぱいの欄を設け、その下に交通手段の行（1 つ）
- 協力会社（is_partner_worker）の欄は 3 社ぶん（3 行・2 行・2 行）。超えたら次の用紙に続ける
- アプリに無い項目（宿泊・交通手段・交通費・現場代理人の氏名）は手書き用に空けておく
- 承認印は、承認済みの日報に「釼持」の赤い判子を押す
- 原本に無いアプリの項目のうち、天候は年月日の右、工種・工程はその下の行、その他は
  作業内容の枠に書く。使用材料は書かない。状態・承認者は枠の外の下余白に出す

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
from reportlab.platypus import (
    Flowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)

pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
_FONT = "HeiseiKakuGo-W5"
# 判子の字は明朝体（印鑑らしく見えるため）
pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
_SEAL_FONT = "HeiseiMin-W3"

WEEKDAYS = ("月", "火", "水", "木", "金", "土", "日")

# 行数（自社は原本の 15 行から 6 行減らした。ADR-0053）
OWN_ROWS = 9
PARTNER_BLOCK_ROWS = (3, 2, 2)

# 承認印に押す名前（縦に 1 字ずつ）と朱色
SEAL_NAME = "釼持"
SEAL_RED = colors.HexColor("#d7262e")

_LINE = colors.black
_W = A4[0] - 24 * mm  # 用紙の左右 12mm を除いた幅（186mm）



class Seal(Flowable):
    """承認印。朱色の丸枠に名前を縦に 1 字ずつ入れた認印の形。"""

    def __init__(self, name=SEAL_NAME, diameter=11 * mm):
        super().__init__()
        self.name = name
        self.diameter = diameter
        self.width = self.height = diameter

    def wrap(self, avail_width, avail_height):
        return self.diameter, self.diameter

    def draw(self):
        c = self.canv
        r = self.diameter / 2
        c.saveState()
        c.setStrokeColor(SEAL_RED)
        c.setFillColor(SEAL_RED)
        c.setLineWidth(1.1)
        c.circle(r, r, r - 0.6, stroke=1, fill=0)
        chars = list(self.name) or [" "]
        size = min(self.diameter * 0.78 / len(chars), self.diameter * 0.46)
        top = r + size * len(chars) / 2 - size * 0.86
        # 明朝体は線が細く印刷で薄くなるので、塗りに細い縁取りを重ねて少し太らせる
        c.setLineWidth(0.35)
        for i, ch in enumerate(chars):
            width = pdfmetrics.stringWidth(ch, _SEAL_FONT, size)
            text = c.beginText(r - width / 2, top - i * size)
            text.setFont(_SEAL_FONT, size)
            text.setTextRenderMode(2)
            text.textOut(ch)
            c.drawText(text)
        c.restoreState()


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


def _time_range(report, standard_start=None):
    """作業時間「08:30～17:30」（時・分とも 2 桁）。終了が開始日の翌日以降なら「翌」を付ける。

    開始・終了が無く作業時間だけ入力された日報は、会社の所定始業（勤怠設定）から
    作業時間ぶん
    （7 時間を超えるときは休憩 1 時間を含めて）の範囲を出す。
    例: 所定 08:30・8 時間 → 08:30～17:30。
    所定始業が分からないときだけ「8 時間」のように時間数を出す（ADR-0054）。
    """
    if not report.start_time and not report.end_time:
        work, _, _ = report.hours_breakdown()
        if not work:
            return ""
        if standard_start is None:
            return f"{_num(work)} 時間"
        return _derived_range(report.report_date, standard_start, work)
    start = _clock(report.start_time)
    end = _clock(report.end_time)
    period = report.work_period() if report.start_time and report.end_time else None
    if period and period[1].date() > (report.start_date or report.report_date):
        end = f"翌{end}"
    return f"{start}～{end}"


# 作業時間だけの日報から範囲を出すときの休憩。アプリの残業計算（calculate_hours）は
# 開始～終了が 8 時間を超えると 1 時間引くので、その逆算に合わせる。
BREAK_MINUTES = 60
BREAK_THRESHOLD_MINUTES = 7 * 60


def _derived_range(day, standard_start, work_hours):
    """所定始業と作業時間から「08:30～17:30」を出す（開始・終了を入れず作業時間だけの日報用）。

    作業時間が 7 時間を超えるときは休憩 1 時間を含めて終了を出す。こうすると保存時の計算
    （8 時間を超えた範囲から休憩 1 時間を引く）で同じ作業時間に戻る。
    """
    import datetime as _dt

    minutes = int(round(float(work_hours) * 60))
    if minutes > BREAK_THRESHOLD_MINUTES:
        minutes += BREAK_MINUTES
    start = _dt.datetime.combine(day, standard_start)
    end = start + _dt.timedelta(minutes=minutes)
    end_label = _clock(end.time())
    if end.date() > day:
        end_label = f"翌{end_label}"
    return f"{_clock(standard_start)}～{end_label}"


def _standard_start(company_id):
    """所定始業。日報を書く画面の初期値と同じ（勤怠設定に保存があればその時刻、無ければ 8:30）。"""
    from apps.reports.standard_times import standard_work_times

    if not company_id:
        return None
    return standard_work_times(company_id)[0]


def _clock(value):
    """「08:30」「17:05」。時・分とも 2 桁（2026-09-14 要望で ○○:○○～○○:○○ の形に）。"""
    return f"{value:%H:%M}" if value else ""


def _hours_h(value):
    """「8h」「1.5h」。値が無ければ「h」だけ（原本の空欄と同じ）。"""
    if value is None:
        return "h"
    return f"{_num(value) or '0'}h"


def _regular(report):
    """通常時間。作業時間だけ入力された日報も作業時間から出す（ADR-0054）。"""
    _, value, _ = report.hours_breakdown()
    return _hours_h(value)


def _overtime(report):
    """残業時間。作業時間だけ入力された日報も 8 時間を超えた分を出す。無ければ「0h」。"""
    _, _, value = report.hours_breakdown()
    return _hours_h(value)


def _reiwa_date(day):
    """「令和8年9月10日 木曜日」。令和より前の日付は西暦で出す。

    年月日の右に天候・工種・工程を並べるため字間を詰める（12月31日でも 48mm に収まる）。
    """
    wd = WEEKDAYS[day.weekday()]
    if day.year >= 2019:
        return f"令和{day.year - 2018}年{day.month}月{day.day}日 {wd}曜日"
    return f"{day.year}年{day.month}月{day.day}日 {wd}曜日"


def _work_summary(reports):
    """作業内容・使用材料の枠に書く文。同じ内容は 1 回だけにする。

    天候・工種・工程は見出しの行に出すので、ここには書かない。ただし同じ用紙に
    工種・工程の違う日報が混ざるときは、どの作業内容がどれか分かるよう【工種／工程】を付ける。
    使用材料は書かない（要望。2026-09-14）。
    """
    entries = []
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
        entries.append(key)

    show_heads = len({head for head, _ in entries}) > 1
    lines = []
    for head, text in entries:
        if show_heads and head:
            lines.append(f"【{head}】")
        if text:
            lines.append(text)

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


def _distinct(values):
    """空でない値を出た順に重ねずに「・」でつなぐ。"""
    return "・".join(OrderedDict.fromkeys(v for v in values if v))


def _header_values(reports):
    """年月日の右に出す天候・工種・工程（同じ用紙の日報で違えば「・」でつなぐ）。"""
    return (
        _distinct(r.get_weather_display() for r in reports if r.weather),
        _distinct(str(r.work_type) for r in reports if r.work_type_id),
        # 工程の文字列表現は「現場 - 工程」なので名前だけ
        _distinct(r.process.name for r in reports if r.process_id),
    )


def _header_tables(site, day, page_no, pages, weather="", work_type="", process="", subtitle=""):
    title = "作　　業　　日　　報"
    if subtitle:
        title += f"　（{subtitle}）"
    if pages > 1:
        title += f"　（{page_no}/{pages}）"
    orderer = str(site.customer) if site.customer_id else ""
    return [
        Table([[_p(title, 16, TA_CENTER)]], colWidths=[_W], rowHeights=[12 * mm],
              style=_grid_style()),
        Table(
            [[_p("現場名", 10, TA_CENTER), _fit(site.name, 92 * mm, 8 * mm, 11, 7),
              _p("発注先", 10, TA_CENTER), _fit(orderer, 52 * mm, 8 * mm, 10, 6)]],
            colWidths=[30 * mm, 98 * mm, 24 * mm, 34 * mm], rowHeights=[9 * mm],
            style=_grid_style(),
        ),
        # 年月日の右に天候、その下の行に工種・工程（原本に無いアプリの項目。ADR-0053）
        Table(
            [[_p("年月日", 10, TA_CENTER), _p(_reiwa_date(day), 10),
              _p("天候", 10, TA_CENTER), _fit(weather, 32 * mm - 6, 8 * mm, 10, 6)]],
            colWidths=[30 * mm, 100 * mm, 24 * mm, 32 * mm],
            rowHeights=[9 * mm],
            style=_grid_style(),
        ),
        Table(
            [[_p("工種", 10, TA_CENTER), _fit(work_type, 63 * mm - 6, 8 * mm, 10, 6),
              _p("工程", 10, TA_CENTER), _fit(process, 63 * mm - 6, 8 * mm, 10, 6)]],
            colWidths=[30 * mm, 63 * mm, 30 * mm, 63 * mm],
            rowHeights=[9 * mm],
            style=_grid_style(),
        ),
    ]


CONTENT_HEIGHT = 45 * mm  # 作業内容の欄（横幅いっぱい）の記入部分の高さ


def _own_table(rows, total, standard_start=None):
    """自社の作業員の表: 作業員名・作業時間・通常時間・残業時間・宿泊（2026-09-14 要望）。"""
    cols = [6 * mm, 44 * mm, 50 * mm, 28 * mm, 28 * mm, 30 * mm]
    data = [[
        _p("作業員名", 9, TA_CENTER), "", _p("作業時間", 9, TA_CENTER),
        _p("通常時間", 9, TA_CENTER), _p("残業時間", 9, TA_CENTER), _p("宿泊", 9, TA_CENTER),
    ]]
    for i in range(OWN_ROWS):
        r = rows[i] if i < len(rows) else None
        data.append([
            "",
            _fit(str(r.worker), cols[1] - 6, 6.5 * mm, 9, 6) if r else "",
            _p(_time_range(r, standard_start), 9.5, TA_CENTER)
            if r else _p("：　　～　　：", 9, TA_CENTER),
            _p(_regular(r) if r else "h", 9.5, TA_RIGHT),
            _p(_overtime(r) if r else "h", 9.5, TA_RIGHT),
            "",
        ])
    data.append([_p("合計", 9, TA_CENTER), "", _p(f"{total}　人", 10, TA_RIGHT), "", "", ""])
    last = OWN_ROWS + 1
    return Table(
        data, colWidths=cols,
        rowHeights=[7 * mm] + [7 * mm] * OWN_ROWS + [7 * mm],
        style=_grid_style([
            ("SPAN", (0, 0), (1, 0)),
            ("SPAN", (0, last), (1, last)),
            ("SPAN", (3, last), (5, last)),
        ]),
    )


def _content_table(summary):
    """作業内容の欄。作業員の表の下に横幅いっぱいでとる（2026-09-14 要望）。"""
    return Table(
        [[_p("作業内容", 9, TA_CENTER)],
         [_fit(summary, _W - 8, CONTENT_HEIGHT - 4, max_size=10, min_size=6)]],
        colWidths=[_W], rowHeights=[6.5 * mm, CONTENT_HEIGHT],
        style=_grid_style([
            ("VALIGN", (0, 1), (0, 1), "TOP"),
            ("TOPPADDING", (0, 1), (0, 1), 3),
            ("LEFTPADDING", (0, 1), (0, 1), 4),
        ]),
    )


def _transport_table():
    """交通手段の行。台数と交通費はそれぞれ書き込める空欄をとる（2026-09-14 要望）。

    見本: 交通手段等 □ 車（＿＿台） □ 乗合 □ 電車 ○交通費：＿＿＿＿円 ※高速代・電車賃など
    """
    cells = [
        _p("交通手段等", 9, TA_CENTER), _p("□ 車（", 9, TA_RIGHT), "", _p("台）", 9),
        _p("□ 乗合", 9, TA_CENTER), _p("□ 電車", 9, TA_CENTER),
        _p("○交通費：", 9, TA_RIGHT), "", _p("円", 9), _p("※高速代・電車賃など", 8),
    ]
    widths = [
        22 * mm, 16 * mm, 16 * mm, 9 * mm, 17 * mm, 17 * mm, 20 * mm, 30 * mm, 7 * mm, 32 * mm,
    ]
    # 1 行だけだと空欄の下線が枠の下辺と重なって見えないので、下に細い余白の行を足す
    return Table(
        [cells, [""] * len(cells)], colWidths=widths, rowHeights=[7 * mm, 2 * mm],
        style=TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, _LINE),
            ("SPAN", (0, 0), (0, 1)),
            ("LINEAFTER", (0, 0), (0, 1), 0.6, _LINE),
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ("VALIGN", (0, 0), (0, 1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 1),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
            # 台数・交通費を書き込む空欄は下線で示す（枠の内側に引く）
            ("LINEBELOW", (2, 0), (2, 0), 0.6, _LINE),
            ("LINEBELOW", (7, 0), (7, 0), 0.6, _LINE),
        ]),
    )


def _partner_table(blocks, total, seals=(), standard_start=None):
    """blocks は [(会社名, [日報...], 会社の人数) を最大 3 つ]。空の枠も原本どおり描く。

    seals は承認印を押す枠の番号（0 始まり）。
    """
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
                _p(_time_range(r, standard_start) if r else "～", 8.5, TA_CENTER),
                _fit((r.work_description or "").replace("\n", " "), cols[4] - 6, row_h - 2, 8, 5.5)
                if r else "",
                Seal() if (i == 0 and index in seals) else "",
            ])
            heights.append(row_h)
        bottom = len(data) - 1
        spans += [("SPAN", (0, top), (0, bottom)), ("SPAN", (2, top), (2, bottom)),
                  ("SPAN", (5, top), (5, bottom)), ("VALIGN", (0, top), (0, bottom), "TOP"),
                  ("ALIGN", (5, top), (5, bottom), "CENTER")]
    # 交通手段の行は協力会社の欄には置かない（自社の欄の 1 行だけ。2026-09-14 要望）
    data.append([_p("合計", 9, TA_CENTER), "", _p(f"{total}　人", 10, TA_RIGHT), "", "", ""])
    heights.append(7 * mm)
    last = len(data) - 1
    spans += [("SPAN", (0, last), (1, last)), ("SPAN", (3, last), (5, last))]
    return Table(data, colWidths=cols, rowHeights=heights, style=_grid_style(spans))


MATERIAL_ROWS = 17  # 使用材料の用紙の行数（参考の原本と同じ）


def _materials_table(items):
    """使用材料の表: 使用材料品名・数量・メーカー・型式・備考。

    参考の原本と同じ並び（ADR-0057）。
    """
    cols = [52 * mm, 24 * mm, 32 * mm, 36 * mm, 42 * mm]
    heads = ("使用材料品名", "数量", "メーカー", "型式", "備考")
    data = [[_p(t, 9.5, TA_CENTER) for t in heads]]
    for i in range(MATERIAL_ROWS):
        m = items[i] if i < len(items) else None
        if m is None:
            data.append(["", "", "", "", ""])
            continue
        name = m.material_name or (m.material.name if m.material_id else "")
        quantity = f"{_num(m.quantity_used)}{m.unit}" if m.quantity_used is not None else m.unit
        data.append([
            _fit(name, cols[0] - 6, 11 * mm, 10, 6),
            _fit(quantity, cols[1] - 6, 11 * mm, 10, 6),
            _fit(m.maker, cols[2] - 6, 11 * mm, 10, 6),
            _fit(m.model_number, cols[3] - 6, 11 * mm, 10, 6),
            _fit(m.note, cols[4] - 6, 11 * mm, 10, 6),
        ])
    return Table(
        data, colWidths=cols, rowHeights=[8 * mm] + [12 * mm] * MATERIAL_ROWS,
        style=_grid_style([("ALIGN", (1, 1), (1, -1), "RIGHT")]),
    )


def _signature_table():
    """「現場代理人又は責任者」を左寄りに置き、右に氏名を書く線を引く（2026-09-14 要望）。"""
    # 1 行だけだと下線が枠の下辺と重なって見えないので、下に余白の行を足して枠の内側に線を引く
    return Table(
        [["", _p("現場代理人又は責任者", 10), ""], ["", "", ""]],
        colWidths=[_W - 140 * mm, 42 * mm, 98 * mm], rowHeights=[11 * mm, 4 * mm],
        style=TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, _LINE),
            # 文字から氏名の欄の右端（右の余白 10mm 手前）まで、署名用の線を 1 本
            ("LINEBELOW", (1, 0), (2, 0), 0.6, _LINE),
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
    weather, work_type, process = _header_values(reports)
    standard_start = _standard_start(reports[0].company_id)
    pages = []
    for n in range(total_pages):
        rows = own_pages[n] if n < len(own_pages) else []
        blocks = partner_pages[n] if n < len(partner_pages) else []
        pages.append([
            *_header_tables(site, day, n + 1, total_pages, weather, work_type, process),
            _own_table(rows, len(own), standard_start),
            _content_table(summary if n == 0 else "（1 枚目に記載）"),
            _transport_table(),
            _partner_table(
                blocks, len(partners), _seal_blocks(blocks, own, partners, n), standard_start,
            ),
            _signature_table(),
        ])

    # 使用材料があれば 2 枚目以降に使用材料の用紙を付ける（ADR-0057）。無ければ付けない
    items = [
        m for r in reports
        for m in r.materials_used.select_related("material").order_by("pk")
    ]
    chunks = [items[i:i + MATERIAL_ROWS] for i in range(0, len(items), MATERIAL_ROWS)]
    for k, chunk in enumerate(chunks):
        pages.append([
            *_header_tables(
                site, day, k + 1, len(chunks), weather, work_type, process, subtitle="使用材料",
            ),
            _materials_table(chunk),
        ])
    return pages, reports


def _all_approved(reports):
    return bool(reports) and all(r.status == r.Status.APPROVED for r in reports)


def _seal_blocks(blocks, own, partners, page_index):
    """承認印を押す協力会社の枠の番号。

    - 協力会社の作業員がいる: その会社の日報（同じ用紙の全員）がすべて承認済みの枠に押す
    - 協力会社の作業員がいない: 承認印の欄は協力会社の欄にしかないので、自社の日報が
      すべて承認済みなら 1 枚目の最初の枠に押す（どこにも押されないのを避ける）
    """
    if not partners:
        return (0,) if page_index == 0 and _all_approved(own) else ()
    by_company = OrderedDict()
    for r in partners:
        by_company.setdefault(str(r.partner) if r.partner_id else "（会社名なし）", []).append(r)
    return tuple(
        index for index, (company, rows, _count) in enumerate(blocks)
        if rows and _all_approved(by_company.get(company, []))
    )


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
