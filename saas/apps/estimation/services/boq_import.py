"""内訳書・内訳明細書の取込サービス（Excel / PDF）。

現場詳細から内訳書ファイルを読み込んで BoqLine に落とす。

方針は labor_pdf の教訓に従う:

- **決定論的に読めるものを LLM に通さない。** 内訳書は「名称・仕様・単位・
  数量・単価・金額」の列を持つ表なので、ヘッダー行さえ見つかれば
  表の座標から直接読める。実際 labor_pdf では決定論的パーサが
  適合率・再現率 1.000 に対し LLM は 0.64 だった
- LLM は「表として抽出できなかったページ」だけの保険にする。
  ADR-0010 の層B（ローカル推論）を使い、届かなければ静かに諦める
- **黙って0件にしない。** 読めなかった理由は warnings に積んで画面に出す

階層（種目別→科目別→中科目別→細目別）は次の順で決める:

1. 「階層」列があればそれに従う（自社が出力した Excel を読み戻す場合）
2. **数量と単価がそろっている行は細目別（内訳明細書）。**
   内訳明細書とは「数量×単価で金額を積む階層」のことなので、
   インデントの深さではなくこの有無で決めるのが実態に合う
3. 名称のインデント（先頭の空白・全角空白）の深さ＝見出しの深さ
4. どれも無ければ、金額などを持つ行を細目別、持たない行を科目別とみなす
"""

import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from apps.estimation.models import BoqLine

logger = logging.getLogger(__name__)

try:
    import openpyxl

    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

try:
    import pdfplumber

    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


# 列見出しの揺れ。内訳書の様式は発注者ごとに違うので、代表的な別名を並べる。
# 先に並べたものから順に照合するため、より具体的な語を先に置く。
COLUMN_ALIASES = {
    "level": ("階層", "レベル", "区分"),
    "name": ("名称", "工種", "品名", "品目", "項目", "工事区分"),
    "spec": ("規格・仕様", "規格仕様", "仕様", "規格", "摘要"),
    "unit": ("単位",),
    "quantity": ("数量",),
    "unit_price": ("単価",),
    "amount": ("金額",),
    "remarks": ("備考", "摘要欄"),
}

# 名称列がこの語だけの行は小計行。明細として取り込むと二重計上になる。
SUBTOTAL_WORDS = ("小計", "合計", "計", "総計", "小　計", "合　計", "計上額")

# 小計行を括る括弧。名称と一緒に読むので、照合前に外す。
BRACKET_CHARS = "【】〔〕[]［］（）()《》〈〉「」"

# 「一式」は数量が読めない行。0 を入れると読めた 0 と区別できなくなる。
LUMP_SUM_WORDS = ("一式", "1式", "式")

LEVEL_BY_LABEL = {
    "種目": BoqLine.Level.SHUMOKU,
    "種目別": BoqLine.Level.SHUMOKU,
    "種目別内訳書": BoqLine.Level.SHUMOKU,
    "科目": BoqLine.Level.KAMOKU,
    "科目別": BoqLine.Level.KAMOKU,
    "科目別内訳書": BoqLine.Level.KAMOKU,
    "中科目": BoqLine.Level.CHUKAMOKU,
    "中科目別": BoqLine.Level.CHUKAMOKU,
    "中科目別内訳書": BoqLine.Level.CHUKAMOKU,
    "細目": BoqLine.Level.SAIMOKU,
    "細目別": BoqLine.Level.SAIMOKU,
    "細目別内訳書": BoqLine.Level.SAIMOKU,
    "明細": BoqLine.Level.SAIMOKU,
    "内訳明細書": BoqLine.Level.SAIMOKU,
}

LEVEL_BY_DEPTH = [
    BoqLine.Level.SHUMOKU,
    BoqLine.Level.KAMOKU,
    BoqLine.Level.CHUKAMOKU,
    BoqLine.Level.SAIMOKU,
]

# インデント何文字で1段とみなすか。Excel の手入力は全角空白1つ、
# 半角空白2つのどちらもよく使われる。
INDENT_UNIT = 2

# セルから最初の数値を切り出す。NFKC 済みの文字列に当てる。
NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

