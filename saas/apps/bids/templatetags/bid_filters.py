"""入札案件のテンプレートフィルター。"""

import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

# 番号付き項目: （1）, (1), ①, （ア）, ア., 1. など
_ITEM_SPLIT = re.compile(
    r"(?:^|\n)\s*"
    r"(?:"
    r"[（(]\s*[0-9０-９]{1,2}\s*[）)]"  # （1）(1)
    r"|[（(]\s*[ア-ン]\s*[）)]"  # （ア）
    r"|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮]"  # ①②
    r")"
    r"\s*"
)

# ラベルと本文を分離: 「工事名 XXX」→ ("工事名", "XXX")
_LABEL_PATTERNS = [
    re.compile(r"^(工事名|業務名|件名)\s+(.+)", re.DOTALL),
    re.compile(r"^(工事場所|履行場所|場所)\s+(.+)", re.DOTALL),
    re.compile(r"^(工事内容|業務内容|内容)\s+(.+)", re.DOTALL),
    re.compile(r"^(工事概算数量|概算数量|数量)\s+(.+)", re.DOTALL),
    re.compile(r"^(工期|履行期間|期間)\s+(.+)", re.DOTALL),
    re.compile(r"^(配置予定技術者.+)", re.DOTALL),
    re.compile(r"^(資料|資格.+)", re.DOTALL),
]


def _split_items(text: str) -> list[tuple[str, str]]:
    """番号付きテキストを [(ラベル, 本文), ...] に分割する。"""
    if not text:
        return []

    # 番号で分割
    parts = _ITEM_SPLIT.split(text.strip())
    parts = [p.strip() for p in parts if p.strip()]

    items = []
    for part in parts:
        label = ""
        body = part
        for pattern in _LABEL_PATTERNS:
            m = pattern.match(part)
            if m:
                if m.lastindex == 2:
                    label = m.group(1)
                    body = m.group(2).strip()
                else:
                    label = ""
                    body = m.group(1).strip()
                break

        if not label:
            # ラベルパターンに一致しない場合、最初の空白で分割を試みる
            first_line = part.split("\n")[0]
            space_m = re.match(r"^(\S{2,15})\s+(.+)", first_line)
            if space_m:
                label = space_m.group(1)
                rest_lines = part[len(first_line):]
                body = space_m.group(2) + rest_lines
                body = body.strip()

        items.append((label, body))

    return items


@register.filter(name="structured_text")
def structured_text(text):
    """番号付きテキストを構造化された表形式のHTMLに変換する。

    Usage: {{ project.work_outline|structured_text }}
    """
    if not text:
        return ""

    items = _split_items(text)

    if not items:
        return mark_safe(f'<div style="white-space:pre-wrap;">{escape(text)}</div>')

    # 1項目だけでラベルもない場合はそのまま表示
    if len(items) == 1 and not items[0][0]:
        return mark_safe(f'<div style="white-space:pre-wrap;">{escape(text)}</div>')

    rows = []
    for label, body in items:
        escaped_body = escape(body).replace("\n", "<br>")
        if label:
            escaped_label = escape(label)
            rows.append(
                f'<tr>'
                f'<td style="white-space:nowrap;vertical-align:top;font-weight:600;'
                f'padding:8px 12px;width:120px;background:var(--surface-hover);">'
                f'{escaped_label}</td>'
                f'<td style="padding:8px 12px;">{escaped_body}</td>'
                f'</tr>'
            )
        else:
            rows.append(
                f'<tr><td colspan="2" style="padding:8px 12px;">{escaped_body}</td></tr>'
            )

    html = (
        '<div class="table-wrap"><table style="width:100%;">'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table></div>'
    )
    return mark_safe(html)


# ---- 参加要件の項目ごとに、不足理由を右側に添える ----

# 等級・点数・資格の話をしている項目かどうかを見分ける語
_QUAL_WORDS = ("競争参加資格", "参加資格", "格付", "統一資格", "資格審査", "認定")
_GRADE_WORDS = ("等級",)
_SCORE_WORDS = (
    "総合審査数値", "経営事項評価数値", "総合点数", "総合数値", "総合評点",
    "審査数値", "評価数値",
)
_NOT_QUAL_WORDS = ("評定", "成績")  # 工事成績の話は資格ではない


