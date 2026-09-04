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