# 同上。NFKC 前の生文字列に当てるので全角の数字・記号も受ける。
RAW_NUMBER_RE = re.compile(
    r"[-－]?[\d０-９][\d０-９,，]*"
    r"(?:[.．][\d０-９]+)?"
)

# ページ見出し。同じ PDF に両方あるとき、内訳書は内訳明細書の集計なので
# 取り込むと二重計上になる。より具体的な「内訳明細書」から先に照合する。
DETAIL_PAGE_TITLES = ("内訳明細書", "細目別内訳書")
SUMMARY_PAGE_TITLES = (
    "内訳書", "種目別内訳書", "科目別内訳書", "中科目別内訳書",
)


@dataclass
class BoqDraft:
    """取り込んだ1行。DB に入れる前の中間表現。"""

    level: str
    name: str
    spec: str = ""
    unit: str = ""
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    remarks: str = ""
    source_row: int = 0


@dataclass
class ParseResult:
    drafts: list[BoqDraft] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def meisai_count(self) -> int:
        """内訳明細書（細目別）の行数。"""
        return sum(1 for d in self.drafts if d.level == BoqLine.MEISAI_LEVEL)


# ---------------------------------------------------------------------------
# 値の正規化
# ---------------------------------------------------------------------------


def _text(value) -> str:
    """セルの値を文字列にする。全角英数は半角へ寄せる。"""
    if value is None:
        return ""
    if isinstance(value, str):
        # NFKC で全角英数・記号を半角へ。日本語の全角空白も半角空白になる。
        return unicodedata.normalize("NFKC", value).strip()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _indent_depth(raw: str) -> int:
    """名称の先頭空白からインデントの段数を数える。

    NFKC 前の生文字列を渡すこと。全角空白は NFKC で半角空白になるため、
    正規化後だと「全角1つ＝1段」の意図が失われる。
    """
    if not raw:
        return 0
    stripped = raw.lstrip(" 　\t")
    lead = raw[: len(raw) - len(stripped)]
    # 全角空白は1つで1段、半角空白は INDENT_UNIT 個で1段。
    width = sum(2 if ch in ("　", "\t") else 1 for ch in lead)
    return width // INDENT_UNIT


def _to_decimal(value) -> Decimal | None:
    """数量・単価・金額のセルを Decimal にする。読めなければ None。

    None を返すのは「読めなかった」の意味で、0 とは区別する。
    一式計上の行を 0 にすると、単価0円の行と見分けがつかなくなる。
    """
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None

    text = unicodedata.normalize("NFKC", str(value)).strip()
    if not text:
        return None
    if any(word in text for word in LUMP_SUM_WORDS) and not re.search(r"\d", text):
        return None

    # **数字以外を消すのではなく、最初の数値だけを取り出す。**
    # 消す方式だと単位記号が数量に混ざる。NFKC は ㎡ を "m2"、㎥ を "m3" に
    # 展開するため、英字だけ落とすと「0.66㎡」が 0.662 になっていた。
    # 金額は ¥ しか付かないので気づかれず、数量×単価だけが合わなくなる。
    matched = NUMBER_RE.search(text)
    if not matched:
        return None
    try:
        return Decimal(matched.group().replace(",", ""))
    except InvalidOperation:
        return None


def _split_unit(value) -> str:
    """数量セルに同居している単位を取り出す。読めなければ空文字。

    単位列を持たない様式では「0.66㎥(立方メートル)」のように数量と単位が
    同じセルに入る。数値の後ろに残った文字を単位とみなす。

    NFKC を通さないのは、㎥ を "m3" に崩さないため。カッコ書きの読み仮名
    （立方メートル）は単位そのものではないので落とす。
    """
    if not isinstance(value, str):
        return ""
    matched = RAW_NUMBER_RE.search(value)
    if not matched:
        return ""
    tail = value[matched.end():].strip()
    tail = re.split(r"[(（\[［]", tail)[0].strip()
    return tail[:50]


def _is_subtotal(name: str) -> bool:
    compact = name.replace(" ", "").replace("　", "")
    # 「【合計】」のように括る様式がある。括弧を外してから照合する。
    return compact.strip(BRACKET_CHARS) in SUBTOTAL_WORDS