def _item_matches_failure(body: str, failed_on: str) -> bool:
    """参加要件の1項目が、判定で落ちた条件の話をしているか。"""
    text = re.sub(r"\s+", "", body)
    if any(w in text for w in _NOT_QUAL_WORDS) and not any(w in text for w in _QUAL_WORDS):
        return False
    if failed_on in ("grade", "grades"):
        return any(w in text for w in _GRADE_WORDS) and any(w in text for w in _QUAL_WORDS)
    if failed_on == "score":
        return "点以上" in text and any(w in text for w in _SCORE_WORDS)
    if failed_on in ("issuer", "category", "expired", "unified_kind"):
        return any(w in text for w in _QUAL_WORDS)
    return False


def _shortfall_note_html(reason: str) -> str:
    return (
        '<span class="badge badge-red" style="margin-right:6px;">資格不足</span>'
        f'{escape(reason)}'
    )


@register.simple_tag(name="requirements_with_shortfall")
def requirements_with_shortfall(text, qual_check):
    """参加要件を項目ごとの表にし、資格不足の理由を該当項目の右側に添える。

    Usage: {% requirements_with_shortfall project.requirements qual_check %}

    - 判定が資格不足でなければ structured_text と同じ表示
    - 落ちた条件（等級・点数・資格の有無）の話をしている項目の右に理由を出す。
      該当する項目が見つからなければ、資格の話をしている最初の項目に付け、
      それも無ければ表の上に1行で出す
    """
    ineligible = bool(qual_check) and qual_check.get("eligible") is False
    if not ineligible:
        return structured_text(text)
    reason = qual_check.get("reason", "")
    failed_on = qual_check.get("failed_on", "")

    if not text:
        return mark_safe(
            f'<div style="margin-bottom:8px;">{_shortfall_note_html(reason)}</div>'
            '<div style="color:var(--gray-400);text-align:center;padding:20px;">'
            '未入力です。公告の入札参加資格・実績要件・配置技術者の条件を転記してください。'
            '</div>'
        )

    items = _split_items(text)
    if not items or (len(items) == 1 and not items[0][0]):
        return mark_safe(
            f'<div style="margin-bottom:8px;">{_shortfall_note_html(reason)}</div>'
            f'<div style="white-space:pre-wrap;">{escape(text)}</div>'
        )

    # 理由を添える項目を決める
    targets = [i for i, (_, body) in enumerate(items) if _item_matches_failure(body, failed_on)]
    if not targets:
        targets = [
            i for i, (_, body) in enumerate(items)
            if any(w in re.sub(r"\s+", "", body) for w in _QUAL_WORDS)
        ][:1]
    banner = ""
    if not targets:
        banner = f'<div style="margin-bottom:8px;">{_shortfall_note_html(reason)}</div>'

    # 左（ラベル＋本文）と右（理由）をちょうど半分ずつにする。
    # table-layout:fixed と colgroup で列幅を固定し、文章の長さで幅が動かないようにする。
    has_label = any(label for label, _ in items)
    if has_label:
        colgroup = (
            '<colgroup><col style="width:120px;"><col style="width:calc(50% - 120px);">'
            '<col style="width:50%;"></colgroup>'
        )
    else:
        colgroup = '<colgroup><col style="width:50%;"><col style="width:50%;"></colgroup>'

    rows = []
    for i, (label, body) in enumerate(items):
        escaped_body = escape(body).replace("\n", "<br>")
        note = (
            f'<td class="shortfall-note" style="padding:8px 12px;vertical-align:top;'
            f'color:var(--danger);font-size:.85rem;border-left:1px solid var(--border-light);">'
            f'{_shortfall_note_html(reason)}</td>'
            if i in targets else
            '<td style="padding:8px 12px;border-left:1px solid var(--border-light);"></td>'
        )
        if label:
            rows.append(
                f'<tr>'
                f'<td style="vertical-align:top;font-weight:600;'
                f'padding:8px 12px;background:var(--surface-hover);">'
                f'{escape(label)}</td>'
                f'<td style="padding:8px 12px;vertical-align:top;">{escaped_body}</td>'
                f'{note}</tr>'
            )
        elif has_label:
            rows.append(
                f'<tr><td colspan="2" style="padding:8px 12px;vertical-align:top;">'
                f'{escaped_body}</td>{note}</tr>'
            )
        else:
            rows.append(
                f'<tr><td style="padding:8px 12px;vertical-align:top;">'
                f'{escaped_body}</td>{note}</tr>'
            )

    html = (
        f'{banner}<div class="table-wrap">'
        f'<table style="width:100%;table-layout:fixed;">{colgroup}'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table></div>'
    )
    return mark_safe(html)
