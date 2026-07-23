"""資料ファイルの保存先・ファイル名管理。

保存先はアプリの構造（業界 → 会社）に合わせた階層:
    FILES_DIR/<業界>/<会社名>/<ファイル名>

ファイル名は自動編集する:
    <営業日YYYYMMDD>_<営業担当者名>_<営業要件>.<拡張子>
    例: 20260723_山田太郎_LED照明の新製品提案.pdf

Windows で使えない文字はフォルダ名では '_' に、ファイル名では除去する。
"""
import re
import shutil
from datetime import date
from pathlib import Path

from config import FILES_DIR

_ILLEGAL = re.compile(r'[\\/:*?"<>|]')

# 営業要件（ファイル名に入れる営業内容の要約）の最大文字数
_REQUIREMENT_MAXLEN = 40


def _safe_dir(name, fallback):
    """フォルダ名として安全に（禁止文字は '_'）。"""
    name = _ILLEGAL.sub("_", (name or "").strip()).rstrip(". ")
    return name or fallback


def _safe_part(name, fallback, maxlen=None):
    """ファイル名の一部として安全に（禁止文字・改行・連続空白を除去）。"""
    name = _ILLEGAL.sub("", (name or ""))
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    if maxlen:
        name = name[:maxlen].strip()
    return name or fallback


def _date_compact(value):
    """'YYYY-MM-DD' 等から 'YYYYMMDD' を作る。取れなければ None。"""
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits[:8] if len(digits) >= 8 else None


def material_dir(industry, company) -> Path:
    """業界・会社に対応する保存フォルダ。"""
    return FILES_DIR / _safe_dir(industry, "未分類業界") / _safe_dir(company, "会社名なし")


def build_filename(record, ext) -> str:
    """記録から `営業日_担当者_営業要件.拡張子` のファイル名を組み立てる。"""
    d = (
        _date_compact(record.get("visit_date"))
        or _date_compact(record.get("received_date"))
        or date.today().strftime("%Y%m%d")
    )
    rep = _safe_part(record.get("rep_name"), "担当者不明")
    req = _safe_part(record.get("sales_content"), "要件不明", maxlen=_REQUIREMENT_MAXLEN)
    return f"{d}_{rep}_{req}{ext.lower()}"


def _unique(path: Path, ignore: Path = None) -> Path:
    """同名ファイルがあれば _2, _3 ... を付けて衝突を避ける（ignore は自分自身）。"""
    def _same(a, b):
        return b is not None and a.exists() and b.exists() and a.resolve() == b.resolve()

    if not path.exists() or _same(path, ignore):
        return path
    stem, suf = path.stem, path.suffix
    i = 2
    while True:
        cand = path.with_name(f"{stem}_{i}{suf}")
        if not cand.exists() or _same(cand, ignore):
            return cand
        i += 1


def store_bytes(filename, data: bytes, record) -> str:
    """バイト列（アップロード）を構造化フォルダに自動命名で保存。"""
    ext = Path(filename).suffix.lower()
    d = material_dir(record.get("industry"), record.get("company_name"))
    d.mkdir(parents=True, exist_ok=True)
    dest = _unique(d / build_filename(record, ext))
    dest.write_bytes(data)
    return str(dest)


def store_move(src_path, record) -> str:
    """既存ファイル（inbox 等）を構造化フォルダへ自動命名で移動。"""
    src_path = Path(src_path)
    ext = src_path.suffix.lower()
    d = material_dir(record.get("industry"), record.get("company_name"))
    d.mkdir(parents=True, exist_ok=True)
    dest = _unique(d / build_filename(record, ext))
    shutil.move(str(src_path), str(dest))
    return str(dest)


def refile(record) -> str:
    """業界・会社・営業日・担当者・要件が変わったら、正しいフォルダ名・ファイル名へ移動。

    移動不要ならそのままのパスを返す。ファイルが無ければ元の値を返す。
    """
    src = record.get("source_file")
    if not src:
        return src
    p = Path(src)
    if not p.exists():
        return src
    target = material_dir(record.get("industry"), record.get("company_name")) / build_filename(
        record, p.suffix.lower()
    )
    if target.resolve() == p.resolve():
        return src
    target = _unique(target, ignore=p)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(target))
    return str(target)