# ---------------------------------------------------------------------------
# 表 → BoqDraft
# ---------------------------------------------------------------------------


def _find_header(rows: list[list], scan_limit: int = 30) -> tuple[int, dict] | None:
    """ヘッダー行を探して {フィールド名: 列番号} を返す。

    「名称」に相当する列があり、かつ数量・単価・金額のどれかがある行を
    ヘッダーとみなす。表紙や工事名の行を誤ってヘッダーにしないため、
    金額系の列を必須にしている。
    """
    for row_index, row in enumerate(rows[:scan_limit]):
        mapping = {}
        for col_index, cell in enumerate(row):
            label = _text(cell).replace(" ", "")
            if not label:
                continue
            for field_name, aliases in COLUMN_ALIASES.items():
                if field_name in mapping:
                    continue
                if any(label == alias or label.startswith(alias) for alias in aliases):
                    mapping[field_name] = col_index
                    break
        if "name" in mapping and (
            {"quantity", "unit_price", "amount"} & set(mapping)
        ):
            return row_index, mapping
    return None


def _levels_by_rank(rank_count: int, *, deepest_is_priced: bool) -> list[str]:
    """インデントの段の**順位**を階層に割り当てる。

    幅の絶対値ではなく順位で見るので、2段の様式でも4段の様式でも
    同じ規則で読める（実ファイルのインデント幅はばらつく）。

    - いちばん浅い段は種目別
    - いちばん深い段は、そこに数量×単価のそろう行があれば細目別に固定する
    - 間の段を科目別・中科目別で順に埋め、あふれたら中科目別にまとめる
    """
    levels: list[str | None] = [None] * rank_count
    levels[0] = BoqLine.Level.SHUMOKU

    ceiling = LEVEL_BY_DEPTH.index(BoqLine.Level.SAIMOKU)
    if deepest_is_priced:
        levels[-1] = BoqLine.Level.SAIMOKU
        # 間の段が細目別まで届くと、最深段と見分けがつかなくなる。
        ceiling = LEVEL_BY_DEPTH.index(BoqLine.Level.CHUKAMOKU)

    depth = 1
    for index in range(1, rank_count):
        if levels[index] is not None:
            continue
        levels[index] = LEVEL_BY_DEPTH[min(depth, ceiling)]
        depth += 1
    return levels  # type: ignore[return-value]


def _resolve_level(raw_name: str, level_label: str, *,
                   is_priced: bool, has_numbers: bool, uses_indent: bool,
                   rank_level: str | None = None, is_leaf: bool = False) -> str:
    """階層を決める。

    優先順:

    1. 「階層」列があればそれに従う
    2. **インデントを使う様式なら、段の順位から決める**（`_levels_by_rank`）。
       ただし最上位段より深く、下に行を持たない（葉の）行で
       数量×単価がそろっていれば細目別に落とす。
       E→a→施工費 のように途中で終わる枝の末端を拾うため
    3. インデントの段が1種類しか無い様式は、数量と単価がそろう行を細目別
    4. どれも無ければ、金額などがある行を細目別、無い行を科目別

    **2 を 3 より先に見るのが要点。** 逆にすると、種目行にも
    「数量1・単価・金額」を入れる様式（金額＝単価の集計行）で
    全行が細目別になり、階層がまるごと潰れる。

    **インデントを使うかは表全体で決める。** 行ごとに判断すると、
    最上位行（インデント0）だけが別の規則で判定され、
    金額を持つ種目行が細目別になってしまう。
    """
    if level_label:
        key = level_label.replace(" ", "").replace("　", "")
        if key in LEVEL_BY_LABEL:
            return LEVEL_BY_LABEL[key]

    if rank_level is not None:
        if (is_priced and is_leaf
                and rank_level != BoqLine.Level.SHUMOKU):
            return BoqLine.Level.SAIMOKU
        return rank_level

    if is_priced:
        return BoqLine.Level.SAIMOKU

    if uses_indent:
        # 見出しの深さ。細目別は上で確定済みなので中科目別までに収める。
        depth = _indent_depth(raw_name)
        return LEVEL_BY_DEPTH[min(depth, LEVEL_BY_DEPTH.index(BoqLine.Level.CHUKAMOKU))]

    # インデントを使っていない様式。金額などがある行は明細、無い行は見出し。
    return BoqLine.Level.SAIMOKU if has_numbers else BoqLine.Level.KAMOKU


