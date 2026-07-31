"""評価レポートのPDF出力

reportlab の CID フォント（HeiseiKakuGo-W5）を使うため、外部フォントファイルは不要。
Windows / Mac / Streamlit Cloud のいずれでも日本語がそのまま出力できる。
"""
from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

FONT = "HeiseiKakuGo-W5"
_FONT_READY = False


def _ensure_font():
    global _FONT_READY
    if not _FONT_READY:
        pdfmetrics.registerFont(UnicodeCIDFont(FONT))
        _FONT_READY = True


def _styles():
    return {
        "title": ParagraphStyle("t", fontName=FONT, fontSize=15, leading=20, spaceAfter=4),
        "sub": ParagraphStyle("s", fontName=FONT, fontSize=9, leading=13,
                              textColor=colors.HexColor("#555555"), spaceAfter=8),
        "h2": ParagraphStyle("h2", fontName=FONT, fontSize=11.5, leading=16,
                             spaceBefore=10, spaceAfter=5),
        "cell": ParagraphStyle("c", fontName=FONT, fontSize=7.2, leading=9.4),
        # 見出し行は列幅に収まりやすいよう本文より一回り小さくする
        "cell_b": ParagraphStyle("cb", fontName=FONT, fontSize=6.6, leading=8.6,
                                 textColor=colors.white),
        "note": ParagraphStyle("n", fontName=FONT, fontSize=7.5, leading=11,
                               textColor=colors.HexColor("#666666"), spaceBefore=6),
    }


def _fmt(value, decimals=0) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if isinstance(value, float):
        return f"{value:.{decimals}f}" if decimals else f"{value:.0f}"
    return str(value)


def _base_table_style(header_bg="#4a5568"):
    return TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 7.2),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b8bfc7")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f8")]),
    ])


