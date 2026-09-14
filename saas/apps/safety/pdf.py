"""安全書類の PDF（ADR-0061）。様式は会社の Excel「現場ごとの書類一覧.xlsx」の2シートに合わせる。

- KY用紙（安全作業指示書）: 現場・日ごとに1枚。参加者の欄は左右2列×10行（1枚20人）。
  21人目からは次の用紙に参加者の欄だけ続ける
- 安全作業確認書（新規入場者用）: 作業員1人1枚
- 危険度は「大・中・小」を書き、選んだものを赤い丸で囲む（様式の「○で囲む」）。
  答えを選ぶ質問は、選んだ答えを赤い下線で示す
- サインは画面で書いた PNG を、縦横比を保って枠に収めて描く

日本語フォントと表の枠の書き方は日報の PDF（apps/reports/pdf.py）と同じものを使う。
"""

import base64
import binascii
import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import (
    Flowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from apps.reports.pdf import _FONT, _W, WEEKDAYS, _grid_style, _p, _style
from apps.safety.formats import (
    ASBESTOS_NOTE,
    ENTRY_KIND,
    ENTRY_PLEDGES,
    ENTRY_RULES_TITLE,
    ENTRY_TITLE,
    ILLNESS_QUESTION,
    KENTAIKYO_NOTE,
    KY_CHECK_POINTS,
    KY_NOTES,
    KY_RISK_CRITERIA,
    KY_RISK_LEGEND,
    KY_TITLE,
    PRIVACY_NOTE,
    QUESTIONS,
    RISK_LEVELS,
    RISK_ROWS,
    SAFETY_RULES,
    SC5_ITEMS,
    SC5_ROWS,
    SHOCK_QUESTION,
    SHOCK_RULES,
    SHOCK_RULES_TITLE,
)
from apps.safety.models import EntryConfirmation
from apps.safety.services import user_display_name

RED = colors.HexColor("#d7262e")
_BLACK = colors.black
PARTICIPANT_ROWS = 10  # 左右2列なので1枚20人
NOTE_HEIGHTS = (8 * mm, 8 * mm, 10 * mm, 10 * mm)
_PNG_PREFIX = "data:image/png;base64,"


# ---------------------------------------------------------------------------
# 部品
# ---------------------------------------------------------------------------


def _signature_image(data_url):
    if not data_url or not data_url.startswith(_PNG_PREFIX):
        return None
    try:
        reader = ImageReader(BytesIO(base64.b64decode(data_url[len(_PNG_PREFIX) :])))
        reader.getSize()
    except (binascii.Error, ValueError, OSError):
        return None  # 読めないサインは空欄にする（PDF 全体は出す）
    return reader


class Signature(Flowable):
    """画面で書いたサインを、縦横比を保って枠（width × height）の真ん中に描く。

    サインが無い・読めないときは何も描かない。
    """

    def __init__(self, data_url, width, height):
        super().__init__()
        self.width = width
        self.height = height
        self.image = _signature_image(data_url)

    def wrap(self, avail_width, avail_height):
        return self.width, self.height

    def draw(self):
        if self.image is None:
            return
        image_width, image_height = self.image.getSize()
        if not image_width or not image_height:
            return
        scale = min(self.width / image_width, self.height / image_height)
        width, height = image_width * scale, image_height * scale
        self.canv.drawImage(
            self.image,
            (self.width - width) / 2,
            (self.height - height) / 2,
            width,
            height,
            mask="auto",
        )


class LevelChoice(Flowable):
    """「大・中・小」を並べ、選んだ危険度を赤い丸で囲む。"""

    def __init__(self, level, width, height, size=8):
        super().__init__()
        self.level = level
        self.width = width
        self.height = height
        self.size = size

    def wrap(self, avail_width, avail_height):
        return self.width, self.height

    def draw(self):
        canvas = self.canv
        size = self.size
        parts = []
        for i, level in enumerate(RISK_LEVELS):
            if i:
                parts.append(("・", False))
            parts.append((level, level == self.level))
        widths = [pdfmetrics.stringWidth(text, _FONT, size) for text, _ in parts]
        x = (self.width - sum(widths)) / 2
        y = (self.height - size) / 2 + size * 0.12
        canvas.saveState()
        canvas.setFont(_FONT, size)
        for (text, selected), width in zip(parts, widths, strict=True):
            canvas.drawString(x, y, text)
            if selected:
                canvas.setStrokeColor(RED)
                canvas.setLineWidth(0.9)
                canvas.circle(x + width / 2, y + size * 0.35, size * 0.72, stroke=1, fill=0)
            x += width
        canvas.restoreState()


def _para(markup, size=8.5, align=None, leading=None):
    """書式（赤い下線など）を含む文。markup のうち利用者が入れた文字はエスケープ済みであること。"""
    return Paragraph(markup, _style(size, align, leading))


def _fit_text(text, width, height, max_size=9, min_size=5):
    """枠（width × height）に収まるよう文字を小さくする。最小でも入らなければ末尾を省略する。"""
    body = escape(str(text or "")).replace("\n", "<br/>")
    size = max_size
    while size >= min_size:
        para = Paragraph(body, _style(size))
        if para.wrap(width, height)[1] <= height:
            return para
        size -= 0.5
    lines = str(text or "").split("\n")
    while lines:
        lines.pop()
        body = escape("\n".join(lines) + "\n…（以下略。全文はアプリで確認）").replace(
            "\n", "<br/>"
        )
        para = Paragraph(body, _style(min_size))
        if para.wrap(width, height)[1] <= height:
            return para
    return Paragraph("…（全文はアプリで確認）", _style(min_size))


def _vertical(text, size=9):
    """縦書きの見出し（1字ずつ改行）。"""
    return Paragraph(
        "<br/>".join(escape(ch) for ch in text),
        _style(size, TA_CENTER, size * 1.15),
    )


def _plain(extra=()):
    """枠の無い表。"""
    return TableStyle(
        [
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 0), (-1, -1), _FONT),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            *extra,
        ]
    )


