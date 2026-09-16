"""PDF・Excel のファイルを受け取るときの共通の決まり（ADR-0067・ADR-0071）。

現場の提出書類（apps/sites/documents.py）と自社書類（apps/tenants/company_documents.py）で
同じ規則を使う。拡張子だけでなく中身の先頭の形も見て、別の形式のファイルを弾く。
"""

import zipfile
from pathlib import Path

# 1件の大きさと、一度に登録できる件数。
# 完成図書や決算書などスキャンした PDF は大きくなるので広めにとる
MAX_DOCUMENT_FILE_MB = 50
MAX_DOCUMENT_FILES_PER_UPLOAD = 10

# 拡張子ごとの種類と、開くときの Content-Type
PDF_KIND = "pdf"
EXCEL_KIND = "excel"
FILE_TYPES = {
    ".pdf": (PDF_KIND, "application/pdf"),
    ".xlsx": (
        EXCEL_KIND,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    ".xls": (EXCEL_KIND, "application/vnd.ms-excel"),
}
# ファイルを選ぶ画面で、PDF と Excel だけを出す
ACCEPT_ATTR = ",".join([*FILE_TYPES, *(content_type for _, content_type in FILE_TYPES.values())])

# .xls（と、パスワード付きの .xlsx）の入れ物の先頭
_OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")


class UnsupportedDocumentFile(ValueError):
    """PDF・Excel ではないファイル。"""


def _read_head(uploaded, size: int) -> bytes:
    uploaded.seek(0)
    try:
        return uploaded.read(size)
    finally:
        uploaded.seek(0)


def _is_xlsx_zip(uploaded) -> bool:
    uploaded.seek(0)
    try:
        with zipfile.ZipFile(uploaded) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return False
    finally:
        uploaded.seek(0)
    return "[Content_Types].xml" in names and any(name.startswith("xl/") for name in names)


def detect_file_kind(uploaded) -> str:
    """PDF か Excel かを返す。どちらでもなければ UnsupportedDocumentFile。

    拡張子だけ変えたファイル（写真や Word を .pdf にしたもの）を通さないよう、中身の先頭も見る。
    """
    suffix = Path(uploaded.name or "").suffix.lower()
    if suffix not in FILE_TYPES:
        raise UnsupportedDocumentFile(
            "PDF（.pdf）か Excel（.xlsx・.xls）のファイルを選んでください"
        )
    head = _read_head(uploaded, 1024)
    if suffix == ".pdf":
        # PDF の印は先頭 1024 バイトのどこかにあればよい（規格上、前に余計なものが付くことがある）
        matches = b"%PDF-" in head
    elif suffix == ".xls":
        matches = head.startswith(_OLE_MAGIC)
    else:
        # パスワード付きの .xlsx は ZIP ではなく、.xls と同じ入れ物になる
        matches = head.startswith(_OLE_MAGIC) or _is_xlsx_zip(uploaded)
    if not matches:
        raise UnsupportedDocumentFile(
            "中身が PDF・Excel ではありません（拡張子だけ変えたファイルは登録できません）"
        )
    return FILE_TYPES[suffix][0]


def content_type_for(name: str) -> str:
    entry = FILE_TYPES.get(Path(name).suffix.lower())
    return entry[1] if entry else "application/octet-stream"
