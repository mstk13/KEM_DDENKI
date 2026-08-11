"""公共工事設計労務単価の PDF 取込パイプライン。

国土交通省は労務単価を **PDFのみ** で配布している（Excelなし）。
公表元: https://www.mlit.go.jp/report/press/tochi_fudousan_kensetsugyo14_hh_000001_00337.html

PDFの構造上の注意:
- 職種名が縦書きのセルがある
- セル結合が多用されている
- 都道府県ごとにページが分かれている → 1県分のパーサを作り47回まわす
- 職種数は都道府県により異なる（有効標本数が不足で単価未設定の職種がある）
  → 未設定は unit_price=None。0を入れてはならない

パイプライン:
[1] PDFを取得・保存（原本は必ず残す）
[2] pdfplumber で都道府県ごとのページ表を抽出
[3] Claude API で構造化（JSON出力を厳格に指定）
[4] LaborRate に status='draft' で投入
[5] レビュー画面で人間が確認 → status='approved'
[6] approved のみが積算計算に使われる
"""

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.estimation.models import LaborRate


@dataclass
class PageTable:
    """pdfplumber から抽出した1ページ分の表データ。"""

    page_number: int
    prefecture: str
    headers: list[str]
    rows: list[list[str | None]]


@dataclass
class LaborRateDraft:
    """構造化後の1レコード分のデータ。"""

    prefecture: str
    occupation_code: str
    occupation_name: str
    unit_price: Decimal | None  # 未設定職種は None。0を入れないこと
    valid_from: date
    fiscal_year_label: str


@dataclass
class ImportResult:
    """インポート結果。"""

    created: int
    updated: int
    skipped: int  # unit_price=None のレコード数
    total: int
    batch_id: str


def fetch_labor_rate_pdf(source_url: str, save_dir: str) -> tuple[bytes, str]:
    """PDFを取得し、(バイト列, sha256ハッシュ) を返す。

    原本は save_dir にファイル保存する（再抽出・監査用）。

    TODO: 実装。requests で取得し、ファイル保存 + ハッシュ計算。
    """
    raise NotImplementedError(
        "PDF取得は未実装。pdfplumber + Claude API の環境準備後に実装する。"
    )


def extract_tables(pdf_bytes: bytes) -> list[PageTable]:
    """pdfplumber で都道府県ごとのページ表を抽出する。

    注意:
    - 縦書き職種名のハンドリングが必要
    - セル結合の展開が必要
    - 1県分のパーサを作り47回まわす設計

    TODO: 実装。pdfplumber.open() で各ページを解析。
    """
    raise NotImplementedError(
        "PDF表抽出は未実装。pdfplumber の環境準備後に実装する。"
    )


def structure_with_llm(page_table: PageTable, valid_from: date) -> list[LaborRateDraft]:
    """Claude API で構造化。JSON schema を厳格指定。

    未設定職種は unit_price=None で返すこと。0を入れてはならない。

    TODO: 実装。Claude API の Anthropic SDK で構造化出力。
    """
    raise NotImplementedError(
        "LLM構造化は未実装。ANTHROPIC_API_KEY 設定後に実装する。"
    )


def load_drafts(
    drafts: list[LaborRateDraft],
    company,
    batch_id: str,
) -> ImportResult:
    """LaborRate に status='draft' で投入する。

    unit_price=None のレコードも保存する（未設定を明示するため）。
    """
    created = 0
    updated = 0
    skipped = 0

    for draft in drafts:
        if draft.unit_price is None:
            skipped += 1
            continue

        _, was_created = LaborRate.unscoped.update_or_create(  # unscoped: company を明示指定
            company=company,
            prefecture=draft.prefecture,
            occupation_code=draft.occupation_code,
            valid_from=draft.valid_from,
            defaults={
                "occupation_name": draft.occupation_name,
                "unit_price": draft.unit_price,
                "fiscal_year_label": draft.fiscal_year_label,
                "status": "draft",
                "import_batch": batch_id,
            },
        )
        if was_created:
            created += 1
        else:
            updated += 1

    return ImportResult(
        created=created,
        updated=updated,
        skipped=skipped,
        total=len(drafts),
        batch_id=batch_id,
    )