def _no_padding(extra=()):
    return TableStyle(
        [
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            *extra,
        ]
    )


def _reiwa(day):
    if day is None:
        return "令和　　年　　月　　日"
    if day.year >= 2019:
        return f"令和{day.year - 2018}年{day.month}月{day.day}日"
    return f"{day.year}年{day.month}月{day.day}日"


def _birth_date(day):
    """生年月日を和暦で（昭和・平成・令和）。"""
    if day is None:
        return "Ｓ・Ｈ　　年　　月　　日"
    for start, era, offset in (
        (datetime.date(2019, 5, 1), "令和", 2018),
        (datetime.date(1989, 1, 8), "平成", 1988),
        (datetime.date(1926, 12, 25), "昭和", 1925),
    ):
        if day >= start:
            return f"{era}{day.year - offset}年{day.month}月{day.day}日"
    return f"{day.year}年{day.month}月{day.day}日"


def _clock(value):
    return f"{value.hour}：{value.minute:02d}" if value else "　　"


def _blank(value):
    return "　" if value in (None, "") else str(value)


def _mark(label, selected):
    """答えの選択肢。選んだものは赤い下線で示す。"""
    text = escape(label)
    return f'<font color="#d7262e"><u>{text}</u></font>' if selected else text


# ---------------------------------------------------------------------------
# KY用紙（安全作業指示書）
# ---------------------------------------------------------------------------