def rows_to_drafts(rows: list[list], *, origin: str = "") -> ParseResult:
    """表（行×列）から BoqDraft を作る。Excel と PDF で共通に使う。"""
    result = ParseResult()

    found = _find_header(rows)
    if not found:
        result.warnings.append(
            f"{origin}見出し行（名称・数量・単価・金額）が見つかりませんでした。"
        )
        return result

    header_index, mapping = found

    def cell(row, key):
        col = mapping.get(key)
        if col is None or col >= len(row):
            return None
        return row[col]

    # 明細行をいったん集める。階層の判定に表全体の情報（インデントを
    # 使っている様式かどうか）が要るため、ここでは決めない。
    collected = []
    for offset, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any(_text(c) for c in row):
            continue

        raw_name = row[mapping["name"]] if mapping["name"] < len(row) else ""
        raw_name = "" if raw_name is None else str(raw_name)
        name = _text(raw_name)
        if not name:
            continue
        if _is_subtotal(name):
            # 小計・合計行。取り込むと二重計上になる。
            continue

        collected.append((offset, row, raw_name, name))

    depths = [_indent_depth(raw_name) for _, _, raw_name, _ in collected]
    uses_indent = any(d > 0 for d in depths)

    # 値ではなく順位で段を持つ。幅は様式ごとにばらつくが、順序は変わらない。
    ranks = sorted(set(depths))
    rank_of = {depth: index for index, depth in enumerate(ranks)}

    # 段が1種類しか無い表は「インデントで階層を表している」とは言えない。
    # 順位を使わず、これまでどおり数量×単価の有無で判定させる。
    levels_by_rank = None
    if len(ranks) > 1:
        deepest_is_priced = any(
            _to_decimal(cell(row, "quantity")) is not None
            and _to_decimal(cell(row, "unit_price")) is not None
            for (_, row, _, _), depth in zip(collected, depths, strict=True)
            if depth == ranks[-1]
        )
        levels_by_rank = _levels_by_rank(
            len(ranks), deepest_is_priced=deepest_is_priced,
        )

    for index, ((offset, row, raw_name, name), depth) in enumerate(
        zip(collected, depths, strict=True)
    ):
        quantity = _to_decimal(cell(row, "quantity"))
        unit_price = _to_decimal(cell(row, "unit_price"))
        amount = _to_decimal(cell(row, "amount"))

        # 次の行が自分と同じか浅い段なら、この行に子は無い（枝の末端）。
        is_leaf = index + 1 >= len(depths) or depths[index + 1] <= depth

        unit = _text(cell(row, "unit"))
        if not unit:
            # 単位列を持たない様式では数量セルに単位が同居している。
            unit = _split_unit(cell(row, "quantity"))

        result.drafts.append(BoqDraft(
            level=_resolve_level(
                raw_name,
                _text(cell(row, "level")),
                is_priced=quantity is not None and unit_price is not None,
                has_numbers=any(
                    v is not None for v in (quantity, unit_price, amount)
                ),
                uses_indent=uses_indent,
                rank_level=(
                    levels_by_rank[rank_of[depth]]
                    if levels_by_rank is not None else None
                ),
                is_leaf=is_leaf,
            ),
            name=name,
            spec=_text(cell(row, "spec")),
            unit=unit,
            quantity=quantity,
            unit_price=unit_price,
            amount=amount,
            remarks=_text(cell(row, "remarks")),
            source_row=offset,
        ))

    if not result.drafts:
        result.warnings.append(
            f"{origin}見出し行は見つかりましたが、明細行が1件も読めませんでした。"
        )
    return result


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------


