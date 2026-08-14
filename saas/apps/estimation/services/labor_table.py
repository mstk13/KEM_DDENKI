"""労務単価表の決定論的パーサ。

公共工事設計労務単価の単価表は「都道府県(行) × 職種(列)」という
規則的な構造を持つ。この形であれば LLM を通す必要はなく、
表の座標から直接読める。

実測（令和8年3月版 p.3, 正解422件）:

| 手段 | 抽出 | 適合率 | 再現率 | 所要 | 費用 |
|---|---:|---:|---:|---:|---:|
| このパーサ | 422件 | 1.000 | 1.000 | 0.01秒 | 0円 |
| ローカル Qwen3-8B | 373件 | 0.678 | 0.600 | 315秒 | 0円 |
| Claude Haiku | 88件 | 0.091 | 0.019 | 18秒 | 3.7円 |

LLM は「表の形が崩れているページ」のための保険であり、
規則的な表に対しては使わない。ADR-0010 の3層分割でいえば、
層Bへ渡す前に層0（決定論的処理）で片を付けるのが正しい。
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 「01 北海道」「13 東京都」のような都道府県セル
PREFECTURE_CELL = re.compile(r"^\s*(\d{2})\s+(\S+?[都道府県])\s*$")

# 単価セル。「26,000」「26000」を受け、「-」「※」「空」は単価なしとみなす
PRICE_CELL = re.compile(r"^-?[\d,]+$")

# 都道府県名の列は先頭から2列目という前提。表の左端は地方連絡協議会名
PREFECTURE_COLUMN = 1
FIRST_JOB_COLUMN = 2


@dataclass(frozen=True)
class LaborRateRow:
    """1つの (都道府県, 職種, 単価) の組。"""

    prefecture: str
    prefecture_code: str
    occupation_name: str
    unit_price: int | None

    def key(self) -> tuple[str, str]:
        return (self.prefecture, self.occupation_name)


def _clean(cell) -> str:
    return (cell or "").replace("\n", "").strip()


def parse_rate_table(table: list[list]) -> list[LaborRateRow]:
    """1つの表から (都道府県, 職種, 単価) を取り出す。

    ヘッダー行の3列目以降を職種名とみなし、
    以降の行のうち都道府県セルを持つものだけを対象にする。
    単価が読めないセル（空欄・「-」・注記）は unit_price=None を返す。
    0 にはしない。0円の労務単価は存在せず、集計を狂わせるため。
    """
    if not table or len(table) < 2:
        return []

    header = [_clean(c) for c in table[0]]
    jobs = {
        i: name
        for i, name in enumerate(header)
        if i >= FIRST_JOB_COLUMN and name
    }
    if not jobs:
        return []

    rows: list[LaborRateRow] = []
    for raw_row in table[1:]:
        cells = [_clean(c) for c in raw_row]
        if len(cells) <= PREFECTURE_COLUMN:
            continue

        matched = PREFECTURE_CELL.match(cells[PREFECTURE_COLUMN])
        if not matched:
            # 地方連絡協議会の見出し行や空行
            continue
        code, prefecture = matched.group(1), matched.group(2)

        for column, job in jobs.items():
            if column >= len(cells):
                continue
            value = cells[column].replace(",", "")
            price = int(value) if PRICE_CELL.match(cells[column]) and value.isdigit() else None
            rows.append(
                LaborRateRow(
                    prefecture=prefecture,
                    prefecture_code=code,
                    occupation_name=job,
                    unit_price=price,
                )
            )
    return rows


def parse_page(tables: list[list[list]]) -> list[LaborRateRow]:
    """1ページ分（複数表）をまとめて解析する。"""
    rows: list[LaborRateRow] = []
    for table in tables:
        rows.extend(parse_rate_table(table))
    return rows


def looks_like_rate_table(tables: list[list[list]]) -> bool:
    """このページを決定論的に読めるか判定する。

    読めるなら LLM を呼ぶ必要はない。読めない場合だけ層B（LLM）へ回す。
    """
    for table in tables:
        if not table or len(table) < 2:
            continue
        header = [_clean(c) for c in table[0]]
        if not any(header[FIRST_JOB_COLUMN:]):
            continue
        for raw_row in table[1:]:
            cells = [_clean(c) for c in raw_row]
            if len(cells) > PREFECTURE_COLUMN and PREFECTURE_CELL.match(
                cells[PREFECTURE_COLUMN]
            ):
                return True
    return False