def _ky_header(sheet):
    site = sheet.site
    day = sheet.work_date
    written = timezone.localtime(sheet.updated_at).date() if sheet.updated_at else day
    underline = 0.6
    title = Table(
        [
            [
                _p("安 全 作 業 指 示 書", 16, TA_CENTER),
                _p("記入日：", 9, TA_RIGHT),
                _p(_reiwa(written), 9),
            ]
        ],
        colWidths=[118 * mm, 20 * mm, 48 * mm],
        rowHeights=[10 * mm],
        style=_plain(),
    )
    info = Table(
        [
            [
                _p("工事件名：", 9),
                _fit_text(site.name, 96 * mm, 6 * mm, 9, 6),
                _p("会社名：", 9),
                _fit_text(sheet.company.name, 42 * mm, 6 * mm, 9, 6),
            ]
        ],
        colWidths=[20 * mm, 100 * mm, 20 * mm, 46 * mm],
        rowHeights=[7 * mm],
        style=_plain(
            [
                ("LINEBELOW", (1, 0), (1, 0), underline, _BLACK),
                ("LINEBELOW", (3, 0), (3, 0), underline, _BLACK),
            ]
        ),
    )
    work = Table(
        [
            [
                _p("作業日：", 9),
                _p(f"{_reiwa(day)}（{WEEKDAYS[day.weekday()]}）", 9),
                _p("予定人数", 9, TA_CENTER),
                _p("作業班名：", 9),
                _fit_text(sheet.crew_name, 50 * mm, 6 * mm, 9, 6),
            ],
            [
                _p("作業時間：", 9),
                _p(f"{_clock(sheet.work_start)}　～　{_clock(sheet.work_end)}", 9),
                _p(f"{_blank(sheet.planned_headcount)} 人", 9, TA_RIGHT),
                _p("作業責任者：", 9),
                _fit_text(sheet.leader_name, 50 * mm, 6 * mm, 9, 6),
            ],
        ],
        colWidths=[20 * mm, 66 * mm, 24 * mm, 22 * mm, 54 * mm],
        rowHeights=[7 * mm, 7 * mm],
        style=_plain(
            [
                ("BOX", (2, 0), (2, 1), 0.9, _BLACK),
                ("LINEBELOW", (1, 0), (1, 1), underline, _BLACK),
                ("LINEBELOW", (4, 0), (4, 1), underline, _BLACK),
            ]
        ),
    )
    return [title, info, work, Spacer(1, 2 * mm)]


def _instruction_table(sheet):
    cols = [8 * mm, 7 * mm, 80 * mm, 7 * mm, 58 * mm, 26 * mm]
    points = "\n".join([*KY_CHECK_POINTS, f"⑦{sheet.extra_check_7}", f"⑧{sheet.extra_check_8}"])
    data = [
        [
            _vertical("安全作業指示", 10),
            _p("作業場所と作業内容", 9, TA_CENTER),
            "",
            _p("作業責任者からの安全指示", 9, TA_CENTER),
            "",
            "",
        ],
        [
            "",
            _fit_text(sheet.work_content, 83 * mm, 22 * mm, 9, 6),
            "",
            _fit_text(sheet.safety_instructions, 87 * mm, 22 * mm, 9, 6),
            "",
            "",
        ],
        [
            "",
            _vertical("作成時の注意ポイント", 5.5),
            _fit_text(points, 77 * mm, 30 * mm, 7, 5),
            _vertical("指導事項", 8),
            _fit_text(sheet.guidance, 80 * mm, 21 * mm, 8, 6),
            "",
        ],
        [
            "",
            "",
            "",
            "",
            _p("現場代理人 または代務者のサイン", 7),
            Signature(sheet.guidance_signature, 23 * mm, 6.5 * mm),
        ],
    ]
    style = _grid_style(
        [
            ("SPAN", (0, 0), (0, 3)),
            ("SPAN", (1, 0), (2, 0)),
            ("SPAN", (3, 0), (5, 0)),
            ("SPAN", (1, 1), (2, 1)),
            ("SPAN", (3, 1), (5, 1)),
            ("SPAN", (1, 2), (1, 3)),
            ("SPAN", (2, 2), (2, 3)),
            ("SPAN", (3, 2), (3, 3)),
            ("SPAN", (4, 2), (5, 2)),
            ("VALIGN", (1, 1), (-1, 1), "TOP"),
            ("VALIGN", (2, 2), (2, 2), "TOP"),
            ("VALIGN", (4, 2), (4, 2), "TOP"),
            ("BOX", (0, 0), (-1, -1), 1.4, _BLACK),
        ]
    )
    return Table(data, colWidths=cols, rowHeights=[6 * mm, 23 * mm, 23 * mm, 8 * mm], style=style)


