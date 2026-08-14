"""公告PDFを Claude に読ませて工事概要・参加要件を取り出す（最後の手段）。

announcement.py の決定論的な抽出が使えない場合だけ通る道。

なぜ必要か:
  発注機関によっては、公告PDFのフォントに ToUnicode が無く、
  pdfplumber が (cid:NNN) しか取り出せないものがある
  （2026-08-14 時点で本番65件中1件。立川防災合同庁舎（２６）電気設備改修工事）。
  この案件は他の公開文書も指名結果書だけで、章立てを持つ文書が存在しない。

なぜ OCR ではなく Claude か:
  tesseract を入れると Dockerfile にシステムパッケージが増え、
  本番イメージのビルドが失敗すると自動デプロイが止まる。
  一方 anthropic は既に依存にあり、APIキーの設定枠も予算監視も揃っている。
  Claude は PDF をページ画像としても読むので cid 化していても中身が取れる。

コスト:
  1件あたり11ページで入力2万トークン前後。Sonnet で $0.06 程度（¥10弱）。
  決定論的な抽出が失敗した案件だけなので、月数件を想定している。
  月間予算（AI_MONTHLY_BUDGET_JPY）のチェックは call_claude_with_log が行う。
"""
from __future__ import annotations

import base64
import logging

logger = logging.getLogger(__name__)

# Claude の PDF 入力の上限。これを超えるものは投げない。
MAX_PDF_BYTES = 30 * 1024 * 1024  # リクエスト全体の上限32MBに対する安全側
MAX_PDF_PAGES = 100

# 抽出タスクなので分析系より安いモデルを使う。
# llm_advisor の MODEL_CONFIG のキー（"haiku" / "sonnet"）。
# 参加要件の読み違いは入札可否の判断を誤らせるので、
# OCR相当とはいえ Haiku ではなく Sonnet を既定にしている。
MODEL_KEY = "sonnet"
# Claude Sonnet 5 は thinking を指定しないと adaptive thinking が既定で有効になり、
# max_tokens は thinking と本文の合計に効く。参加要件は原文をそのまま返させるので
# 2,000字を超えることがあり、4,000 では本文が切れる余地があった。
MAX_TOKENS = 12000

SYSTEM_PROMPT = (
    "あなたは日本の公共工事の入札公告を読む担当者です。"
    "PDFに書かれていることだけを根拠に答えてください。"
    "書かれていない項目は推測せず空にしてください。"
    "常にJSON形式のみで回答してください。"
)

INSTRUCTION = """このPDFは日本の官公庁が公開した入札公告です。
次のJSONだけを返してください。前後に説明文やコードブロックを付けないでください。

{
  "work_outline": "工事概要にあたる部分の本文。工事名・工事場所・工事内容・工期など。原文の表現をそのまま使う",
  "requirements": "競争参加資格（入札に参加するための要件）にあたる部分の本文。原文の表現をそのまま使う",
  "required_grades": "参加資格として認定を求められている等級。A〜Dの該当するものを並べる。例: BC。書かれていなければ空文字",
  "required_score": 総合審査数値・経営事項評価数値の下限（整数）。書かれていなければ null
}

注意:
- required_grades は「B等級又はC等級に認定されている者」のような列挙をそのまま集めます。
  「以上」と書かれている場合も、該当する等級を並べてください。
- required_score は資格審査の点数です。
  「工事成績評定点が65点未満のものを除く」「65点以上の工事とみなす」は
  過去の工事成績の話なので、ここには入れないでください。
- 共同企業体の構成員向けに緩い点数が併記されている場合は、
  単体で参加する場合に必要な厳しいほうを採ってください。
- 該当する記載が無ければ、文字列は空文字、数値は null にしてください。
"""


def is_available() -> bool:
    """LLM での読み取りが使える状態か。"""
    from apps.ai.services.llm_advisor import check_availability

    available, reason = check_availability()
    if not available:
        logger.info("公告のLLM読み取りは使えません: %s", reason)
    return available


def _page_count(pdf_bytes: bytes) -> int | None:
    try:
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return len(pdf.pages)
    except Exception:
        return None


def extract_with_llm(pdf_bytes: bytes, company, user=None) -> dict | None:
    """公告PDFを Claude に読ませる。読めなければ None。

    Args:
        pdf_bytes: PDFのバイト列
        company: テナント（予算チェックとログに必要）
        user: 実行者（任意）

    Returns:
        {"work_outline", "requirements", "required_grades", "required_score"}
        または None
    """
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        return None
    if company is None:
        # 予算チェックが効かなくなるので会社なしでは呼ばない
        logger.warning("company が無いため公告のLLM読み取りを行いません")
        return None
    if len(pdf_bytes) > MAX_PDF_BYTES:
        logger.warning(
            "公告PDFが大きすぎます（%dバイト）。LLM読み取りを行いません", len(pdf_bytes)
        )
        return None

    pages = _page_count(pdf_bytes)
    if pages is not None and pages > MAX_PDF_PAGES:
        logger.warning(
            "公告PDFのページ数が多すぎます（%dページ）。LLM読み取りを行いません", pages
        )
        return None

    from apps.ai.models import AILog
    from apps.ai.services.llm_advisor import call_claude_with_log

    content = [
        {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(pdf_bytes).decode("ascii"),
            },
        },
        {"type": "text", "text": INSTRUCTION},
    ]

    try:
        result = call_claude_with_log(
            prompt=INSTRUCTION,
            model_key=MODEL_KEY,
            max_tokens=MAX_TOKENS,
            company=company,
            site=None,  # 入札案件は現場に紐づかない
            task_type=AILog.TaskType.GENERAL_ANALYSIS,
            input_data={"source": "bid_announcement_pdf", "pages": pages},
            user=user,
            system_prompt=SYSTEM_PROMPT,
            content=content,
        )
    except Exception as e:
        # 予算超過・APIキー未設定・API側の障害。案件取得自体は失敗させない。
        logger.warning("公告のLLM読み取りに失敗しました: %s", e)
        return None

    parsed = result.get("parsed")
    if not isinstance(parsed, dict):
        logger.warning("公告のLLM読み取りの応答をJSONとして読めませんでした")
        return None

    logger.info(
        "公告をLLMで読み取りました（%s, $%s）",
        result.get("ai_log_id"), result.get("cost_usd"),
    )
    return _normalize(parsed)


def _normalize(parsed: dict) -> dict:
    """LLMの応答を announcement.extract_sections と同じ形に揃える。"""
    grades = "".join(
        sorted({
            c for c in str(parsed.get("required_grades") or "").upper()
            if c in "ABCD"
        })
    )

    score = parsed.get("required_score")
    try:
        score = int(score) if score not in (None, "") else None
    except (TypeError, ValueError):
        score = None

    return {
        "work_outline": str(parsed.get("work_outline") or "").strip(),
        "requirements": str(parsed.get("requirements") or "").strip(),
        "required_grade": "",  # 下限表記はLLMには判定させない（列挙と混ざるため）
        "required_grades": grades,
        "required_score": score,
        "headings": [],
        "garbled": False,
        "by_llm": True,
    }