def parse_excel(data: bytes) -> ParseResult:
    """Excel の内訳書を読む。全シートを順に見る。"""
    if not HAS_OPENPYXL:
        return ParseResult(warnings=["openpyxl が利用できません。"])

    result = ParseResult()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception as e:  # noqa: BLE001 - 壊れたファイルは理由を出して返す
        return ParseResult(warnings=[f"Excel を開けませんでした: {e}"])

    try:
        for ws in wb.worksheets:
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            if not rows:
                continue
            sheet = rows_to_drafts(rows, origin=f"[{ws.title}] ")
            result.drafts.extend(sheet.drafts)
            # 明細が取れたシートの警告は出さない。内訳書ファイルには
            # 表紙・鑑・集計だけのシートが普通に混ざっており、
            # そこで毎回警告を出すと本当の失敗が埋もれる。
            if not sheet.drafts:
                continue
    finally:
        wb.close()

    if not result.drafts:
        result.warnings.append(
            "内訳書として読める表がありませんでした。"
            "名称・数量・単価・金額の見出しがある表かご確認ください。"
        )
    return result


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _page_kind(page) -> str | None:
    """ページ見出しから「内訳書」か「内訳明細書」かを見る。読めなければ None。

    同じ PDF に両方が綴じられているのが普通で、内訳書は内訳明細書の集計。
    両方取り込むと同じ工種が二重に入り、合計も二重計上になる。
    """
    head = "\n".join((page.extract_text() or "").splitlines()[:3])
    if any(title in head for title in DETAIL_PAGE_TITLES):
        return "detail"
    if any(title in head for title in SUMMARY_PAGE_TITLES):
        return "summary"
    return None


def _dropped_row_count(table: list[list]) -> int:
    """名称が空で捨てられる行の数。罫線から表が取り切れたかの目安にする。"""
    found = _find_header(table)
    if not found:
        return 0
    header_index, mapping = found
    name_col = mapping["name"]

    dropped = 0
    for row in table[header_index + 1:]:
        if not any(_text(c) for c in row):
            continue
        name = _text(row[name_col]) if name_col < len(row) else ""
        if not name:
            dropped += 1
    return dropped


def _column_bounds(page) -> list[float]:
    """縦罫線の x 座標。列の境界として使う。"""
    bounds: list[float] = []
    for x in sorted({round(edge["x0"], 1) for edge in page.edges
                     if edge["orientation"] == "v"}):
        if not bounds or x - bounds[-1] > 2:
            bounds.append(x)
    return bounds


def _table_span(page) -> tuple[float, float]:
    """縦罫線が通っている範囲。表の上端と下端とみなす。

    ページ番号や「※印は軽減税率対象です」といった脚注は表の外にあり、
    そのまま拾うと名称列の最左になって段の順位を1つずつずらす。
    """
    verticals = [e for e in page.edges if e["orientation"] == "v"]
    if not verticals:
        return (0.0, float(page.height))
    return (
        min(e["top"] for e in verticals),
        max(e["bottom"] for e in verticals),
    )