def _risk_table(sheet):
    cols = [8 * mm, 90 * mm, 16 * mm, 58 * mm, 14 * mm]
    rows = list(sheet.risks or [])[:RISK_ROWS]
    rows += [{}] * (RISK_ROWS - len(rows))
    data = [
        [
            _vertical("ＴＢＭ－ＲＫＹ", 9),
            _fit_text("評価基準\n" + KY_RISK_CRITERIA, 101 * mm, 15 * mm, 7, 5),
            "",
            _fit_text("危険度\n" + KY_RISK_LEGEND, 67 * mm, 15 * mm, 7, 5),
            "",
        ],
        [
            "",
            _p("予想される危険（リスク）【これが危険のポイントだ】", 8, TA_CENTER),
            _p("危険度\n（○で囲む）", 6.5, TA_CENTER),
            _p("危険（リスク）の低減措置【私達はこうする】", 8, TA_CENTER),
            _p("作業中確認\n（○印）", 6.5, TA_CENTER),
        ],
    ]
    for row in rows:
        data.append(
            [
                "",
                _fit_text(row.get("hazard", ""), 87 * mm, 6.5 * mm, 9, 6),
                LevelChoice(row.get("level", ""), 14 * mm, 6.5 * mm),
                _fit_text(row.get("measure", ""), 55 * mm, 6.5 * mm, 8, 5),
                _p("○" if row.get("checked") else "", 10, TA_CENTER),
            ]
        )
    style = _grid_style(
        [
            ("SPAN", (0, 0), (0, -1)),
            ("SPAN", (1, 0), (2, 0)),
            ("SPAN", (3, 0), (4, 0)),
            ("LEFTPADDING", (2, 2), (2, -1), 1),
            ("RIGHTPADDING", (2, 2), (2, -1), 1),
            ("BOX", (0, 0), (-1, -1), 1.4, _BLACK),
        ]
    )
    return Table(
        data,
        colWidths=cols,
        rowHeights=[16 * mm, 9 * mm] + [7.5 * mm] * RISK_ROWS,
        style=style,
    )


def _sc5_table(sheet):
    cols = [7 * mm, 75 * mm, 16 * mm]
    checks = list(sheet.sc5_checks or [])
    items = [*SC5_ITEMS, sheet.sc5_extra_5, sheet.sc5_extra_6][:SC5_ROWS]
    data = [[_p("ＳＣ－５確認項目", 9, TA_CENTER), "", _p("朝礼時確認\n（○印）", 6.5, TA_CENTER)]]
    for i, text in enumerate(items):
        checked = i < len(checks) and checks[i]
        data.append(
            [
                _p(str(i + 1), 8, TA_CENTER),
                _fit_text(text, 72 * mm, 6 * mm, 7, 5),
                _p("○" if checked else "", 10, TA_CENTER),
            ]
        )
    data.append([_p("記入時の注意事項", 9, TA_CENTER), "", ""])
    for i, note in enumerate(KY_NOTES):
        data.append(
            [
                _p(str(i + 1), 8, TA_CENTER),
                _fit_text(note, 88 * mm, NOTE_HEIGHTS[i] - 1 * mm, 6.5, 5),
                "",
            ]
        )
    notes_start = 1 + SC5_ROWS + 1
    style = _grid_style(
        [
            ("SPAN", (0, 0), (1, 0)),
            ("SPAN", (0, notes_start - 1), (2, notes_start - 1)),
            *[("SPAN", (1, r), (2, r)) for r in range(notes_start, notes_start + len(KY_NOTES))],
        ]
    )
    heights = [8 * mm] + [6.5 * mm] * SC5_ROWS + [6 * mm] + list(NOTE_HEIGHTS)
    return Table(data, colWidths=cols, rowHeights=heights, style=style)


def _participant_header():
    return [
        _p("氏名（自筆ｻｲﾝ）", 7, TA_CENTER),
        _p("健康\n状態", 5.5, TA_CENTER),
        _p("検電\n器", 5.5, TA_CENTER),
    ]


