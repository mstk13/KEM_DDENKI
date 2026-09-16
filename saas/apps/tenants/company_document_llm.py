"""自社書類を Claude に読ませて、何が書いてあるかを取り出す（ADR-0071）。

経営規模等評価結果通知書・許可証・証明書は、発注機関ごとに様式が違い、
決まった位置から抜き出す作り方が当てはまらない。読み取りは目安として出し、
更新日などの大事な値は画面で人が直して確定させる（AI の値をそのまま帳票には使わない）。

コスト: 1件あたり数ページで Sonnet で $0.01〜0.05 程度。登録のたびに自動では呼ばず、
画面の「AI で読み取る」を押したときだけ動く。月間予算の確認は call_claude_with_log が行う。
"""

from __future__ import annotations

import base64
import io
import logging

logger = logging.getLogger(__name__)

# Claude に渡せる大きさの上限（リクエスト全体の 32MB に対する安全側）
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 60
# Excel から起こす文字数の上限。長い決算書でも要点は先頭に出る
MAX_EXCEL_CHARS = 20000

MODEL_KEY = "sonnet"
MAX_TOKENS = 4000
# 画面に出す項目の数。多すぎると読むより原本を見たほうが早い
MAX_FIELDS = 12

SYSTEM_PROMPT = (
    "あなたは日本の建設会社の事務担当者です。"
    "会社の書類（経営規模等評価結果通知書・許可証・証明書・決算書など）を読み、"
    "書いてあることだけを根拠に答えてください。"
    "書かれていない項目は推測せず空にしてください。"
    "常にJSON形式のみで回答してください。"
)

INSTRUCTION = """この書類は日本の建設会社が受け取った会社に関する書類です。
次のJSONだけを返してください。前後に説明文やコードブロックを付けないでください。

{
  "document_type": "書類の名前（例: 経営規模等評価結果通知書、建設業許可証、納税証明書）",
  "issuer": "発行した役所・機関の名前。書かれていなければ空文字",
  "issued_on": "発行日。YYYY-MM-DD。書かれていなければ空文字",
  "renewal_on": "次に更新・提出が必要な日（有効期限・更新期限）。YYYY-MM-DD。無ければ空文字",
  "fields": [
    {"label": "項目名", "value": "値"}
  ],
  "summary": "何の書類で、何が書いてあるかを3行以内で。数字は書類のとおりに"
}

注意:
- fields には、あとで書類を探すときの手がかりになる項目を最大12個入れてください
  （許可番号、総合評定値（P点）、各評点、完成工事高、自己資本額、審査基準日、有効期間など）。
- 日付は和暦なら西暦に直してください（令和8年4月1日 → 2026-04-01）。
- 金額は書類のとおりの単位で、単位も value に含めてください（例: 1,234千円）。
- 読み取れない項目は入れないでください。空の項目を埋めるより、少ないほうが役に立ちます。
"""


def is_available() -> bool:
    """AI での読み取りが使える状態か。"""
    from apps.ai.services.llm_advisor import check_availability

    available, reason = check_availability()
    if not available:
        logger.info("自社書類のAI読み取りは使えません: %s", reason)
    return available


def _page_count(pdf_bytes: bytes) -> int | None:
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return len(pdf.pages)
    except Exception:
        return None


def excel_to_text(data: bytes) -> str:
    """Excel の中身を文字にする。シート名と、値の入っているセルだけを並べる。"""
    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    lines: list[str] = []
    length = 0
    for sheet in workbook.worksheets:
        lines.append(f"# {sheet.title}")
        for row in sheet.iter_rows(values_only=True):
            values = [str(v).strip() for v in row if v not in (None, "")]
            if not values:
                continue
            line = " | ".join(values)
            lines.append(line)
            length += len(line)
            if length > MAX_EXCEL_CHARS:
                lines.append("（以下省略）")
                return "\n".join(lines)
    return "\n".join(lines)


def _content_for(document, data: bytes):
    """Claude に渡す中身。PDF はそのまま、Excel は文字に起こして渡す。"""
    if document.kind == document.Kind.PDF:
        if not data.startswith(b"%PDF") or len(data) > MAX_PDF_BYTES:
            return None, {}
        pages = _page_count(data)
        if pages is not None and pages > MAX_PDF_PAGES:
            logger.warning("自社書類のページ数が多すぎます（%dページ）", pages)
            return None, {}
        return [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(data).decode("ascii"),
                },
            },
            {"type": "text", "text": INSTRUCTION},
        ], {"source": "company_document_pdf", "pages": pages}

    try:
        text = excel_to_text(data)
    except Exception as exc:  # noqa: BLE001 — 読めない Excel は AI にかけずに終える
        logger.warning("自社書類のExcelを読めませんでした: %s", exc)
        return None, {}
    if not text.strip():
        return None, {}
    return [
        {"type": "text", "text": f"{INSTRUCTION}\n\n--- 書類の中身 ---\n{text}"},
    ], {"source": "company_document_excel", "chars": len(text)}


def _clean_fields(parsed) -> list[dict]:
    rows = parsed.get("fields")
    cleaned = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "").strip()[:60]
            value = str(row.get("value") or "").strip()[:200]
            if label and value:
                cleaned.append({"label": label, "value": value})
    return cleaned[:MAX_FIELDS]


def _clean_date(value) -> str:
    """"2026-04-01" の形だけ通す。読めなければ空文字。"""
    import datetime

    text = str(value or "").strip()
    try:
        return datetime.date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def analyze(document, data: bytes, user=None) -> dict | None:
    """書類を Claude に読ませる。読めなければ None。

    Returns:
        {"document_type", "issuer", "issued_on", "renewal_on", "fields", "summary"}
    """
    company = document.company
    if company is None:
        # 予算チェックが効かなくなるので会社なしでは呼ばない
        logger.warning("company が無いため自社書類のAI読み取りを行いません")
        return None
    content, input_data = _content_for(document, data)
    if content is None:
        return None

    from apps.ai.models import AILog
    from apps.ai.services.llm_advisor import call_claude_with_log

    try:
        result = call_claude_with_log(
            prompt=INSTRUCTION,
            model_key=MODEL_KEY,
            max_tokens=MAX_TOKENS,
            company=company,
            site=None,  # 会社そのものの書類なので現場に紐づかない
            task_type=AILog.TaskType.GENERAL_ANALYSIS,
            input_data={**input_data, "document_id": document.pk},
            user=user,
            system_prompt=SYSTEM_PROMPT,
            content=content,
        )
    except Exception as exc:  # noqa: BLE001 — 予算超過・鍵未設定・API障害。登録は失敗させない
        logger.warning("自社書類のAI読み取りに失敗しました: %s", exc)
        return None

    parsed = result.get("parsed")
    if not isinstance(parsed, dict):
        logger.warning("自社書類のAI読み取りの応答をJSONとして読めませんでした")
        return None

    return {
        "document_type": str(parsed.get("document_type") or "").strip()[:200],
        "issuer": str(parsed.get("issuer") or "").strip()[:200],
        "issued_on": _clean_date(parsed.get("issued_on")),
        "renewal_on": _clean_date(parsed.get("renewal_on")),
        "fields": _clean_fields(parsed),
        "summary": str(parsed.get("summary") or "").strip()[:2000],
    }