def _row_tolerance(tops: list[float]) -> float:
    """同じ行とみなす縦方向の許容幅。行送りの半分弱を採る。

    折り返した単位（「0.66㎥(」＋「立方メートル)」）を同じ行に寄せつつ、
    次の行を巻き込まない幅にする。
    """
    gaps = sorted(
        # tops と tops[1:] は隣同士の差を取るための意図的なずれ
        round(b - a, 1)
        for a, b in zip(tops, tops[1:], strict=False)
        if b - a > 1
    )
    if not gaps:
        return 3.0
    # 最頻の行送り。外れ値に引きずられないよう中央値を使う。
    pitch = gaps[len(gaps) // 2]
    return max(3.0, pitch * 0.45)


def _rows_from_words(page) -> list[list[str]]:
    """罫線の列位置と語の座標から表を組み直す。

    縞模様の背景を敷いた PDF では罫線が1行おきにしか引かれず、
    `extract_tables()` は罫線の無い行の7列ぶんを1セルに潰す。
    潰れた行は名称列が空になり、明細として丸ごと捨てられていた。

    列の境界は縦罫線から採る（縦罫線は表全体に通っている）。
    見出しラベルの位置は使わない。「名称」は列の中央に置かれるのに
    中身は左詰めで、境界を取り違えるため。

    名称列の左端位置は段の深さそのものなので、順位ぶんの全角空白を
    先頭に足して返す。以降は Excel と同じインデント判定に乗る。
    """
    bounds = _column_bounds(page)
    if len(bounds) < 3:
        return []

    top, bottom = _table_span(page)
    words = [
        w for w in page.extract_words()
        if top - 2 <= w["top"] and w["bottom"] <= bottom + 2
    ]
    if not words:
        return []

    def column_of(word) -> int | None:
        center = (word["x0"] + word["x1"]) / 2
        for index in range(len(bounds) - 1):
            if bounds[index] <= center < bounds[index + 1]:
                return index
        return None

    words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    tolerance = _row_tolerance(sorted({round(w["top"], 1) for w in words}))

    clusters: list[tuple[float, dict[int, list]]] = []
    for word in words:
        column = column_of(word)
        if column is None:
            continue
        if clusters and word["top"] - clusters[-1][0] <= tolerance:
            clusters[-1][1].setdefault(column, []).append(word)
        else:
            clusters.append((word["top"], {column: [word]}))

    column_count = len(bounds) - 1
    rows = [
        [
            " ".join(w["text"] for w in sorted(cells.get(c, []),
                                               key=lambda w: w["x0"]))
            for c in range(column_count)
        ]
        for _, cells in clusters
    ]

    found = _find_header(rows)
    if not found:
        return []
    header_index, mapping = found
    name_col = mapping["name"]

    # 名称列の左端を段として拾い、順位ぶんの全角空白に置き換える。
    def left_of(cells) -> float | None:
        words_in_name = cells.get(name_col)
        if not words_in_name:
            return None
        return round(min(w["x0"] for w in words_in_name), 1)

    body = clusters[header_index + 1:]
    lefts: list[float] = []
    for _, cells in body:
        left = left_of(cells)
        if left is not None and not any(abs(left - seen) <= 3 for seen in lefts):
            lefts.append(left)
    lefts.sort()

    for offset, (_, cells) in enumerate(body, start=header_index + 1):
        left = left_of(cells)
        if left is None:
            continue
        rank = next(
            (i for i, seen in enumerate(lefts) if abs(left - seen) <= 3), 0
        )
        rows[offset][name_col] = "　" * rank + rows[offset][name_col]

    return rows


def _usable_row_count(rows: list[list]) -> int:
    """名称が読める明細行の数。どの読み方を採るかの比較に使う。"""
    found = _find_header(rows)
    if not found:
        return 0
    header_index, mapping = found
    name_col = mapping["name"]
    return sum(
        1 for row in rows[header_index + 1:]
        if name_col < len(row) and _text(row[name_col])
    )


def _page_rows(page) -> list[list]:
    """1ページぶんの表を行×列で返す。"""
    tables = page.extract_tables() or []
    rows: list[list] = []
    for table in tables:
        rows.extend(table)

    # 罫線から行を取りこぼしていれば、語の座標から組み直す。
    if not tables or any(_dropped_row_count(t) for t in tables):
        rescued = _rows_from_words(page)
        if _usable_row_count(rescued) > _usable_row_count(rows):
            logger.info(
                "p.%s を語の座標から組み直しました: %d行 → %d行",
                page.page_number,
                _usable_row_count(rows), _usable_row_count(rescued),
            )
            return rescued
    return rows


def parse_pdf(data: bytes) -> ParseResult:
    """PDF の内訳書を読む。

    まず pdfplumber の表抽出で決定論的に読む。表として取れなかった
    ページだけ、ADR-0010 層Bのローカル推論に回す。

    **同じ列構成のページは1つの表として繋いでから読む。** 内訳書は
    ページを跨いで続き、階層はページ内では閉じない。ページごとに読むと、
    ページ末尾の行が「下に行が無い＝枝の末端」に見えて階層を取り違える。
    """
    if not HAS_PDFPLUMBER:
        return ParseResult(warnings=["pdfplumber が利用できません。"])

    result = ParseResult()
    unreadable_pages = []
    # 列構成ごとにページを束ねる: [(見出しの対応, 先頭ページ, 行)]
    groups: list[tuple[tuple, int, list[list]]] = []

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            kinds = [_page_kind(page) for page in pdf.pages]
            # 内訳書は内訳明細書の集計。両方あるなら明細書だけを取り込む。
            skip_summary = "detail" in kinds and "summary" in kinds
            # 見出しでページを見分けられる PDF なら、見出しの無いページは
            # 表紙・鑑とみなして黙って飛ばす。Excel の表紙シートと同じ扱い。
            titled = any(kind is not None for kind in kinds)

            for page, kind in zip(pdf.pages, kinds, strict=True):
                if skip_summary and kind == "summary":
                    logger.info(
                        "p.%s は内訳書（集計）なので読み飛ばします", page.page_number,
                    )
                    continue

                rows = _page_rows(page)
                found = _find_header(rows) if rows else None
                if not found or _usable_row_count(rows) == 0:
                    if titled and kind is None:
                        continue
                    if (page.extract_text() or "").strip():
                        unreadable_pages.append(page)
                    continue

                header_index, mapping = found
                key = tuple(sorted(mapping.items()))
                if groups and groups[-1][0] == key:
                    # 続きのページ。繰り返しの見出し行から下だけを足す。
                    groups[-1][2].extend(rows[header_index + 1:])
                else:
                    groups.append((key, page.page_number, list(rows)))
    except Exception as e:  # noqa: BLE001 - 壊れたPDFは理由を出して返す
        return ParseResult(warnings=[f"PDF を開けませんでした: {e}"])

    for _, first_page, rows in groups:
        parsed = rows_to_drafts(rows, origin=f"[p.{first_page}~] ")
        result.drafts.extend(parsed.drafts)
        result.warnings.extend(parsed.warnings)

    for page in unreadable_pages:
        drafts = _structure_page_with_llm(page)
        if drafts:
            result.drafts.extend(drafts)
        else:
            result.warnings.append(
                f"p.{page.page_number} は表として読み取れませんでした。"
            )

    if not result.drafts:
        result.warnings.append(
            "内訳書として読める表がありませんでした。"
            "スキャン画像のPDFは文字が取れないため、Excelでの取込をお試しください。"
        )
    return result


LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "spec": {"type": "string"},
                    "unit": {"type": "string"},
                    "quantity": {"type": "string"},
                    "unit_price": {"type": "string"},
                    "amount": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    "required": ["rows"],
}