def build_employee_report(employee: str, meta: dict, matrix: pd.DataFrame,
                          by_item: pd.DataFrame, history: list[dict],
                          score_cols: list[str], extra_cols: list[str],
                          self_labels: list[str]) -> bytes:
    """従業員1名分の評価レポートPDFをバイト列で返す。

    matrix   : 設問 × 評価者 の比較表（項目 / # / 設問 / 各評価者 / 他者平均 / 差）
    by_item  : 評価項目ごとの平均
    history  : 評価履歴（core.load_evaluations() の要素）
    """
    _ensure_font()
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
        title=f"人事評価レポート {employee}", author="KEM電気 人事評価管理",
    )
    story = []

    # --- 見出し ---
    story.append(Paragraph(f"人事評価レポート　{employee}", st["title"]))
    story.append(Paragraph(
        f"役割: {meta.get('role', '—')}　／　評価期間: {meta.get('period', '—')}　／　"
        f"評価件数: {meta.get('count', 0)} 件　／　出力日: {datetime.now():%Y-%m-%d %H:%M}",
        st["sub"]))

    # --- 評価履歴 ---
    if history:
        story.append(Paragraph("■ 評価履歴", st["h2"]))
        head = ["評価日", "役割", "評価期間", "評価者", "得点", "達成率", "ランク"]
        rows = [[Paragraph(h, st["cell_b"]) for h in head]]
        for e in history:
            score = f"{e['total_score']} / {e['max_total']}" if e["max_total"] else str(e["total_score"])
            rows.append([Paragraph(x, st["cell"]) for x in [
                e["created_at"][:16], e["role"], e["period"], e["evaluator"] or "—",
                score, f"{e['rate']:.1f} %", e["rank"],
            ]])
        t = Table(rows, colWidths=[30 * mm, 20 * mm, 45 * mm, 30 * mm, 24 * mm, 20 * mm, 16 * mm],
                  repeatRows=1)
        t.setStyle(_base_table_style())
        story.append(t)

    # --- 評価項目ごとの平均 ---
    if by_item is not None and not by_item.empty:
        story.append(Paragraph("■ 評価項目ごとの平均（5点満点）", st["h2"]))
        cols = list(by_item.columns)
        rows = [[Paragraph(str(c), st["cell_b"]) for c in cols]]
        for _, r in by_item.iterrows():
            rows.append([Paragraph(r[c] if c == "項目" else _fmt(r[c], 2), st["cell"]) for c in cols])
        item_w = 45 * mm
        rest = (255 * mm - item_w) / max(1, len(cols) - 1)
        t = Table(rows, colWidths=[item_w] + [rest] * (len(cols) - 1), repeatRows=1)
        style = _base_table_style()
        for i, c in enumerate(cols):
            if c != "項目":
                style.add("ALIGN", (i, 1), (i, -1), "CENTER")
            if c in self_labels:      # 自己評価の列を強調
                style.add("BACKGROUND", (i, 1), (i, -1), colors.HexColor("#fff4e0"))
        t.setStyle(style)
        story.append(t)

    # --- 設問ごとの比較（メイン）---
    story.append(PageBreak())
    story.append(Paragraph("■ 設問ごとの回答（評価者を横並びで比較）", st["h2"]))
    if self_labels:
        story.append(Paragraph(
            f"※ 左側の「{self_labels[0]}」が自己評価（回答者と対象者が一致）。"
            "評価は 5=期待を大きく上回る / 4=期待を上回る / 3=期待通り / 2=やや不足 / 1=大きく不足。"
            "「—」は未回答（わからない・該当なし）。", st["note"]))
    else:
        story.append(Paragraph(
            "※ 評価は 5=期待を大きく上回る / 4=期待を上回る / 3=期待通り / 2=やや不足 / 1=大きく不足。"
            "「—」は未回答（わからない・該当なし）。", st["note"]))
    story.append(Spacer(1, 3))

    value_cols = score_cols + extra_cols
    head = ["項目", "#", "設問"] + value_cols
    rows = [[Paragraph(str(h), st["cell_b"]) for h in head]]
    for _, r in matrix.iterrows():
        line = [Paragraph(str(r["項目"]), st["cell"]),
                Paragraph(str(r["#"]), st["cell"]),
                Paragraph(str(r["設問"]), st["cell"])]
        for c in value_cols:
            line.append(Paragraph(_fmt(r[c], 2 if c in extra_cols else 0), st["cell"]))
        rows.append(line)

    n_val = max(1, len(value_cols))
    val_w = min(22 * mm, max(13 * mm, (120 * mm) / n_val))
    q_w = 273 * mm - (34 * mm + 12 * mm) - val_w * n_val
    t = Table(rows, colWidths=[34 * mm, 12 * mm, q_w] + [val_w] * n_val, repeatRows=1)
    style = _base_table_style()
    for i, c in enumerate(head):
        if i >= 3:
            style.add("ALIGN", (i, 1), (i, -1), "CENTER")
        if c in self_labels:
            style.add("BACKGROUND", (i, 1), (i, -1), colors.HexColor("#fff4e0"))
    t.setStyle(style)
    story.append(t)

    doc.build(story)
    return buf.getvalue()


