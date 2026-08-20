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

    # カンマ・通貨記号・単位を落とす。負号と小数点は残す。
    cleaned = re.sub(r"[,¥￥円\s]", "", text)
    cleaned = re.sub(r"[^0-9.\-]", "", cleaned)
    if cleaned in ("", "-", ".", "-."):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _is_subtotal(name: str) -> bool:
    compact = name.replace(" ", "").replace("　", "")
    return compact in SUBTOTAL_WORDS


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


def _resolve_level(raw_name: str, level_label: str, *,
                   is_priced: bool, has_numbers: bool, uses_indent: bool) -> str:
    """階層を決める。

    優先順:

    1. 「階層」列があればそれに従う
    2. **数量と単価がそろっている行は細目別（内訳明細書）。**
       内訳明細書とは「数量×単価で金額を積む階層」のことなので、
       インデントの深さではなくこの有無で決めるのが実態に合う。
       実ファイルのインデントは 2段だったり4段だったりばらつくため、
       段数だけで見ると最下層が細目別にならない
    3. インデントを使っている様式なら段数（ただし上位3階層まで。
       細目別は 2 で決まるので、ここでは見出しの深さだけを決める）
    4. どれも無ければ、金額などがある行を細目別、無い行を科目別

    **インデントを使うかは表全体で決める。** 行ごとに判断すると、
    最上位行（インデント0）だけが別の規則で判定され、
    金額を持つ種目行が細目別になってしまう。
    """
    if level_label:
        key = level_label.replace(" ", "").replace("　", "")
        if key in LEVEL_BY_LABEL:
            return LEVEL_BY_LABEL[key]

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

    uses_indent = any(_indent_depth(raw_name) > 0 for _, _, raw_name, _ in collected)

    for offset, row, raw_name, name in collected:
        quantity = _to_decimal(cell(row, "quantity"))
        unit_price = _to_decimal(cell(row, "unit_price"))
        amount = _to_decimal(cell(row, "amount"))

        result.drafts.append(BoqDraft(
            level=_resolve_level(
                raw_name,
                _text(cell(row, "level")),
                is_priced=quantity is not None and unit_price is not None,
                has_numbers=any(
                    v is not None for v in (quantity, unit_price, amount)
                ),
                uses_indent=uses_indent,
            ),
            name=name,
            spec=_text(cell(row, "spec")),
            unit=_text(cell(row, "unit")),
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


def parse_pdf(data: bytes) -> ParseResult:
    """PDF の内訳書を読む。

    まず pdfplumber の表抽出で決定論的に読む。表として取れなかった
    ページだけ、ADR-0010 層Bのローカル推論に回す。
    """
    if not HAS_PDFPLUMBER:
        return ParseResult(warnings=["pdfplumber が利用できません。"])

    result = ParseResult()
    unreadable_pages = []

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables() or []
                page_drafts = []
                for table in tables:
                    parsed = rows_to_drafts(table, origin=f"[p.{page.page_number}] ")
                    page_drafts.extend(parsed.drafts)

                if page_drafts:
                    result.drafts.extend(page_drafts)
                elif (page.extract_text() or "").strip():
                    unreadable_pages.append(page)
    except Exception as e:  # noqa: BLE001 - 壊れたPDFは理由を出して返す
        return ParseResult(warnings=[f"PDF を開けませんでした: {e}"])

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