LLM_SYSTEM_PROMPT = (
    "あなたは建設工事の内訳書を読む担当者です。"
    "与えられたテキストに書かれていることだけを根拠に答えてください。"
    "書かれていない項目は空文字にしてください。推測してはいけません。"
)

LLM_USER_PROMPT = """\
次のテキストは工事の内訳書の1ページです。明細行を抜き出してください。

- 小計・合計の行は含めないでください
- 数量・単価・金額は数字だけを文字列で入れてください（カンマや円記号は不要）
- 読み取れない項目は空文字にしてください

---
{text}
"""


def _structure_page_with_llm(page) -> list[BoqDraft]:
    """表として抽出できなかったページをローカル推論で構造化する。

    ADR-0010 層B。到達不可なら静かに諦める（API へは上げない。
    内訳書のページ全文は入力が大きく、課金を伴う自動フォールバックは
    取り込み1回のコストが読めなくなるため）。
    """
    from apps.ai.services import local_llm

    if not local_llm.is_configured():
        return []

    text = (page.extract_text() or "")[:6000]
    if not text.strip():
        return []

    payload = local_llm.chat_json(
        LLM_USER_PROMPT.format(text=text),
        LLM_SCHEMA,
        system_prompt=LLM_SYSTEM_PROMPT,
        # 内訳書1ページは長い。既定の 8192 では入力で埋まる。
        num_ctx=16384,
    )
    if payload is None:
        return []

    drafts = []
    for row in payload["parsed"].get("rows", []):
        name = _text(row.get("name"))
        if not name or _is_subtotal(name):
            continue
        quantity = _to_decimal(row.get("quantity"))
        unit_price = _to_decimal(row.get("unit_price"))
        amount = _to_decimal(row.get("amount"))
        drafts.append(BoqDraft(
            level=_resolve_level(
                name, "",
                is_priced=quantity is not None and unit_price is not None,
                has_numbers=any(
                    v is not None for v in (quantity, unit_price, amount)
                ),
                # LLM の出力は原文のインデントを保たないので使わない。
                uses_indent=False,
            ),
            name=name,
            spec=_text(row.get("spec")),
            unit=_text(row.get("unit")),
            quantity=quantity,
            unit_price=unit_price,
            amount=amount,
        ))
    logger.info(
        "p.%s をローカル推論で構造化しました: %d件", page.page_number, len(drafts),
    )
    return drafts


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def parse_upload(filename: str, data: bytes) -> ParseResult:
    """拡張子で読み方を選ぶ。"""
    lowered = (filename or "").lower()
    if lowered.endswith((".xlsx", ".xlsm")):
        return parse_excel(data)
    if lowered.endswith(".pdf"):
        return parse_pdf(data)
    if lowered.endswith(".xls"):
        return ParseResult(warnings=[
            "旧形式の .xls は読めません。.xlsx で保存し直してください。"
        ])
    return ParseResult(warnings=[
        "Excel(.xlsx) または PDF(.pdf) を選んでください。"
    ])


