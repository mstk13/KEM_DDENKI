"""電材品目名の正規化モジュール。

Django 非依存の純粋関数群。テスト容易性と再利用性を確保するため、
DB アクセスやフレームワーク依存を一切持たない。

正規化ルールは後から必ず追加・修正が入る。
ルール変更時に全 normalized_name を再生成できるよう、
このモジュールを唯一の正規化ロジックの源泉とする。
"""

import re
import unicodedata

# ---------------------------------------------------------------------------
# 1. 文字種の正規化
# ---------------------------------------------------------------------------


def normalize_width(text: str) -> str:
    """全角英数記号→半角、半角カタカナ→全角カタカナ。"""
    return unicodedata.normalize("NFKC", text)


def normalize_whitespace(text: str) -> str:
    """連続空白→単一スペース、前後 trim。"""
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# 2. 電材固有の正規化
# ---------------------------------------------------------------------------

# --- スケア（断面積）表記の統一 ---
_SQ_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:㎟|mm²|mm2|ＭＭ２|sq|SQ|ＳＱ|スケア|スケ)",
    re.IGNORECASE,
)

# --- 芯数（心数）表記の統一 ---
_CORE_PATTERN = re.compile(
    r"(\d+)\s*(?:心|芯|C|c|core|コア|ｃ)",
)
# "×3" や "x3" のパターン（芯数が後置の場合）
_CORE_SUFFIX_PATTERN = re.compile(
    r"[×xX＊\*]\s*(\d+)\s*(?:心|芯|C|c|core|コア)?",
)

# --- 径表記の統一 ---
_DIAMETER_PATTERN = re.compile(
    r"(?:φ|Φ|ファイ|パイ|径)\s*(\d+(?:\.\d+)?)",
)

# --- 乗算記号の統一 ---
_MULTIPLY_PATTERN = re.compile(r"[×＊\*]")


def normalize_sq(text: str) -> str:
    """スケア表記を統一: 38sq, 38㎟, 38mm2 → 38sq"""
    return _SQ_PATTERN.sub(r"\1sq", text)


def normalize_cores(text: str) -> str:
    """芯数表記を統一: 3心, 3芯, 3C → 3C"""
    text = _CORE_PATTERN.sub(r"\1C", text)
    return text


def normalize_diameter(text: str) -> str:
    """径表記を統一: φ25, Φ25, 径25 → D25"""
    return _DIAMETER_PATTERN.sub(r"D\1", text)


def normalize_multiply(text: str) -> str:
    """乗算記号を統一: ×, ＊, * → x"""
    return _MULTIPLY_PATTERN.sub("x", text)


# --- 中黒・ハイフンの正規化 ---
_PUNCTUATION_PATTERN = re.compile(r"[・\-−–—‐‑]")


def normalize_punctuation(text: str) -> str:
    """中黒・ハイフン類をスペースに統一。"""
    return _PUNCTUATION_PATTERN.sub(" ", text)


# --- ケーブル種別の正規化 ---
_CABLE_ALIASES = {
    "CVT": "CVT",
    "ＣＶＴ": "CVT",
    "CV": "CV",
    "ＣＶ": "CV",
    "VVF": "VVF",
    "ＶＶＦ": "VVF",
    "VVR": "VVR",
    "ＶＶＲ": "VVR",
    "IV": "IV",
    "ＩＶ": "IV",
    "EM-CE": "EM-CE",
    "EM-CET": "EM-CET",
    "EM-IE": "EM-IE",
    "EM CE": "EM-CE",
    "EM CET": "EM-CET",
    "EM IE": "EM-IE",
}


def normalize_cable_type(text: str) -> str:
    """ケーブル種別の正規化。全角→半角は normalize_width で済んでいる前提。"""
    for alias, canonical in _CABLE_ALIASES.items():
        # 単語境界で置換（部分一致を避ける）
        pattern = re.compile(re.escape(alias), re.IGNORECASE)
        text = pattern.sub(canonical, text)
    return text


# --- 電線管の正規化 ---
_CONDUIT_ALIASES = {
    "薄鋼電線管": "C管",
    "Ｃ管": "C管",
    "厚鋼電線管": "G管",
    "Ｇ管": "G管",
    "ねじなし電線管": "E管",
    "Ｅ管": "E管",
    "PF管": "PF管",
    "ＰＦ管": "PF管",
    "CD管": "CD管",
    "ＣＤ管": "CD管",
    "硬質ビニル電線管": "VE管",
    "ＶＥ管": "VE管",
}


def normalize_conduit_type(text: str) -> str:
    """電線管種別の正規化。"""
    for alias, canonical in _CONDUIT_ALIASES.items():
        text = text.replace(alias, canonical)
    return text


# --- 電圧表記の正規化 ---
_VOLTAGE_PATTERN = re.compile(
    r"(\d+)\s*(?:V|v|ボルト|Ｖ)",
)


def normalize_voltage(text: str) -> str:
    """電圧表記を統一: 600V, 600v, 600ボルト → 600V"""
    return _VOLTAGE_PATTERN.sub(r"\1V", text)


# ---------------------------------------------------------------------------
# 3. メインパイプライン
# ---------------------------------------------------------------------------


def normalize(text: str) -> str:
    """全正規化パイプラインを適用して返す。

    呼び出し順序は重要。幅の正規化を最初に行い、
    その後に電材固有の正規化を適用する。
    """
    if not text:
        return ""

    text = normalize_width(text)
    text = normalize_punctuation(text)
    text = normalize_voltage(text)
    text = normalize_cable_type(text)
    text = normalize_conduit_type(text)
    text = normalize_sq(text)
    text = normalize_cores(text)
    text = normalize_diameter(text)
    text = normalize_multiply(text)
    text = normalize_whitespace(text)
    text = text.lower()
    return text


# ---------------------------------------------------------------------------
# 4. 仕様抽出
# ---------------------------------------------------------------------------

# ケーブル仕様の抽出パターン
_SPEC_VOLTAGE = re.compile(r"(\d+)V", re.IGNORECASE)
_SPEC_TYPE = re.compile(
    r"\b(CVT|CV|VVF|VVR|IV|EM-CE|EM-CET|EM-IE)\b", re.IGNORECASE,
)
_SPEC_SIZE = re.compile(r"(\d+(?:\.\d+)?)sq", re.IGNORECASE)
_SPEC_CORES = re.compile(r"(\d+)C", re.IGNORECASE)
_SPEC_DIAMETER = re.compile(r"D(\d+(?:\.\d+)?)", re.IGNORECASE)


def extract_spec(text: str) -> dict:
    """品目名称から仕様 JSON を抽出する。

    normalize() を適用済みのテキストを入力として想定。

    >>> extract_spec("600v cv 3c 38sq")
    {'voltage': '600V', 'type': 'CV', 'cores': 3, 'size': '38sq'}
    """
    spec = {}

    m = _SPEC_VOLTAGE.search(text)
    if m:
        spec["voltage"] = f"{m.group(1)}V"

    m = _SPEC_TYPE.search(text)
    if m:
        spec["type"] = m.group(1).upper()

    m = _SPEC_SIZE.search(text)
    if m:
        spec["size"] = f"{m.group(1)}sq"

    m = _SPEC_CORES.search(text)
    if m:
        spec["cores"] = int(m.group(1))

    m = _SPEC_DIAMETER.search(text)
    if m:
        spec["diameter"] = f"D{m.group(1)}"

    return spec