def _participant_cells(participant):
    if participant is None:
        return ["", "", ""]
    if participant.signature:
        name = Signature(participant.signature, 28 * mm, 5.2 * mm)
    else:
        name = _fit_text(participant.worker.name, 28 * mm, 5.5 * mm, 8, 5)
    return [
        name,
        _p(participant.health_mark, 9, TA_CENTER),
        _p(participant.tester_mark, 9, TA_CENTER),
    ]


def _participants_table(participants, rows=PARTICIPANT_ROWS, row_height=6.2 * mm):
    cols = [30 * mm, 7 * mm, 7 * mm, 30 * mm, 7 * mm, 7 * mm]
    data = [_participant_header() + _participant_header()]
    for r in range(rows):
        left = participants[r] if r < len(participants) else None
        right = participants[rows + r] if rows + r < len(participants) else None
        data.append(_participant_cells(left) + _participant_cells(right))
    style = _grid_style(
        [
            ("LEFTPADDING", (0, 0), (-1, -1), 1),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1),
        ]
    )
    return Table(data, colWidths=cols, rowHeights=[8 * mm] + [row_height] * rows, style=style)


def _remarks_table(sheet, count):
    data = [
        [
            _vertical("備考", 8),
            _fit_text(sheet.remarks, 49 * mm, 17 * mm, 8, 5),
            _p("参加人数", 8, TA_CENTER),
        ],
        ["", "", _p(f"{count} 人", 10, TA_RIGHT)],
    ]
    style = _grid_style(
        [
            ("SPAN", (0, 0), (0, 1)),
            ("SPAN", (1, 0), (1, 1)),
            ("VALIGN", (1, 0), (1, 0), "TOP"),
        ]
    )
    return Table(
        data,
        colWidths=[8 * mm, 52 * mm, 28 * mm],
        rowHeights=[10 * mm, 9 * mm],
        style=style,
    )


def _middle_table(sheet, participants, count):
    return Table(
        [[_sc5_table(sheet), [_participants_table(participants), _remarks_table(sheet, count)]]],
        colWidths=[98 * mm, 88 * mm],
        style=_no_padding([("BOX", (0, 0), (-1, -1), 1.4, _BLACK)]),
    )


def _signoff_table(sheet):
    confirm = Table(
        [
            [_vertical("確認", 9), _p("現場代理人または代務者", 8, TA_CENTER)],
            ["", Signature(sheet.confirm_signature, 40 * mm, 11 * mm)],
        ],
        colWidths=[8 * mm, 46 * mm],
        rowHeights=[6 * mm, 13 * mm],
        style=_grid_style([("SPAN", (0, 0), (0, 1))]),
    )
    completion = Table(
        [
            [_vertical("作業完了報告", 6), _p("作業責任者", 8, TA_CENTER)],
            ["", Signature(sheet.completion_signature, 34 * mm, 11 * mm)],
        ],
        colWidths=[8 * mm, 40 * mm],
        rowHeights=[6 * mm, 13 * mm],
        style=_grid_style([("SPAN", (0, 0), (0, 1))]),
    )
    patrol_sign = Table(
        [
            [
                _p("現場代理人 または代務者のサイン", 6.5),
                Signature(sheet.patrol_signature, 22 * mm, 7.5 * mm),
            ]
        ],
        colWidths=[40 * mm, 24 * mm],
        rowHeights=[9 * mm],
        style=_plain(),
    )
    patrol = Table(
        [
            [
                _p("現場巡視\n指導記録", 6.5, TA_CENTER),
                _fit_text(sheet.patrol_record, 60 * mm, 9 * mm, 7, 5),
            ],
            ["", patrol_sign],
        ],
        colWidths=[12 * mm, 64 * mm],
        rowHeights=[10 * mm, 9 * mm],
        style=_grid_style(
            [
                ("SPAN", (0, 0), (0, 1)),
                ("LEFTPADDING", (1, 1), (1, 1), 0),
                ("RIGHTPADDING", (1, 1), (1, 1), 0),
                ("TOPPADDING", (1, 1), (1, 1), 0),
                ("BOTTOMPADDING", (1, 1), (1, 1), 0),
            ]
        ),
    )
    return Table(
        [[confirm, "", completion, "", patrol]],
        colWidths=[54 * mm, 4 * mm, 48 * mm, 4 * mm, 76 * mm],
        style=_no_padding(),
    )


