"""公共工事設計労務単価の PDF 取込パイプライン。

国土交通省は労務単価を PDFのみ で配布している（Excelなし）。
公表元: https://www.mlit.go.jp/report/press/tochi_fudousan_kensetsugyo14_hh_000001_00337.html

パイプライン:
[1] PDFファイルを読み込み・保存（原本は必ず残す）
[2] pdfplumber で都道府県ごとのページ表を抽出
[3] Claude API で構造化（JSON出力を厳格に指定）
[4] LaborRate に status='draft' で投入
[5] レビュー画面で人間が確認 → status='approved'
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.conf import settings

from apps.estimation.models import LaborRate
from apps.estimation.services import labor_table

logger = logging.getLogger(__name__)

try:
    import pdfplumber

    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    import anthropic

    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


@dataclass
class PageTable:
    """pdfplumber から抽出した1ページ分の表データ。"""
    page_number: int
    raw_text: str
    tables: list[list[list[str | None]]] = field(default_factory=list)


@dataclass
class LaborRateDraft:
    """構造化後の1レコード。"""
    prefecture: str
    occupation_code: str
    occupation_name: str
    unit_price: int | None  # 未設定職種は None
    valid_from: date
    fiscal_year_label: str = ""


@dataclass
class ImportResult:
    """インポート結果。"""
    created: int = 0
    updated: int = 0
    skipped: int = 0
    total: int = 0
    batch_id: str = ""
    errors: list[str] = field(default_factory=list)


# ===================================================================
# [1] PDF読み込み
# ===================================================================


def read_pdf(file_path: str) -> tuple[bytes, str]:
    """PDFファイルを読み込み、(バイト列, SHA-256ハッシュ) を返す。"""
    with open(file_path, "rb") as f:
        pdf_bytes = f.read()
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    return pdf_bytes, sha256


# ===================================================================
# [2] pdfplumber で表抽出
# ===================================================================


def extract_tables_from_pdf(pdf_bytes: bytes) -> list[PageTable]:
    """pdfplumber で全ページの表を抽出する。

    注意:
    - 縦書き職種名は pdfplumber では完全には対応できない場合がある
    - セル結合は pdfplumber が自動展開する
    - 空セルは None になる
    """
    if not HAS_PDFPLUMBER:
        raise ImportError(
            "pdfplumber がインストールされていません。"
            "pip install pdfplumber を実行してください。"
        )

    import io

    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages):
            raw_text = page.extract_text() or ""
            tables = page.extract_tables() or []
            if tables or raw_text.strip():
                pages.append(PageTable(
                    page_number=i + 1,
                    raw_text=raw_text,
                    tables=tables,
                ))

    logger.info(f"PDF解析完了: {len(pages)}ページから表を抽出")
    return pages


# ===================================================================
# [3] Claude API で構造化
# ===================================================================

# 1ページ分の構造化出力の上限。到達すると JSON が途中で切れる。
# 令和8年3月版の単価表は1ページ400件超あり、この上限では到底収まらない。
# そうしたページは labor_table の決定論的パーサで処理する前提。
STRUCTURE_MAX_TOKENS = 4000

STRUCTURE_SYSTEM_PROMPT = (
    "あなたは日本の公共工事設計労務単価のPDFから表を読み取る専門家です。"
    "入力されたテキストや表データから、都道府県名・職種名・単価を正確に抽出してください。"
    "必ずJSON形式で回答してください。"
)

STRUCTURE_USER_PROMPT = """\
以下は国土交通省「公共工事設計労務単価」PDFの{page_number}ページ目から抽出したデータです。

## 抽出テキスト:
{raw_text}

## 抽出された表データ:
{tables_json}

このデータから労務単価を構造化してください。以下のJSON形式で出力してください:

```json
{{
  "prefecture": "都道府県名（例: 神奈川県）",
  "rates": [
    {{
      "occupation_name": "職種名（例: 電工）",
      "occupation_code": "職種コード（わかれば。不明なら空文字）",
      "unit_price": 25600
    }}
  ]
}}
```

