"""評価テンプレート（質問項目）のPDF出力。"""

from collections import OrderedDict
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from apps.workers.eval_data import QUESTION_SCALE

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

            # 5段階の行動基準（アンカー）は廃止したため出力しない

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

    # 総合所見は廃止

    doc.build(elements)
    return buf.getvalue()


# =====================================================================
# 比較型スタイル（小さめ）
# =====================================================================
STYLE_COMP_TITLE = ParagraphStyle(
    "CompTitle", parent=_styles["Title"],
    fontName=_FONT, fontSize=14, leading=18, spaceAfter=4,
)
STYLE_COMP_H2 = ParagraphStyle(
    "CompH2", parent=_styles["Heading2"],
    fontName=_FONT, fontSize=10, leading=14, spaceBefore=10, spaceAfter=4,
    textColor=colors.HexColor("#2b6cb0"),
)
STYLE_COMP_BODY = ParagraphStyle(
    "CompBody", parent=_styles["Normal"],
    fontName=_FONT, fontSize=7, leading=10,
)
STYLE_COMP_SMALL = ParagraphStyle(
    "CompSmall", parent=_styles["Normal"],
    fontName=_FONT, fontSize=6.5, leading=9, textColor=colors.HexColor("#4a5568"),
)
STYLE_COMP_NAME = ParagraphStyle(
    "CompName", parent=_styles["Normal"],
    fontName=_FONT, fontSize=7, leading=10, alignment=1,  # center
)
STYLE_COMP_LABEL = ParagraphStyle(
    "CompLabel", parent=_styles["Normal"],
    fontName=_FONT, fontSize=6.5, leading=9, textColor=colors.HexColor("#718096"),
)

_HEADER_BG = colors.HexColor("#edf2f7")
_GROUP_BG = colors.HexColor("#ebf4ff")
_GRID_COLOR = colors.HexColor("#e2e8f0")
_LIGHT_YELLOW = colors.HexColor("#fffff0")

STYLE_COMP_SCORE = ParagraphStyle(
    "CompScore", parent=_styles["Normal"],
    fontName=_FONT, fontSize=6, leading=8, alignment=1,
    textColor=colors.HexColor("#a0aec0"),
)


def _cp(text, style=STYLE_COMP_BODY):
    return Paragraph(str(text), style)


def _make_page_header(template, period=""):
    """比較PDFの全ページに表示するヘッダー描画関数を返す。"""
    company_name = template.company.name if template.company else ""
    title = f"{company_name}　人材評価 比較シート"
    if period:
        title += f"　【{period}】"

    # スケール情報を事前に準備
    scale_items = []
    if template.scale:
        # value の降順（5→1）で並べる
        sorted_scale = sorted(template.scale, key=lambda s: s.get("value", 0), reverse=True)
        for s in sorted_scale:
            scale_items.append((s.get("value", 0), s.get("label", "")))

    # スケールバーの色（5=濃い青 → 1=赤系）
    _SCALE_COLORS = {
        5: "#2b6cb0",
        4: "#3182ce",
        3: "#48bb78",
        2: "#ed8936",
        1: "#e53e3e",
    }

    def _draw_header(canvas, doc):
        canvas.saveState()
        page_w = doc.pagesize[0]
        top_y = doc.pagesize[1] - 8 * mm

        # タイトル
        canvas.setFont(_FONT, 11)
        canvas.setFillColor(colors.HexColor("#1a202c"))
        canvas.drawString(12 * mm, top_y, title)

        # スケール凡例（視覚的な横棒バー表示）
        if scale_items:
            bar_y = top_y - 18  # バー描画の基準Y
            canvas.setFont(_FONT, 12)
            canvas.setFillColor(colors.HexColor("#1a202c"))
            canvas.drawString(12 * mm, bar_y, "評価スケール:")

            # 「評価スケール:」の右から横並びにバーを描画
            bar_start_x = 12 * mm + 90  # ラベルの右側
            max_bar_w = 5  # 1段階あたりのバー基本幅
            bar_h = 12  # バーの高さ
            content_w = page_w - bar_start_x - 12 * mm
            item_w = content_w / len(scale_items) if scale_items else 100

            for i, (val, label) in enumerate(scale_items):
                x = bar_start_x + i * item_w
                bar_w = val * max_bar_w  # 値に比例した幅

                # 色付き横棒
                bar_color = _SCALE_COLORS.get(val, "#718096")
                canvas.setFillColor(colors.HexColor(bar_color))
                canvas.roundRect(x, bar_y - 2, bar_w, bar_h, 2, fill=1, stroke=0)

                # 数字（バーの右側）
                canvas.setFont(_FONT, 12)
                canvas.setFillColor(colors.HexColor(bar_color))
                canvas.drawString(x + bar_w + 3, bar_y, f"{val}")

                # ラベル（数字の右側）
                canvas.setFont(_FONT, 8)
                canvas.setFillColor(colors.HexColor("#4a5568"))
                canvas.drawString(x + bar_w + 16, bar_y, f"={label}")

            # 注記
            canvas.setFont(_FONT, 8)
            canvas.setFillColor(colors.HexColor("#718096"))
            canvas.drawString(
                12 * mm, bar_y - 16, "※ 各欄に該当する数字（1〜5）を記入してください"
            )

        # ページ番号
        canvas.setFont(_FONT, 7)
        canvas.setFillColor(colors.HexColor("#a0aec0"))
        canvas.drawRightString(page_w - 12 * mm, 8 * mm, f"- {canvas.getPageNumber()} -")

        canvas.restoreState()

    return _draw_header