def generate_ky_pdf(sheet):
    """KY用紙（安全作業指示書）1枚ぶんの PDF のバイト列を返す。

    参加者が20人を超えたら、次の用紙に参加者の欄だけ続ける。
    """
    participants = list(sheet.participants.select_related("worker").order_by("signed_at", "pk"))
    per_page = PARTICIPANT_ROWS * 2
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm,
        title=KY_TITLE,
        author="KEM",
    )
    elements = [
        *_ky_header(sheet),
        _instruction_table(sheet),
        _risk_table(sheet),
        _middle_table(sheet, participants[:per_page], len(participants)),
        Spacer(1, 2 * mm),
        _signoff_table(sheet),
        Spacer(1, 1 * mm),
        _p(ASBESTOS_NOTE, 6.5),
    ]
    for start in range(per_page, len(participants), per_page):
        elements += [
            PageBreak(),
            _p(f"{KY_TITLE}（参加者のつづき）　{_reiwa(sheet.work_date)}　{sheet.site.name}", 11),
            Spacer(1, 3 * mm),
            _participants_table(participants[start : start + per_page]),
        ]
    doc.build(elements)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 安全作業確認書（新規入場者用）
# ---------------------------------------------------------------------------


def _entry_header(confirmation):
    site = confirmation.site
    worker = confirmation.worker
    underline = 0.6
    name_cell = Table(
        [
            [
                _fit_text(worker.name, 28 * mm, 7 * mm, 11, 7),
                Signature(confirmation.signature, 32 * mm, 8.5 * mm),
                _p("自筆ｻｲﾝ", 6, TA_RIGHT),
            ]
        ],
        colWidths=[30 * mm, 34 * mm, 2 * mm],
        rowHeights=[9 * mm],
        style=_no_padding(
            [("VALIGN", (0, 0), (-1, -1), "MIDDLE")],
        ),
    )
    return Table(
        [
            [
                _p("工事件名", 9),
                _fit_text(site.name, 70 * mm, 12 * mm, 9, 6),
                "",
                _p("所属会社名", 9),
                _fit_text(confirmation.company.name, 62 * mm, 6 * mm, 9, 6),
            ],
            [
                "",
                "",
                "",
                _p("（ふりがな）", 7),
                _fit_text(confirmation.name_kana, 62 * mm, 5 * mm, 8, 5),
            ],
            [
                _p("現場代理人", 9),
                _p(f"{user_display_name(site.manager)}　殿", 9),
                "",
                _p("氏　名", 9),
                name_cell,
            ],
            ["", "", "", _p("生年月日", 9), _p(_birth_date(confirmation.birth_date), 9)],
        ],
        colWidths=[20 * mm, 72 * mm, 6 * mm, 22 * mm, 66 * mm],
        rowHeights=[7 * mm, 6 * mm, 10 * mm, 7 * mm],
        style=_plain(
            [
                ("SPAN", (0, 0), (0, 1)),
                ("SPAN", (1, 0), (1, 1)),
                ("LINEBELOW", (0, 1), (1, 1), underline, _BLACK),
                ("LINEBELOW", (0, 2), (1, 2), underline, _BLACK),
                ("LINEBELOW", (3, 0), (4, 0), underline, _BLACK),
                ("LINEBELOW", (3, 2), (4, 2), underline, _BLACK),
                ("LINEBELOW", (3, 3), (4, 3), underline, _BLACK),
            ]
        ),
    )


def _shock_box(confirmation):
    answer = confirmation.shock_education
    lines = [
        _para(
            f'<font color="#d7262e">{escape(SHOCK_QUESTION)}（{_mark("はい", answer is True)}・'
            f"{_mark('いいえ', answer is False)}）</font>",
            8,
            leading=10,
        ),
        _para(f'<font color="#d7262e">{escape(SHOCK_RULES_TITLE)}</font>', 8, leading=10),
        *[
            _para(f'<font color="#d7262e">　　　{escape(rule)}</font>', 8, leading=10)
            for rule in SHOCK_RULES
        ],
    ]
    return Table(
        [[lines]],
        colWidths=[_W],
        style=TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1.2, RED),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        ),
    )