def build_blank_questionnaire(
    evaluator: str,
    employee: str,
    role: str,
    period: str,
    common_items: list[dict],
    role_items: list[dict],
    questions_by_item: dict[int, list[dict]],
    overall_questions: list[dict],
) -> bytes:
    """手書き記入用の空白評価アンケートPDFをバイト列で返す。

    common_items / role_items: 評価項目 dict (id, name, description, max_score,
                               anchor_5, anchor_3, anchor_1 は任意)
    questions_by_item: {item_id: [{id, number, text}, ...]}
    overall_questions: [{id, text}, ...]
    """
    _ensure_font()
    st = _styles()
    # アンケート専用の追加スタイル
    st_body = ParagraphStyle("body", fontName=FONT, fontSize=9, leading=13)
    st_item_title = ParagraphStyle(
        "item_title", fontName=FONT, fontSize=10, leading=14, spaceBefore=8, spaceAfter=2,
    )
    st_anchor = ParagraphStyle(
        "anchor", fontName=FONT, fontSize=7.5, leading=10,
        textColor=colors.HexColor("#444444"),
    )
    st_q = ParagraphStyle("q", fontName=FONT, fontSize=8.5, leading=12)
    st_circle = ParagraphStyle("circle", fontName=FONT, fontSize=10, leading=13, alignment=1)
    st_legend = ParagraphStyle(
        "legend", fontName=FONT, fontSize=8, leading=12,
        textColor=colors.HexColor("#333333"), spaceAfter=6,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title="人事評価アンケート", author="KEM電気 人事評価管理",
    )
    story: list = []

    # --- ヘッダー ---
    story.append(Paragraph("人事評価アンケート", st["title"]))
    story.append(Paragraph(
        f"評価者: {evaluator}　／　被評価者: {employee}　／　役割: {role}　／　評価期間: {period}",
        st["sub"],
    ))

    # --- 評価スケール凡例 ---
    story.append(Paragraph(
        "【評価スケール】　5＝期待を大きく上回る　　4＝期待を上回る　　3＝期待通り"
        "　　2＝やや不足　　1＝大きく不足",
        st_legend,
    ))
    story.append(Spacer(1, 4))

    # --- 評価項目セクションを構築するヘルパー ---
    def _add_items_section(section_label: str, items: list[dict]):
        if not items:
            return
        story.append(Paragraph(f"■ {section_label}", st["h2"]))
        story.append(Spacer(1, 2))

        for item in items:
            item_id = item["id"]
            name = item.get("name", "")
            desc = item.get("description", "")
            max_score = item.get("max_score", "")

            # 項目タイトル行
            story.append(Paragraph(
                f"【{name}】　（配点: {max_score}）", st_item_title,
            ))
            if desc:
                story.append(Paragraph(desc, st_body))

            # アンカー (5/3/1)
            anchor_5 = item.get("anchor_5")
            anchor_3 = item.get("anchor_3")
            anchor_1 = item.get("anchor_1")
            if anchor_5 or anchor_3 or anchor_1:
                anchors_parts = []
                if anchor_5:
                    anchors_parts.append(f"5点: {anchor_5}")
                if anchor_3:
                    anchors_parts.append(f"3点: {anchor_3}")
                if anchor_1:
                    anchors_parts.append(f"1点: {anchor_1}")
                story.append(Paragraph("　".join(anchors_parts), st_anchor))

            story.append(Spacer(1, 3))

            # 設問テーブル
            questions = questions_by_item.get(item_id, [])
            if questions:
                head_row = [
                    Paragraph("#", st["cell_b"]),
                    Paragraph("設問", st["cell_b"]),
                    Paragraph("評価（○をつけてください）", st["cell_b"]),
                ]
                rows = [head_row]
                for q in questions:
                    q_num = q.get("qnum", q.get("number", ""))
                    q_text = q.get("text", "")
                    rows.append([
                        Paragraph(str(q_num), st["cell"]),
                        Paragraph(q_text, st_q),
                        Paragraph("①　　②　　③　　④　　⑤", st_circle),
                    ])

                page_w = A4[0] - 30 * mm  # usable width
                t = Table(
                    rows,
                    colWidths=[10 * mm, page_w - 10 * mm - 55 * mm, 55 * mm],
                    repeatRows=1,
                )
                t.setStyle(TableStyle([
                    ("FONTNAME", (0, 0), (-1, -1), FONT),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4a5568")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b8bfc7")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (0, -1), "CENTER"),
                    ("ALIGN", (2, 1), (2, -1), "CENTER"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                     [colors.white, colors.HexColor("#f4f6f8")]),
                ]))
                story.append(t)

            # 自由記述欄
            story.append(Spacer(1, 3))
            story.append(Paragraph("自由記述（コメント）:", st_q))
            comment_box = Table(
                [[""]],
                colWidths=[A4[0] - 30 * mm],
                rowHeights=[28 * mm],
            )
            comment_box.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(comment_box)
            story.append(Spacer(1, 6))

    # --- 共通項目 / 役割別項目 ---
    _add_items_section("共通評価項目", common_items)
    _add_items_section("役割別評価項目", role_items)

    # --- 総合質問 ---
    if overall_questions:
        story.append(Paragraph("■ 総合質問", st["h2"]))
        story.append(Spacer(1, 2))
        page_w = A4[0] - 30 * mm

        for i, oq in enumerate(overall_questions, 1):
            story.append(Paragraph(f"Q{i}. {oq.get('text', '')}", st_q))
            # 空の回答欄（3行分程度の枠線）
            answer_box = Table(
                [[""]],
                colWidths=[page_w],
                rowHeights=[24 * mm],
            )
            answer_box.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(answer_box)
            story.append(Spacer(1, 5))

    doc.build(story)
    return buf.getvalue()