# ---------------------------------------------------------------------------
# 保存
# ---------------------------------------------------------------------------


def rebuild_tree(lines) -> None:
    """並び順と階層から親子関係を組み立て直す。

    表形式で編集したあとに呼ぶ。人に親を選ばせると、行を1つ挿しただけで
    親子が総崩れになるため、並び順を正とする。

    lines は sort_order 順に並んでいること。保存まで行う。
    """
    last_by_depth: dict[int, object] = {}
    changed = []

    for line in lines:
        try:
            depth = LEVEL_BY_DEPTH.index(line.level)
        except ValueError:
            depth = len(LEVEL_BY_DEPTH) - 1

        parent = None
        for upper in range(depth - 1, -1, -1):
            if upper in last_by_depth:
                parent = last_by_depth[upper]
                break

        if line.parent_id != (parent.pk if parent else None):
            line.parent = parent
            changed.append(line)

        last_by_depth[depth] = line
        for deeper in list(last_by_depth):
            if deeper > depth:
                del last_by_depth[deeper]

    for line in changed:
        line.save(update_fields=["parent"])


def load_drafts(drafts: list[BoqDraft], *, company, site=None, project=None,
                user=None, replace: bool = False) -> int:
    """BoqDraft を BoqLine として保存する。階層から親子を組み立てる。

    Args:
        replace: True なら既存の内訳書を削除してから入れ替える。
                 取り込み直しで行が二重になるのを防ぐ。

    Returns:
        作成した行数。
    """
    if (site is None) == (project is None):
        raise ValueError("site か project のどちらか一方を指定してください。")

    owner = {"site": site} if site is not None else {"project": project}

    if replace:
        BoqLine.objects.filter(**owner).delete()

    # 直近に見た行を階層ごとに覚えておき、1つ上の階層を親にする。
    last_by_depth: dict[int, BoqLine] = {}
    created = 0

    for order, draft in enumerate(drafts, start=1):
        depth = LEVEL_BY_DEPTH.index(draft.level)
        parent = None
        for upper in range(depth - 1, -1, -1):
            if upper in last_by_depth:
                parent = last_by_depth[upper]
                break

        line = BoqLine(
            company=company,
            parent=parent,
            level=draft.level,
            sort_order=order,
            name=draft.name,
            spec=draft.spec,
            unit=draft.unit,
            quantity=draft.quantity,
            unit_price=draft.unit_price,
            amount=draft.amount,
            remarks=draft.remarks,
            **owner,
        )
        if line.amount is None:
            line.calc_amount()
        if user is not None and hasattr(line, "created_by"):
            line.created_by = user
        line.save()

        last_by_depth[depth] = line
        # 自分より深い階層の記憶は捨てる。次の兄弟の子が
        # 前の兄弟の子にぶら下がるのを防ぐ。
        for deeper in list(last_by_depth):
            if deeper > depth:
                del last_by_depth[deeper]
        created += 1

    return created