def _entry_info_tables(confirmation):
    c = confirmation

    def tel(phone):
        return f"TEL　{phone}" if phone else "TEL"

    info = Table(
        [
            [
                _p("元 請 会 社 名", 8.5, TA_CENTER),
                _fit_text(c.company.name, 53 * mm, 5 * mm, 9, 6),
                _p("あなたの\n直属(自社)の職長名", 7.5, TA_CENTER),
                _fit_text(c.foreman_name, 61 * mm, 10 * mm, 9, 6),
            ],
            [
                _p("１次協力会社名", 8.5, TA_CENTER),
                _fit_text(c.partner_company_1, 53 * mm, 5 * mm, 9, 6),
                "",
                "",
            ],
            [
                _p("２次協力会社名", 8.5, TA_CENTER),
                _fit_text(c.partner_company_2, 53 * mm, 5 * mm, 9, 6),
                _p("当該現場までの\n使用交通機関", 7.5, TA_CENTER),
                _fit_text(c.transport, 61 * mm, 10 * mm, 9, 6),
            ],
            [
                _p(f"（{_blank(c.partner_company_n_tier)}）次協力会社名", 8.5, TA_CENTER),
                _fit_text(c.partner_company_n, 53 * mm, 5 * mm, 9, 6),
                "",
                "",
            ],
            [
                _p("現　　住　　所", 8.5, TA_CENTER),
                _fit_text(c.address, 87 * mm, 5 * mm, 9, 6),
                "",
                _p(tel(c.phone), 8.5),
            ],
            [
                _p("緊急連絡者氏名", 8.5, TA_CENTER),
                _fit_text(c.emergency_contact_name, 150 * mm, 5 * mm, 9, 6),
                "",
                "",
            ],
            [
                _p("同 上 者 住 所", 8.5, TA_CENTER),
                _fit_text(c.emergency_contact_address, 87 * mm, 5 * mm, 9, 6),
                "",
                _p(tel(c.emergency_contact_phone), 8.5),
            ],
        ],
        colWidths=[32 * mm, 56 * mm, 34 * mm, 64 * mm],
        rowHeights=[6 * mm] * 7,
        style=_grid_style(
            [
                ("SPAN", (2, 0), (2, 1)),
                ("SPAN", (3, 0), (3, 1)),
                ("SPAN", (2, 2), (2, 3)),
                ("SPAN", (3, 2), (3, 3)),
                ("SPAN", (1, 4), (2, 4)),
                ("SPAN", (1, 5), (3, 5)),
                ("SPAN", (1, 6), (2, 6)),
            ]
        ),
    )
    blood = f"{c.blood_type}型" if c.blood_type else ""
    health = Table(
        [
            [
                _p("経　験　年　数", 8.5, TA_CENTER),
                _p(
                    f"{_blank(c.experience_years)}　年　{_blank(c.experience_months)}　月",
                    8.5,
                    TA_RIGHT,
                ),
                _p("血液型", 8, TA_CENTER),
                _p(blood, 9, TA_CENTER),
                _p(
                    f"血圧（{_blank(c.blood_pressure_high)}）～（{_blank(c.blood_pressure_low)}）",
                    8.5,
                    TA_CENTER,
                ),
                _p(
                    f"視力　右（{_blank(c.vision_right)}）　左（{_blank(c.vision_left)}）",
                    8.5,
                    TA_CENTER,
                ),
            ]
        ],
        colWidths=[32 * mm, 34 * mm, 14 * mm, 16 * mm, 42 * mm, 48 * mm],
        rowHeights=[6 * mm],
        style=_grid_style(),
    )
    return [info, health]