重要なルール:
- unit_price は整数（円/人日）。カンマや円記号を含めないこと
- 単価が設定されていない職種（空欄、「-」、「※」等）は unit_price を null にすること。0にしてはならない
- 都道府県名が特定できない場合は prefecture を "不明" にすること
- 表のヘッダー行や注記は除外すること
"""


def _get_api_key():
    """既存の AI サービスと同じ方法で API キーを取得する。"""
    api_key = getattr(settings, "ANTHROPIC_API_KEY", None)
    if not api_key:
        import os
        api_key = os.environ.get("ANTHROPIC_API_KEY")
    return api_key


def _parse_json(text: str) -> dict:
    """LLM レスポンスから JSON を抽出してパースする。

    出力が max_tokens で途中終了すると閉じフェンス ``` が付かない。
    旧実装は text.index("```", start) が ValueError になり、
    呼び出し側がそれを握り潰して全件を捨てていた（実データで確認）。
    ここでは開始フェンスだけでも処理し、閉じが無ければ残り全部を対象にする。
    """
    body = text
    for fence in ("```json", "```"):
        if fence in body:
            body = body.split(fence, 1)[1]
            break
    # 閉じフェンスがあればそこまで。無ければ末尾まで。
    body = body.split("```", 1)[0].strip()
    return json.loads(body)


def structure_page_with_llm(
    page: PageTable,
    valid_from: date,
    fiscal_year_label: str = "",
) -> list[LaborRateDraft]:
    """Claude API で1ページ分の表データを構造化する。"""
    if not HAS_ANTHROPIC:
        raise ImportError("anthropic がインストールされていません。")

    api_key = _get_api_key()
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY が設定されていません。")

    client = anthropic.Anthropic(api_key=api_key)

    tables_json = json.dumps(page.tables, ensure_ascii=False, indent=2)
    user_prompt = STRUCTURE_USER_PROMPT.format(
        page_number=page.page_number,
        raw_text=page.raw_text[:3000],
        tables_json=tables_json[:5000],
    )

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=STRUCTURE_MAX_TOKENS,
        system=[{
            "type": "text",
            "text": STRUCTURE_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_prompt}],
    )

    result_text = response.content[0].text
    logger.info(
        f"Page {page.page_number}: "
        f"input={response.usage.input_tokens}, output={response.usage.output_tokens}"
    )

    # 出力が上限で切られたら黙って部分結果を返さない。
    # 実データ（令和8年3月版 p.3、正解422件）で max_tokens=4000 に到達し、
    # 途中で切れた JSON が捨てられて0件になっていた。
    # 件数が多いページは LLM ではなく labor_table の決定論的パーサで処理する。
    if response.stop_reason == "max_tokens":
        logger.error(
            "Page %s: 出力が max_tokens(%s) に到達し切り捨てられました。"
            "このページは件数が多すぎます。決定論的パーサの利用を検討してください。",
            page.page_number, STRUCTURE_MAX_TOKENS,
        )

    try:
        data = _parse_json(result_text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Page {page.page_number}: JSON parse error: {e}")
        return []

    prefecture = data.get("prefecture", "不明")
    drafts = []
    for rate in data.get("rates", []):
        drafts.append(LaborRateDraft(
            prefecture=prefecture,
            occupation_code=rate.get("occupation_code", ""),
            occupation_name=rate.get("occupation_name", ""),
            unit_price=rate.get("unit_price"),
            valid_from=valid_from,
            fiscal_year_label=fiscal_year_label,
        ))

    return drafts


def structure_page_deterministic(
    page: PageTable,
    valid_from: date,
    fiscal_year_label: str = "",
) -> list[LaborRateDraft]:
    """表の座標から直接読む。LLM を使わない。

    「都道府県(行) × 職種(列)」の規則的な表であればこれで完全に読める。
    実測で適合率・再現率とも 1.000（LLM は 0.03〜0.64）。
    """
    rows = labor_table.parse_page(page.tables)
    return [
        LaborRateDraft(
            prefecture=row.prefecture,
            occupation_code=row.prefecture_code,
            occupation_name=row.occupation_name,
            unit_price=row.unit_price,
            valid_from=valid_from,
            fiscal_year_label=fiscal_year_label,
        )
        for row in rows
    ]


def structure_all_pages(
    pages: list[PageTable],
    valid_from: date,
    fiscal_year_label: str = "",
    *,
    use_llm_fallback: bool = True,
) -> list[LaborRateDraft]:
    """全ページを構造化する。

    規則的な単価表は決定論的に読み、読めないページだけ LLM に回す。
    LLM を先に通していた頃は、1ページ400件超の表で出力が
    max_tokens に達して切り捨てられ、静かに0件になっていた。
    """
    all_drafts = []
    for page in pages:
        if not page.tables and len(page.raw_text.strip()) < 50:
            continue

        if labor_table.looks_like_rate_table(page.tables):
            drafts = structure_page_deterministic(
                page, valid_from, fiscal_year_label,
            )
            logger.info(
                "Page %s: 決定論的パーサで %d 件（LLM未使用）",
                page.page_number, len(drafts),
            )
            all_drafts.extend(drafts)
            continue

        if not use_llm_fallback:
            logger.info("Page %s: 決定論的に読めずスキップ", page.page_number)
            continue

        try:
            drafts = structure_page_with_llm(page, valid_from, fiscal_year_label)
            all_drafts.extend(drafts)
        except Exception as e:
            logger.error(f"Page {page.page_number}: 構造化エラー: {e}")
    return all_drafts


# ===================================================================
# [4] LaborRate に投入
# ===================================================================


def load_drafts(
    drafts: list[LaborRateDraft],
    company,
    batch_id: str,
) -> ImportResult:
    """LaborRate に status='draft' で投入する。"""
    result = ImportResult(batch_id=batch_id, total=len(drafts))

    for draft in drafts:
        if draft.prefecture == "不明":
            result.errors.append(f"都道府県不明: {draft.occupation_name}")
            result.skipped += 1
            continue

        defaults = {
            "occupation_name": draft.occupation_name,
            "fiscal_year_label": draft.fiscal_year_label,
            "status": "draft",
            "data_scope": "public",
            "import_batch": batch_id,
        }

        if draft.unit_price is not None:
            defaults["unit_price"] = Decimal(str(draft.unit_price))
        else:
            defaults["unit_price"] = None

        _, was_created = LaborRate.unscoped.update_or_create(  # unscoped: company を明示指定
            company=company,
            prefecture=draft.prefecture,
            occupation_code=draft.occupation_code or draft.occupation_name,
            valid_from=draft.valid_from,
            defaults=defaults,
        )
        if was_created:
            result.created += 1
        else:
            result.updated += 1

    return result


# ===================================================================
# 統合パイプライン
# ===================================================================


def import_labor_rates_from_pdf(
    file_path: str,
    valid_from: date,
    company,
    *,
    fiscal_year_label: str = "",
) -> ImportResult:
    """PDFファイルから労務単価をインポートする統合パイプライン。

    [1] PDF読み込み → [2] 表抽出 → [3] LLM構造化 → [4] DB投入
    """
    batch_id = f"pdf_{valid_from}_{date.today().isoformat()}"

    # [1] 読み込み
    pdf_bytes, sha256 = read_pdf(file_path)
    logger.info(f"PDF読み込み完了: hash={sha256[:12]}")

    # [2] 表抽出
    pages = extract_tables_from_pdf(pdf_bytes)
    if not pages:
        return ImportResult(batch_id=batch_id, errors=["PDFから表を抽出できませんでした"])

    # [3] LLM構造化
    drafts = structure_all_pages(pages, valid_from, fiscal_year_label)
    if not drafts:
        return ImportResult(batch_id=batch_id, errors=["構造化されたデータがありません"])

    # [4] DB投入
    result = load_drafts(drafts, company, batch_id)
    logger.info(
        f"インポート完了: created={result.created}, "
        f"updated={result.updated}, skipped={result.skipped}"
    )
    return result
