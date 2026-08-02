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


def generate_comparison_pdf(template, workers, period=""):
    """役員用: 被評価者を横に並べた比較評価シートPDFを生成する。

    職種ごとにワーカーをグループ化し、各グループについて
    該当する質問項目を行、被評価者名を列に並べる。
    """
    buf = BytesIO()
    # A4横長
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
    )

    elements = []

    # タイトル
    title = f"{template.company.name}　人材評価 比較シート"
    if period:
        title += f"　【{period}】"
    elements.append(_cp(title, STYLE_COMP_TITLE))
    elements.append(Spacer(1, 4))

    # スケール凡例（コンパクト）
    if template.scale:
        scale_text = "　".join(
            f"{s.get('value')}={s.get('label', '')}" for s in template.scale
        )
        elements.append(_cp(f"評価スケール: {scale_text}", STYLE_COMP_SMALL))
        elements.append(_cp(
            "※ 各質問の数字（1〜5）に○をつけてください。",
            STYLE_COMP_SMALL,
        ))
        elements.append(Spacer(1, 6))

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

            # スケールの最大値を取得
            max_sv = max(
                (int(s.get("value", 5)) for s in (template.scale or [{"value": 5}])),
                default=5,
            )
            score_hint = " ".join(str(i) for i in range(1, max_sv + 1))

            for item in items:
                name = item.get("name", "")
                num = item.get("num", "")

                # 評価項目名行（グレー背景） — スコア記入欄に「1 2 3 4 5」ヒント
                item_row = [_cp(f"{num}. {name}", STYLE_COMP_BODY)]
                for _ in group_workers:
                    item_row.append(_cp(score_hint, STYLE_COMP_SCORE))
                table_data.append(item_row)

                # 個別質問行
                questions = item.get("questions", [])
                for q in questions:
                    q_row = [
                        _cp(f"  {q.get('qnum', '')}  {q.get('text', '')}", STYLE_COMP_SMALL),
                    ]
                    for _ in group_workers:
                        q_row.append(_cp(score_hint, STYLE_COMP_SCORE))
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

    # 総合所見（全員共通）
    overall = template.overall or []
    if overall:
        elements.append(PageBreak())
        elements.append(_cp("【総合所見】", STYLE_COMP_H2))

        for job_name, group_workers in job_groups.items():
            n_workers = len(group_workers)
            q_col_width = 130 * mm
            remaining = available_width - q_col_width
            name_col_width = min(remaining / max(n_workers, 1), 40 * mm)
            col_widths = [q_col_width] + [name_col_width] * n_workers

            header = [_cp(f"【{job_name}】 総合所見", STYLE_COMP_LABEL)]
            for w in group_workers:
                header.append(_cp(w.name, STYLE_COMP_NAME))
            table_data = [header]

            for o in overall:
                writer = "（本人記入）" if o.get("by_self") else ""
                row = [_cp(f"{o.get('qnum', '')}  {o.get('text', '')}{writer}", STYLE_COMP_SMALL)]
                for _ in group_workers:
                    row.append(_cp("", STYLE_COMP_BODY))
                table_data.append(row)

            t = Table(table_data, colWidths=col_widths, repeatRows=1)
            t.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), _FONT),
                ("GRID", (0, 0), (-1, -1), 0.4, _GRID_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                ("ALIGN", (1, 0), (-1, 0), "CENTER"),
                ("BACKGROUND", (1, 1), (-1, -1), _LIGHT_YELLOW),
            ]))
            elements.append(t)
            elements.append(Spacer(1, 10))

    doc.build(elements)
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
        survey_items, scale, overall を含む。
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
        scale = target.get("scale") or legend_scale or []
        overall = target.get("overall") or []

        max_scale_value = max(
            (int(s.get("value", 5)) for s in scale), default=5
        )

        # 対象者ヘッダー
        elements.append(
            _p(
                f"対象者 {idx + 1}: {worker_name}　（{job_title}）",
                STYLE_EVAL_TARGET,
            )
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

        total_question_count = 0

        for sec in sections_order:
            elements.append(_p(f"【{sec}】", STYLE_EVAL_SECTION))

            for item in sections_map[sec]:
                name = item.get("name", "")
                num = item.get("num", "")
                elements.append(
                    _p(f"{num}. {name}　<font color='#718096'>〈{sec}〉</font>",
                       STYLE_EVAL_ITEM)
                )

                # アンカー（基準）
                anchor_5 = item.get("anchor_5", "")
                anchor_3 = item.get("anchor_3", "")
                anchor_1 = item.get("anchor_1", "")
                if anchor_5 or anchor_3 or anchor_1:
                    anchor_rows = [[
                        _p("評点", STYLE_LABEL),
                        _p("行動基準", STYLE_LABEL),
                    ]]
                    if anchor_5:
                        anchor_rows.append([
                            _p("5 (最高)", STYLE_EVAL_ANCHOR),
                            _p(anchor_5, STYLE_EVAL_ANCHOR),
                        ])
                    if anchor_3:
                        anchor_rows.append([
                            _p("3 (標準)", STYLE_EVAL_ANCHOR),
                            _p(anchor_3, STYLE_EVAL_ANCHOR),
                        ])
                    if anchor_1:
                        anchor_rows.append([
                            _p("1 (要改善)", STYLE_EVAL_ANCHOR),
                            _p(anchor_1, STYLE_EVAL_ANCHOR),
                        ])
                    t = Table(anchor_rows, colWidths=[60, None])
                    t.setStyle(TableStyle([
                        ("FONTNAME", (0, 0), (-1, -1), _FONT),
                        ("GRID", (0, 0), (-1, -1), 0.5, _GRID_COLOR),
                        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ]))
                    elements.append(t)
                    elements.append(Spacer(1, 3))

                # 個別質問 + スコアボックス
                questions = item.get("questions", [])
                for q in questions:
                    total_question_count += 1
                    qnum = q.get("qnum", "")
                    qtext = q.get("text", "")
                    elements.append(
                        _p(f"Q{qnum}. {qtext}", STYLE_EVAL_Q)
                    )
                    elements.append(Spacer(1, 2))
                    elements.append(_score_boxes_table(max_scale_value))
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

        # ---------- 総合所見 ----------
        if overall:
            elements.append(Spacer(1, 6))
            elements.append(_p("【総合所見】", STYLE_EVAL_SECTION))

            for o in overall:
                oqnum = o.get("qnum", "")
                otext = o.get("text", "")
                by_self = o.get("by_self", False)
                label = "（本人記入）" if by_self else ""
                elements.append(
                    _p(f"{oqnum}. {otext}{label}", STYLE_EVAL_OVERALL_Q)
                )
                elements.append(Spacer(1, 2))
                elements.append(_writein_area(num_lines=4))
                elements.append(Spacer(1, 6))

        # ---------- 合計点セクション ----------
        elements.append(Spacer(1, 10))
        elements.append(_p("【合計点】", STYLE_EVAL_SECTION))

        total_data = [
            [
                _p("質問数", STYLE_LABEL),
                _p("合計スコア", STYLE_LABEL),
                _p("平均スコア", STYLE_LABEL),
            ],
            [
                _p(str(total_question_count), STYLE_BODY),
                _p("　　　/　　　", STYLE_BODY),
                _p("　　　.　　　", STYLE_BODY),
            ],
        ]
        t = Table(total_data, colWidths=[60, 90, 90])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), _FONT),
            ("GRID", (0, 0), (-1, -1), 0.8, _SCORE_BOX_BORDER),
            ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
            ("BACKGROUND", (1, 1), (-1, -1), _WRITEIN_BG),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(t)

    doc.build(elements)
    return buf.getvalue()
