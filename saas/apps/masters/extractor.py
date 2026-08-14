"""写真/PDFから取引先情報をAI抽出する。

Claude APIのマルチモーダル機能を使い、名刺・書類・PDFから
会社名・代表者・担当者・電話番号・FAX・メール・住所を抽出する。

コスト方針: OCR/抽出はHaikuで十分。AILogに記録する。
"""

import base64
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_EXTRACT_PROMPT = """\
この画像/文書から取引先（会社・事業者）の情報を抽出してください。
以下のJSON形式で返してください。見つからない項目は空文字にしてください。

{
  "name": "会社名・事業者名",
  "representative": "代表者名",
  "contact_person": "担当者名",
  "phone": "電話番号",
  "fax": "FAX番号",
  "email": "メールアドレス",
  "address": "住所"
}

JSONのみを返し、他のテキストは含めないでください。
複数の取引先が含まれる場合は、配列 [...] で返してください。
1社の場合もオブジェクト1つを返してください。
"""


def _encode_image(file_path):
    """画像ファイルをbase64エンコードする。"""
    with open(file_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def _get_media_type(file_path):
    """ファイル拡張子からメディアタイプを返す。"""
    suffix = Path(file_path).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }.get(suffix, "image/jpeg")


def extract_from_file(file_path, company=None, user=None):
    """画像/PDFファイルから取引先情報を抽出する。AILogに記録。

    Args:
        file_path: 画像/PDFのパス
        company: テナント（AILog・予算チェック用）
        user: 実行ユーザー

    Returns:
        list[dict]: 抽出された取引先情報のリスト。
    """
    from apps.ai.models import AILog
    from apps.ai.services.llm_advisor import call_claude_with_log

    media_type = _get_media_type(file_path)
    data = _encode_image(file_path)

    if media_type == "application/pdf":
        content = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": data,
                },
            },
            {"type": "text", "text": _EXTRACT_PROMPT},
        ]
    else:
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": data,
                },
            },
            {"type": "text", "text": _EXTRACT_PROMPT},
        ]

    result = call_claude_with_log(
        prompt=_EXTRACT_PROMPT,
        model_key="haiku",
        max_tokens=2000,
        company=company,
        site=None,
        task_type=AILog.TaskType.MASTER_EXTRACT,
        input_data={"file_path": str(file_path), "media_type": media_type},
        user=user,
        content=content,
    )

    parsed = result["parsed"]
    if parsed is None:
        # パース失敗時は生テキストから再試行
        text = result["raw"].strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        parsed = json.loads(text)

    if isinstance(parsed, dict):
        parsed = [parsed]

    return parsed