def _entry_questions(confirmation):
    c = confirmation
    business = EntryConfirmation.BusinessType
    blank_answer = "　" * 12
    rows = [
        f"{escape(ILLNESS_QUESTION)}　{_mark('ない', c.has_illness is False)}，"
        f"{_mark('ある', c.has_illness is True)}（{escape(c.illness_detail) or blank_answer}）",
        f"{escape(QUESTIONS['business_type'])}　"
        f"{_mark('中小企業主(⑤へ)', c.business_type == business.SME_OWNER)}，"
        f"{_mark('一人親方(⑤へ)', c.business_type == business.SOLE_PROPRIETOR)}，"
        f"{_mark('どちらでもない（②へ）', c.business_type == business.NEITHER)}",
        f"{escape(QUESTIONS['received_employment_document'])}　"
        f"{_mark('受けた', c.received_employment_document is True)}，"
        f"{_mark('受けてない', c.received_employment_document is False)}",
        f"{escape(QUESTIONS['received_safety_education'])}　"
        f"{_mark('受けた', c.received_safety_education is True)}，"
        f"{_mark('受けてない', c.received_safety_education is False)}",
        f"{escape(QUESTIONS['paying_company'])}（{escape(c.paying_company) or blank_answer}）",
        f"{escape(QUESTIONS['special_accident_insurance'])}　"
        f"{_mark('はい(保険証写し添付)', c.special_accident_insurance is True)}，"
        f"{_mark('いいえ', c.special_accident_insurance is False)}",
        f"{escape(QUESTIONS['has_retirement_system'])}　"
        f"{_mark('はい（⑦の設問に回答不要）', c.has_retirement_system is True)}，"
        f"{_mark('いいえ', c.has_retirement_system is False)}",
    ]
    last = [
        _para(
            f"{escape(QUESTIONS['has_kentaikyo_book'])}　"
            f"{_mark('はい', c.has_kentaikyo_book is True)}，"
            f"{_mark('いいえ', c.has_kentaikyo_book is False)}",
            8.3,
        ),
        *[_para("　　　" + escape(note), 7.2, leading=8.8) for note in KENTAIKYO_NOTE],
    ]
    data = [[_para(row, 8.3)] for row in rows] + [[last]]
    return Table(
        data,
        colWidths=[_W],
        rowHeights=[6 * mm] * len(rows) + [14 * mm],
        style=_grid_style(),
    )


def generate_entry_pdf(confirmation):
    """安全作業確認書（新規入場者用）1人ぶんの PDF のバイト列を返す。"""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm,
        title=ENTRY_TITLE,
        author="KEM",
    )
    rules = [
        _para(f"（{i}）　{escape(rule)}", 7.6, leading=8.6)
        for i, rule in enumerate(SAFETY_RULES, start=1)
    ]
    elements = [
        Table(
            [["", _p(ENTRY_KIND, 8.5, TA_CENTER)]],
            colWidths=[_W - 44 * mm, 44 * mm],
            rowHeights=[6 * mm],
            style=_plain([("BOX", (1, 0), (1, 0), 0.8, _BLACK)]),
        ),
        Table(
            [[_p("安 全 作 業 確 認 書", 18, TA_CENTER)]],
            colWidths=[_W],
            rowHeights=[11 * mm],
            style=_plain(),
        ),
        Table(
            [["", _p(_reiwa(confirmation.entry_date), 10, TA_RIGHT)]],
            colWidths=[_W - 60 * mm, 60 * mm],
            rowHeights=[6 * mm],
            style=_plain(),
        ),
        _entry_header(confirmation),
        Spacer(1, 1 * mm),
        *[_para(f"<u>{escape(text)}</u>", 11, TA_CENTER) for text in ENTRY_PLEDGES],
        _p(ENTRY_RULES_TITLE, 11, TA_CENTER),
        Spacer(1, 1 * mm),
        _shock_box(confirmation),
        Table(
            [[rules]],
            colWidths=[_W],
            style=TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            ),
        ),
        Spacer(1, 1.5 * mm),
        *_entry_info_tables(confirmation),
        _entry_questions(confirmation),
        Spacer(1, 1 * mm),
        _p(PRIVACY_NOTE, 7.5, TA_CENTER),
    ]
    doc.build(elements)
    return buf.getvalue()