def generate_comparison_pdf(template, workers, period=""):
    """役員用: 被評価者を横に並べた比較評価シートPDFを生成する。

    職種ごとにワーカーをグループ化し、各グループについて
    該当する質問項目を行、被評価者名を列に並べる。
    """
    buf = BytesIO()
    # A4横長 — topMarginを広めにしてヘッダー領域を確保
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=38 * mm, bottomMargin=14 * mm,
    )

    page_header = _make_page_header(template, period)
    elements = []

    # ワーカーを職種ごとにグループ化
    job_groups = OrderedDict()
    for w in workers:
        job_name = str(w.job_title) if w.job_title else "未設定"
        job_groups.setdefault(job_name, []).append(w)

    # テンプレートの質問をセクション別にまとめる
    survey_items = template.survey_items or []
    sections_order = []
    sections_map = {}
    for item in survey_items:
        sec = item.get("section", "共通")
        if sec not in sections_map:
            sections_order.append(sec)
            sections_map[sec] = []
        sections_map[sec].append(item)

    # 職種→該当セクションのマッピング
    def _sections_for_job(job_name):
        secs = ["共通"]
        if job_name == "電工":
            secs.append("電工")
        elif job_name in ("事務", "developer"):
            secs.append("事務")
        elif job_name in ("役員", "社長"):
            secs.append(job_name)
        # テンプレートに job_name と一致するセクションがあれば追加
        if job_name in sections_map and job_name not in secs:
            secs.append(job_name)
        return secs

    # 利用可能な幅 (A4横 = 297mm - 24mm margins = 273mm)
    available_width = 273 * mm

    # 各職種グループごとに比較テーブルを生成
    first_group = True
    for job_name, group_workers in job_groups.items():
        if not first_group:
            elements.append(PageBreak())
        first_group = False

        applicable_secs = _sections_for_job(job_name)
        n_workers = len(group_workers)

        # ヘッダー
        elements.append(_cp(f"【{job_name}】 {n_workers}名", STYLE_COMP_H2))

        # 列幅の計算: 質問列(固定幅) + 名前列(均等分割)
        q_col_width = 130 * mm
        remaining = available_width - q_col_width
        name_col_width = min(remaining / max(n_workers, 1), 40 * mm)

        col_widths = [q_col_width] + [name_col_width] * n_workers

        # 該当セクションの質問をまとめる
        for sec in applicable_secs:
            if sec not in sections_map:
                continue

            items = sections_map[sec]

            # セクションヘッダー行 + 名前ヘッダー行
            header_row = [_cp(f"【{sec}】", STYLE_COMP_LABEL)]
            for w in group_workers:
                header_row.append(_cp(w.name, STYLE_COMP_NAME))

            table_data = [header_row]

            for item in items:
                name = item.get("name", "")
                num = item.get("num", "")

                # 評価項目名行（グレー背景） — 空欄（数字を直接記入）
                item_row = [_cp(f"{num}. {name}", STYLE_COMP_BODY)]
                for _ in group_workers:
                    item_row.append(_cp("", STYLE_COMP_BODY))
                table_data.append(item_row)

                # 個別質問行
                questions = item.get("questions", [])
                for q in questions:
                    q_row = [
                        _cp(f"  {q.get('qnum', '')}  {q.get('text', '')}", STYLE_COMP_SMALL),
                    ]
                    for _ in group_workers:
                        q_row.append(_cp("", STYLE_COMP_BODY))
                    table_data.append(q_row)

                # 自由記述行
                free_text = item.get("free_text", "")
                if free_text:
                    ft_row = [_cp(f"  [自由記述] {free_text}", STYLE_COMP_SMALL)]
                    for _ in group_workers:
                        ft_row.append(_cp("", STYLE_COMP_BODY))
                    table_data.append(ft_row)

            # テーブル描画
            t = Table(table_data, colWidths=col_widths, repeatRows=1)

            # スタイル
            style_commands = [
                ("FONTNAME", (0, 0), (-1, -1), _FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.4, _GRID_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                # ヘッダー行
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                ("ALIGN", (1, 0), (-1, 0), "CENTER"),
            ]

            # 評価項目名行にグループ背景色を適用
            row_idx = 1
            for item in items:
                style_commands.append(
                    ("BACKGROUND", (0, row_idx), (-1, row_idx), _GROUP_BG)
                )
                q_count = len(item.get("questions", []))
                ft = 1 if item.get("free_text") else 0
                row_idx += 1 + q_count + ft

            # 記入欄（名前列）に薄い黄色背景
            style_commands.append(
                ("BACKGROUND", (1, 1), (-1, -1), _LIGHT_YELLOW)
            )
            # でもグループ行は上書き
            row_idx = 1
            for item in items:
                style_commands.append(
                    ("BACKGROUND", (0, row_idx), (-1, row_idx), _GROUP_BG)
                )
                q_count = len(item.get("questions", []))
                ft = 1 if item.get("free_text") else 0
                row_idx += 1 + q_count + ft

            t.setStyle(TableStyle(style_commands))
            elements.append(t)
            elements.append(Spacer(1, 8))

    # 総合所見は廃止

    doc.build(elements, onFirstPage=page_header, onLaterPages=page_header)
    return buf.getvalue()


# =====================================================================
# 評価者別アンケートPDF
# =====================================================================

STYLE_EVAL_TITLE = ParagraphStyle(
    "EvalTitle", parent=_styles["Title"],
    fontName=_FONT, fontSize=16, leading=22, spaceAfter=4,
)
STYLE_EVAL_SUB = ParagraphStyle(
    "EvalSub", parent=_styles["Normal"],
    fontName=_FONT, fontSize=11, leading=15, spaceAfter=8,
    textColor=colors.HexColor("#2d3748"),
)
STYLE_EVAL_TARGET = ParagraphStyle(
    "EvalTarget", parent=_styles["Heading2"],
    fontName=_FONT, fontSize=13, leading=18, spaceBefore=6, spaceAfter=6,
    textColor=colors.white, backColor=colors.HexColor("#2b6cb0"),
    borderPadding=(6, 8, 6, 8),
)
STYLE_EVAL_SECTION = ParagraphStyle(
    "EvalSection", parent=_styles["Heading3"],
    fontName=_FONT, fontSize=10, leading=14, spaceBefore=8, spaceAfter=4,
    textColor=colors.HexColor("#2b6cb0"),
)
STYLE_EVAL_ITEM = ParagraphStyle(
    "EvalItem", parent=_styles["Heading3"],
    fontName=_FONT, fontSize=9.5, leading=13, spaceBefore=6, spaceAfter=3,
)
STYLE_EVAL_Q = ParagraphStyle(
    "EvalQ", parent=_styles["Normal"],
    fontName=_FONT, fontSize=8.5, leading=12,
)
STYLE_EVAL_ANCHOR = ParagraphStyle(
    "EvalAnchor", parent=_styles["Normal"],
    fontName=_FONT, fontSize=7.5, leading=10, textColor=colors.HexColor("#4a5568"),
)
STYLE_EVAL_SCORE_NUM = ParagraphStyle(
    "EvalScoreNum", parent=_styles["Normal"],
    fontName=_FONT, fontSize=10, leading=14, alignment=1,
)
STYLE_EVAL_OVERALL_Q = ParagraphStyle(
    "EvalOverallQ", parent=_styles["Normal"],
    fontName=_FONT, fontSize=9, leading=13, spaceBefore=4,
)
STYLE_EVAL_TOTAL_LABEL = ParagraphStyle(
    "EvalTotalLabel", parent=_styles["Normal"],
    fontName=_FONT, fontSize=10, leading=14,
)

_SCORE_BOX_BG = colors.HexColor("#fafafa")
_SCORE_BOX_BORDER = colors.HexColor("#a0aec0")
_WRITEIN_BG = colors.HexColor("#fffff0")
_WRITEIN_BORDER = colors.HexColor("#e2e8f0")


def _score_boxes_table(max_value=5):
    """1〜max_value の番号付き空ボックス行を返す（紙で○をつける用）。"""
    nums = [Paragraph(str(i), STYLE_EVAL_SCORE_NUM) for i in range(1, max_value + 1)]
    t = Table([nums], colWidths=[28] * max_value, rowHeights=[22])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT),
        ("BOX", (0, 0), (-1, -1), 1, _SCORE_BOX_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.8, _SCORE_BOX_BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), _SCORE_BOX_BG),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _choice_boxes_table(labels):
    """任意のラベルの空ボックス行を返す（設問の「はい/いいえ」用）。"""
    cells = [Paragraph(str(label), STYLE_EVAL_SCORE_NUM) for label in labels]
    t = Table([cells], colWidths=[48] * len(cells), rowHeights=[22])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT),
        ("BOX", (0, 0), (-1, -1), 1, _SCORE_BOX_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.8, _SCORE_BOX_BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), _SCORE_BOX_BG),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _writein_area(num_lines=3, width=None):
    """空の罫線付き記入エリアを返す。"""
    if width is None:
        width = 170 * mm
    rows = [[Paragraph("", STYLE_EVAL_Q)] for _ in range(num_lines)]
    t = Table(rows, colWidths=[width], rowHeights=[18] * num_lines)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, _WRITEIN_BORDER),
        ("LINEBELOW", (0, 0), (0, -1), 0.3, _WRITEIN_BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), _WRITEIN_BG),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def generate_evaluator_pdf(template, evaluator_name, targets_with_data, period=""):
    """評価者別アンケートPDFを生成する。

    各対象者ごとにページを分け、質問項目・スコア記入欄・
    自由記述欄・総合所見・合計点欄を含む紙ベースのアンケート用紙。

    Parameters
    ----------
    template : EvaluationTemplate
        テンプレートオブジェクト（company, scale 等を参照）。
    evaluator_name : str
        評価者の氏名。
    targets_with_data : list[dict]
        対象者情報のリスト。各要素は worker_name, job_title,
        survey_items, scale を含む。
    period : str
        評価期間の表示文字列（任意）。
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
    )

    elements = []

    # ---------- 表紙的ヘッダー ----------
    company_name = template.company.name if template.company else ""
    title_text = f"{company_name} 人材評価アンケート"
    if period:
        title_text += f"【{period}】"
    elements.append(_p(title_text, STYLE_EVAL_TITLE))
    elements.append(_p(f"評価者: {evaluator_name}", STYLE_EVAL_SUB))
    elements.append(Spacer(1, 6))

    # ---------- スケール凡例（1回だけ表示） ----------
    legend_scale = None
    if targets_with_data:
        legend_scale = targets_with_data[0].get("scale") or []
    if not legend_scale and template.scale:
        legend_scale = template.scale
    if legend_scale:
        elements.append(_p("■ 評価スケール", STYLE_H2))
        scale_data = [[
            _p("値", STYLE_LABEL),
            _p("ラベル", STYLE_LABEL),
        ]]
        for s in legend_scale:
            scale_data.append([
                _p(str(s.get("value", "")), STYLE_BODY),
                _p(str(s.get("label", "")), STYLE_BODY),
            ])
        t = Table(scale_data, colWidths=[40, None])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), _FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.5, _GRID_COLOR),
            ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 4))
        elements.append(
            _p("※ 各質問について該当する数字に○をつけてください。", STYLE_SMALL)
        )

    # ---------- 対象者ごとのセクション ----------
    for idx, target in enumerate(targets_with_data):
        elements.append(PageBreak())

        worker_name = target.get("worker_name", "")
        job_title = target.get("job_title", "")
        survey_items = target.get("survey_items") or []

        # 対象者ヘッダー。氏名が空の場合は役職別の白紙シートとして扱い、
        # 氏名・評価者は手書きできるよう記入欄にする。
        if worker_name:
            elements.append(
                _p(
                    f"対象者 {idx + 1}: {worker_name}　（{job_title}）",
                    STYLE_EVAL_TARGET,
                )
            )
        else:
            elements.append(_p(f"【{job_title}】評価シート", STYLE_EVAL_TARGET))
            elements.append(Spacer(1, 2))
            elements.append(
                _p("被評価者：＿＿＿＿＿＿＿＿＿＿　　評価者：＿＿＿＿＿＿＿＿＿＿",
                   STYLE_EVAL_SUB)
            )
        elements.append(Spacer(1, 6))

        # セクション別にグループ化
        sections_order = []
        sections_map = {}
        for item in survey_items:
            sec = item.get("section", "共通")
            if sec not in sections_map:
                sections_order.append(sec)
                sections_map[sec] = []
            sections_map[sec].append(item)

        for sec in sections_order:
            elements.append(_p(f"【{sec}】", STYLE_EVAL_SECTION))

            for item in sections_map[sec]:
                name = item.get("name", "")
                num = item.get("num", "")
                elements.append(
                    _p(f"{num}. {name}　<font color='#718096'>〈{sec}〉</font>",
                       STYLE_EVAL_ITEM)
                )

                # 5段階の行動基準（アンカー）は廃止したため出力しない

                # 個別質問 + スコアボックス
                questions = item.get("questions", [])
                for q in questions:
                    qnum = q.get("qnum", "")
                    qtext = q.get("text", "")
                    elements.append(
                        _p(f"Q{qnum}. {qtext}", STYLE_EVAL_Q)
                    )
                    elements.append(Spacer(1, 2))
                    # 設問は「はい/いいえ」の2択。項目全体・総合は5段階のまま。
                    elements.append(
                        _choice_boxes_table([s["label"] for s in QUESTION_SCALE])
                    )
                    elements.append(Spacer(1, 4))

                # 自由記述エリア
                free_text = item.get("free_text", "")
                if free_text:
                    elements.append(
                        _p(f"[自由記述] {free_text}", STYLE_SMALL)
                    )
                    elements.append(Spacer(1, 2))
                    elements.append(_writein_area(num_lines=3))
                    elements.append(Spacer(1, 4))

                elements.append(Spacer(1, 4))

        # ---------- 総合コメント ----------
        # 総合所見（設問形式）と合計点は廃止。自由記入の総合コメント欄のみ置く。
        elements.append(Spacer(1, 10))
        elements.append(_p("【総合コメント】", STYLE_EVAL_SECTION))
        elements.append(Spacer(1, 2))
        elements.append(_writein_area(num_lines=8))

    doc.build(elements)
    return buf.getvalue()
