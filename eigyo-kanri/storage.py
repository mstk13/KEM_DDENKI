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

from config import FILES_DIR, SUPPORTED_EXTS

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


def _split_base(stem):
    """末尾の連番 '_N' を分離して (ベース名, '_N' または '') を返す。"""
    m = re.search(r"_(\d+)$", stem)
    if m:
        return stem[:m.start()], stem[m.start():]
    return stem, ""


def group_files(source_file):
    """同じ記録に属する資料ファイル一覧を返す（代表を先頭に）。

    複数アップロード時は同じベース名＋'_2','_3'... で保存されるため、
    同フォルダ内でベース名が一致する対応拡張子ファイルをまとめる。
    """
    if not source_file:
        return []
    p = Path(source_file)
    if not p.exists():
        return []
    folder = p.parent
    base, _ = _split_base(p.stem)
    out = []
    for f in sorted(folder.iterdir()):
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS and _split_base(f.stem)[0] == base:
            out.append(f)
    if p in out:
        out = [p] + [f for f in out if f != p]
    return out


def refile(record) -> str:
    """業界・会社・営業日・担当者・要件が変わったら、記録に属する資料群を移動・改名。

    代表ファイルの新パスを返す。ファイルが無ければ元の値を返す。
    """
    src = record.get("source_file")
    if not src:
        return src
    p = Path(src)
    if not p.exists():
        return src
    target_dir = material_dir(record.get("industry"), record.get("company_name"))
    new_base = build_filename(record, "")  # ベース名（拡張子なし）
    new_primary = src
    for f in group_files(src):
        _, idx = _split_base(f.stem)
        dest = target_dir / f"{new_base}{idx}{f.suffix.lower()}"
        if dest.resolve() == f.resolve():
            newp = f
        else:
            target_dir.mkdir(parents=True, exist_ok=True)
            dest = _unique(dest, ignore=f)
            shutil.move(str(f), str(dest))
            newp = dest
        if f.resolve() == p.resolve():
            new_primary = str(newp)
    return new_primary
