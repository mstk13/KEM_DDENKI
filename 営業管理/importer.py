"""フォルダ監視による取込（CLI / 定期実行向け）。

INBOX_DIR に置かれた PDF/画像を1件ずつ:
  1. Claude API で会社名・担当者名・営業内容などを自動抽出
  2. 「下書き」ステータスで DB に登録
  3. 元ファイルを FILES_DIR/<業界>/<会社名>/<自動命名> に退避
"""
from datetime import date, datetime
from pathlib import Path

from config import INBOX_DIR, SUPPORTED_EXTS
import database
import extractor
import storage


def scan_inbox():
    """INBOX_DIR の取込対象ファイル一覧を返す。"""
    if not INBOX_DIR.exists():
        return []
    return sorted(
        p for p in INBOX_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    )


def import_file(path) -> int:
    """1ファイルを取込して visit_id を返す。抽出失敗時は例外を送出。"""
    path = Path(path)
    received = date.fromtimestamp(path.stat().st_mtime).isoformat()
    data = extractor.extract(path)

    visit_id = database.add_visit(
        industry=data.get("industry", ""),
        company_name=data.get("company_name", ""),
        rep_name=data.get("rep_name", ""),
        business_overview=data.get("business_overview", ""),
        sales_content=data.get("sales_content", ""),
        phone=data.get("phone", ""),
        email=data.get("email", ""),
        website=data.get("website", ""),
        address=data.get("address", ""),
        visit_date=data.get("visit_date"),
        received_date=received,
    )

    # 元ファイルをアプリ構造（業界/会社）のフォルダへ、自動命名で移動して保管
    record = {
        "industry": data.get("industry"),
        "company_name": data.get("company_name"),
        "visit_date": data.get("visit_date"),
        "received_date": received,
        "rep_name": data.get("rep_name"),
        "sales_content": data.get("sales_content"),
    }
    dest = storage.store_move(path, record)
    database.update_visit(visit_id, source_file=dest)
    return visit_id


def import_inbox():
    """INBOX_DIR を一括取込。結果サマリを返す。"""
    files = scan_inbox()
    results = {"saved": 0, "errors": []}
    for f in files:
        try:
            import_file(f)
            results["saved"] += 1
        except Exception as e:  # noqa: BLE001 - 1ファイルの失敗で全体を止めない
            results["errors"].append((f.name, str(e)))
    return results


if __name__ == "__main__":
    database.init_db()
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] INBOX 取込開始: {INBOX_DIR}")
    res = import_inbox()
    print(f"取込 {res['saved']} 件")
    for name, err in res["errors"]:
        print(f"  失敗: {name} -> {err}")
