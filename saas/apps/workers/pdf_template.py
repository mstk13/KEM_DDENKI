"""評価テンプレート（質問項目）のPDF出力。"""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# 日本語フォント登録
pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
_FONT = "HeiseiKakuGo-W5"

_styles = getSampleStyleSheet()

STYLE_TITLE = ParagraphStyle(
    "Title_JP", parent=_styles["Title"],
    fontName=_FONT, fontSize=16, leading=22, spaceAfter=6,
)
STYLE_H2 = ParagraphStyle(
    "H2_JP", parent=_styles["Heading2"],
    fontName=_FONT, fontSize=12, leading=16, spaceBefore=14, spaceAfter=6,
    textColor=colors.HexColor("#2b6cb0"),
)
STYLE_H3 = ParagraphStyle(
    "H3_JP", parent=_styles["Heading3"],
    fontName=_FONT, fontSize=10, leading=14, spaceBefore=10, spaceAfter=4,
)
STYLE_BODY = ParagraphStyle(
    "Body_JP", parent=_styles["Normal"],
    fontName=_FONT, fontSize=8.5, leading=13,
)
STYLE_SMALL = ParagraphStyle(
    "Small_JP", parent=_styles["Normal"],
    fontName=_FONT, fontSize=7.5, leading=11, textColor=colors.HexColor("#4a5568"),
)
STYLE_LABEL = ParagraphStyle(
    "Label_JP", parent=_styles["Normal"],
    fontName=_FONT, fontSize=7.5, leading=10, textColor=colors.HexColor("#718096"),
)


def _p(text, style=STYLE_BODY):
    return Paragraph(text, style)


def generate_template_pdf(template):
    """EvaluationTemplate のデータからPDFバイト列を生成して返す。"""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
    )

    elements = []

    # タイトル
    elements.append(_p(f"{template.name}", STYLE_TITLE))
    elements.append(_p(f"{template.company.name}　人材評価　質問項目一覧", STYLE_SMALL))
    elements.append(Spacer(1, 10))

    # 評価スケール
    if template.scale:
        elements.append(_p("評価スケール", STYLE_H2))
        scale_data = [[
            _p("値", STYLE_LABEL),
            _p("ラベル", STYLE_LABEL),
        ]]
        for s in template.scale:
            scale_data.append([
                _p(str(s.get("value", "")), STYLE_BODY),
                _p(str(s.get("label", "")), STYLE_BODY),
            ])
        t = Table(scale_data, colWidths=[40, None])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), _FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f4f8")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 8))

    # セクション別に質問項目をグループ化
    items = template.survey_items or []
    sections_order = []
    sections_map = {}
    for item in items:
        sec = item.get("section", "共通")
        if sec not in sections_map:
            sections_order.append(sec)
            sections_map[sec] = []
        sections_map[sec].append(item)

    for sec in sections_order:
        elements.append(_p(f"【{sec}】", STYLE_H2))

        for item in sections_map[sec]:
            name = item.get("name", "")
            num = item.get("num", "")
            elements.append(_p(f"{num}. {name}", STYLE_H3))

            # アンカー（基準）
            anchor_5 = item.get("anchor_5", "")
            anchor_3 = item.get("anchor_3", "")
            anchor_1 = item.get("anchor_1", "")
            if anchor_5 or anchor_3 or anchor_1:
                anchor_data = [[
                    _p("評点", STYLE_LABEL),
                    _p("行動基準", STYLE_LABEL),
                ]]
                if anchor_5:
                    anchor_data.append([_p("5 (最高)", STYLE_SMALL), _p(anchor_5, STYLE_SMALL)])
                if anchor_3:
                    anchor_data.append([_p("3 (標準)", STYLE_SMALL), _p(anchor_3, STYLE_SMALL)])
                if anchor_1:
                    anchor_data.append([_p("1 (要改善)", STYLE_SMALL), _p(anchor_1, STYLE_SMALL)])
                t = Table(anchor_data, colWidths=[60, None])
                t.setStyle(TableStyle([
                    ("FONTNAME", (0, 0), (-1, -1), _FONT),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f4f8")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ]))
                elements.append(t)
                elements.append(Spacer(1, 4))

            # 個別質問
            questions = item.get("questions", [])
            if questions:
                q_data = [[
                    _p("No.", STYLE_LABEL),
                    _p("質問", STYLE_LABEL),
                ]]
                for q in questions:
                    q_data.append([
                        _p(str(q.get("qnum", "")), STYLE_BODY),
                        _p(str(q.get("text", "")), STYLE_BODY),
                    ])
                t = Table(q_data, colWidths=[40, None])
                t.setStyle(TableStyle([
                    ("FONTNAME", (0, 0), (-1, -1), _FONT),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f4f8")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ]))
                elements.append(t)

            # 自由記述
            free_text = item.get("free_text", "")
            if free_text:
                elements.append(Spacer(1, 3))
                elements.append(_p(f"[自由記述] {free_text}", STYLE_SMALL))

            elements.append(Spacer(1, 6))

    # 総合所見
    overall = template.overall or []
    if overall:
        elements.append(_p("【総合所見】", STYLE_H2))
        o_data = [[
            _p("No.", STYLE_LABEL),
            _p("質問", STYLE_LABEL),
            _p("記入者", STYLE_LABEL),
        ]]
        for o in overall:
            writer = "本人" if o.get("by_self") else "評価者"
            o_data.append([
                _p(str(o.get("qnum", "")), STYLE_BODY),
                _p(str(o.get("text", "")), STYLE_BODY),
                _p(writer, STYLE_BODY),
            ])
        t = Table(o_data, colWidths=[40, None, 50])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), _FONT),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f4f8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(t)

    doc.build(elements)
    return buf.getvalue()
