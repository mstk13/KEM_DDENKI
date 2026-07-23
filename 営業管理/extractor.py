"""営業資料（PDF / 画像）から会社名・担当者名・営業内容などを自動抽出する。

Claude API（claude-opus-4-8）の Vision / PDF 入力 + 構造化出力を使う。
- 画像（名刺・チラシ）: image ブロックで送信
- PDF（会社案内・提案書）: document ブロックで送信
会社の事業概要はウェブ検索でも取得できる（overview_from_web）。
"""
import base64
import json
from pathlib import Path

import anthropic

from config import EXTRACT_MODEL, INDUSTRIES, DEFAULT_INDUSTRY

# 拡張子 -> メディアタイプ
_IMAGE_MEDIA = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# 抽出結果の構造（構造化出力）。不明な項目は空文字を返させる。
_SCHEMA = {
    "type": "object",
    "properties": {
        "industry": {
            "type": "string",
            "enum": INDUSTRIES,
            "description": "営業に来た会社の業界カテゴリ。最も近いものを1つ選ぶ。判断できなければ『その他』",
        },
        "company_name": {"type": "string", "description": "営業に来た会社名。不明なら空文字"},
        "rep_name": {"type": "string", "description": "営業担当者の氏名。不明なら空文字"},
        "business_overview": {
            "type": "string",
            "description": "その会社がどのような事業を行っているか（事業内容）を、一目で分かるよう1〜2文で簡潔にまとめる。今回の売り込み内容ではなく会社そのものの事業。不明なら空文字",
        },
        "sales_content": {
            "type": "string",
            "description": "今回の営業内容の要約。何を売り込みに来たか（商材・サービス・目的）を日本語で簡潔にまとめる。不明なら空文字",
        },
        "phone": {"type": "string", "description": "電話番号。不明なら空文字"},
        "email": {"type": "string", "description": "メールアドレス。不明なら空文字"},
        "website": {"type": "string", "description": "会社の公式サイト(HP)のURL。資料に記載があれば。不明なら空文字"},
        "address": {"type": "string", "description": "住所。不明なら空文字"},
        "visit_date": {
            "type": "string",
            "description": "訪問日または資料に記載の日付。YYYY-MM-DD 形式。不明なら空文字",
        },
    },
    "required": ["industry", "company_name", "rep_name", "business_overview", "sales_content", "phone", "email", "website", "address", "visit_date"],
    "additionalProperties": False,
}

_PROMPT = (
    "これは当社に営業に来た会社が持参した資料（名刺・チラシ・会社案内・提案書など）です。"
    "資料から、営業に来た会社名・営業担当者の氏名・その会社の事業概要（何をしている会社か）・"
    "今回の営業内容（何を売り込みに来たか）と、連絡先（電話・メール・住所）、日付を読み取り、"
    "指定のJSON形式で出力してください。読み取れない項目は空文字にしてください。"
    "事業概要と営業内容は資料全体から要約してください。事業概要は会社そのものの事業、"
    "営業内容は今回の提案、というように区別してください。"
)


def _block_from_bytes(filename, data_bytes):
    """（ファイル名, バイト列）を Claude 入力用の content ブロックに変換。"""
    ext = Path(filename).suffix.lower()
    b64 = base64.standard_b64encode(data_bytes).decode("utf-8")
    if ext == ".pdf":
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
        }
    if ext in _IMAGE_MEDIA:
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": _IMAGE_MEDIA[ext], "data": b64},
        }
    raise ValueError(f"未対応のファイル形式です: {filename}")


def _content_block(path: Path):
    path = Path(path)
    return _block_from_bytes(path.name, path.read_bytes())


def _call(blocks) -> dict:
    """content ブロック群を Claude に渡して抽出結果 dict を返す。"""
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY を環境から解決
    resp = client.messages.create(
        model=EXTRACT_MODEL,
        max_tokens=2000,
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": blocks + [{"type": "text", "text": _PROMPT}]}],
    )
    text = next(b.text for b in resp.content if b.type == "text")
    data = json.loads(text)
    if not data.get("visit_date"):
        data["visit_date"] = None
    if data.get("industry") not in INDUSTRIES:
        data["industry"] = DEFAULT_INDUSTRY
    return data


def extract(path) -> dict:
    """1ファイル（ディスク上のパス）を解析して抽出結果 dict を返す。"""
    return _call([_content_block(path)])


def extract_uploads(files) -> dict:
    """アップロードされた複数ファイルをまとめて解析する。

    files: [(ファイル名, バイト列), ...]（名刺＋会社案内などを一括で参照）
    """
    blocks = [_block_from_bytes(name, data) for name, data in files]
    return _call(blocks)


def overview_from_web(company_name, email="", address="", url="") -> str:
    """会社名などから公式HPをウェブ検索し、事業概要を1〜2文で返す。

    ANTHROPIC_API_KEY が必要。ウェブ検索ツールを使うため従量課金が発生する。
    特定できない場合は空文字を返す。
    """
    if not (company_name or url):
        return ""
    hint = f"会社名: {company_name}"
    if url:
        hint += f"\n公式サイト: {url}"
    if email:
        hint += f"\nメールアドレス: {email}（ドメインがHPのヒントになる）"
    if address:
        hint += f"\n所在地: {address}"
    prompt = (
        "次の会社の公式サイト（ホームページ）をウェブ検索で調べ、その会社がどのような事業を"
        "行っているか（事業内容）を、日本語で1〜2文に簡潔に要約してください。"
        "要約の本文のみを出力し、URL・出典・前置き・箇条書きは書かないでください。"
        "同名の別会社と混同しないよう、所在地やメールドメインも手掛かりにしてください。"
        "確実な情報が見つからない場合は、何も推測せず空文字だけを返してください。\n\n" + hint
    )
    client = anthropic.Anthropic()
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]

    def _run(messages):
        resp = client.messages.create(model=EXTRACT_MODEL, max_tokens=1500, tools=tools, messages=messages)
        for _ in range(4):  # サーバー側ツールのループ上限（pause_turn）で継続
            if resp.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": resp.content})
            resp = client.messages.create(model=EXTRACT_MODEL, max_tokens=1500, tools=tools, messages=messages)
        return resp

    # 1) 調査（ウェブ検索。途中経過テキストが混ざる場合がある）
    messages = [{"role": "user", "content": prompt}]
    resp = _run(messages)
    # 2) 調査結果をもとに「要約本文のみ」を出させる
    messages.append({"role": "assistant", "content": resp.content})
    messages.append({
        "role": "user",
        "content": "上記の調査結果に基づき、その会社の事業概要のみを日本語で1〜2文にまとめて出力してください。"
                   "前置き・英語・URL・出典・箇条書きは書かず、要約の本文だけを返してください。"
                   "事業内容が特定できない場合は空文字だけを返してください。",
    })
    resp = _run(messages)
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return _clean_overview(text)


def _clean_overview(text) -> str:
    """先頭の英語前置きなどを除去し、最初の日本語文字以降を返す。"""
    if not text:
        return ""
    import re
    text = re.sub(r"<[^>]+>", "", text)      # <cite> 等のタグを除去
    text = re.sub(r"[ \t]+", " ", text).strip()
    m = re.search(r"[一-龥ぁ-んァ-ヶ０-９]", text)
    if m:
        text = text[m.start():]
    return text.strip()


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("使い方: python extractor.py <資料ファイル>")
        sys.exit(1)
    print(json.dumps(extract(sys.argv[1]), ensure_ascii=False, indent=2))
