"""写真/PDFから取引先情報をAI抽出する。

Claude APIのマルチモーダル機能を使い、名刺・書類・PDFから
会社名・代表者・担当者・電話番号・FAX・メール・住所を抽出する。
"""

import base64
import json
import os
from pathlib import Path


def _get_client():
    """Anthropic クライアントを取得。"""
    try:
        import anthropic
    except ImportError as exc:
        raise ImportError(
            "anthropic パッケージが必要です。pip install anthropic を実行してください。"
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY が設定されていません。"
            "環境変数または .env ファイルに設定してください。"
        )
    return anthropic.Anthropic(api_key=api_key)


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


def extract_from_file(file_path):
    """画像/PDFファイルから取引先情報を抽出する。

    Returns:
        list[dict]: 抽出された取引先情報のリスト。
        各dictは name, representative, contact_person, phone, fax, email, address を含む。
    """
    client = _get_client()
    media_type = _get_media_type(file_path)

    if media_type == "application/pdf":
        # PDFはbase64エンコードしてdocumentとして送信
        data = _encode_image(file_path)
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
        # 画像
        data = _encode_image(file_path)
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

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": content}],
    )

    text = response.content[0].text.strip()

    # JSON部分を抽出
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    result = json.loads(text)

    # 単一オブジェクトの場合はリストに変換
    if isinstance(result, dict):
        result = [result]

    return result
