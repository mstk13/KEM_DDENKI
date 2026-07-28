"""別アプリ(KEM_DDENKI / 作業日報)からの日報取り込み。

別アプリは独立した SQLite(`data/sagyo_nippou.db`)を持つため、そのままではデータが共有されない。
このモジュールが *読み取り専用* で別アプリの DB を参照し、本アプリの形式に変換して取り込む。

取り込み対象:
    reports + report_workers  … 現場の作業日報
    office_reports            … 事務日報(存在する場合)

同じ日報を何度取り込んでも重複しないよう、`reports.source_key` に
`sagyo:報告ID` の形式で元 ID を記録し、2回目以降は更新扱いにする。

CLI:
    py -3 importer.py                      … 全期間を取り込み
    py -3 importer.py 2026-07-01 2026-07-31  … 期間を指定して取り込み
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import config
import database as db

# 別アプリの DB の既定パス(data/sagyo_nippou.db)
_data_dir = os.getenv("KEM_DATA_DIR", str(config.BASE_DIR.parent / "data"))
DEFAULT_SOURCE_DB = Path(os.getenv(
    "NIPPOU_SOURCE_DB", os.path.join(_data_dir, "sagyo_nippou.db")))

SOURCE_PREFIX = "sagyo"
OFFICE_SITE_NAME = "(事務所)"

# 別アプリのステータス → 本アプリのステータス
STATUS_MAP = {
    "下書き": "未確認",
    "提出済": "確認済",
    "承認済": "承認済",
    "差戻し": "差戻し",
}


def _connect(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"別アプリの DB が見つかりません: {p}")
    # 読み取り専用で開く(別アプリの動作に影響を与えない)
    conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def peek(path: str | Path = DEFAULT_SOURCE_DB) -> dict:
    """取り込み前の概要(件数・期間)を返す。"""
    conn = _connect(path)
    try:
        tabs = _tables(conn)
        info: dict = {"path": str(path), "tables": sorted(tabs)}
        if "reports" in tabs:
            row = conn.execute(
                "SELECT COUNT(*) c, MIN(report_date) mn, MAX(report_date) mx FROM reports"
            ).fetchone()
            info["reports"] = row["c"]
            info["date_from"] = row["mn"] or ""
            info["date_to"] = row["mx"] or ""
        if "report_workers" in tabs:
            info["workers_rows"] = conn.execute(
                "SELECT COUNT(*) FROM report_workers").fetchone()[0]
        if "office_reports" in tabs:
            info["office_reports"] = conn.execute(
                "SELECT COUNT(*) FROM office_reports").fetchone()[0]
        if "workers" in tabs:
            info["workers"] = [dict(r) for r in conn.execute(
                "SELECT name, kana, role, is_active FROM workers ORDER BY id")]
        return info
    finally:
        conn.close()


def fetch(path: str | Path = DEFAULT_SOURCE_DB, date_from: str = "", date_to: str = "",
          include_office: bool = True) -> list[dict]:
    """別アプリの日報を、本アプリの形式(ヘッダ + 明細)に変換して返す。"""
    conn = _connect(path)
    try:
        tabs = _tables(conn)
        blocks: list[dict] = []

        if "reports" in tabs and "report_workers" in tabs:
            sql = ["SELECT r.id, r.report_date, r.work_content, r.status, r.manager,",
                   "  COALESCE(s.name, '') AS site_name",
                   "FROM reports r LEFT JOIN sites s ON s.id = r.site_id WHERE 1=1"]
            params: list = []
            if date_from:
                sql.append("AND r.report_date >= ?"); params.append(date_from)
            if date_to:
                sql.append("AND r.report_date <= ?"); params.append(date_to)
            sql.append("ORDER BY r.report_date, r.id")
            for rep in conn.execute(" ".join(sql), params).fetchall():
                crew = conn.execute(
                    "SELECT worker_name, start_time, end_time FROM report_workers "
                    "WHERE report_id = ? ORDER BY sort_order, id", (rep["id"],)
                ).fetchall()
                if not crew:
                    continue
                blocks.append({
                    "source_key": f"{SOURCE_PREFIX}:report:{rep['id']}",
                    "date": rep["report_date"],
                    "site": rep["site_name"] or "(現場未設定)",
                    "content": rep["work_content"] or "",
                    "note": f"現場代理人/責任者: {rep['manager']}" if rep["manager"] else "",
                    "status": STATUS_MAP.get(rep["status"], "未確認"),
                    "entries": [{
                        "name": (w["worker_name"] or "").strip(),
                        "start": w["start_time"] or "",
                        "end": w["end_time"] or "",
                    } for w in crew if (w["worker_name"] or "").strip()],
                })

        if include_office and "office_reports" in tabs:
            sql = ["SELECT id, report_date, worker_name, start_time, end_time,",
                   "  work_content, report_content, status FROM office_reports WHERE 1=1"]
            params = []
            if date_from:
                sql.append("AND report_date >= ?"); params.append(date_from)
            if date_to:
                sql.append("AND report_date <= ?"); params.append(date_to)
            sql.append("ORDER BY report_date, id")
            for rep in conn.execute(" ".join(sql), params).fetchall():
                name = (rep["worker_name"] or "").strip()
                if not name:
                    continue
                blocks.append({
                    "source_key": f"{SOURCE_PREFIX}:office:{rep['id']}",
                    "date": rep["report_date"],
                    "site": OFFICE_SITE_NAME,
                    "content": rep["work_content"] or rep["report_content"] or "",
                    "note": "事務日報",
                    "status": STATUS_MAP.get(rep["status"], "未確認"),
                    "entries": [{"name": name, "start": rep["start_time"] or "",
                                 "end": rep["end_time"] or ""}],
                })
        return blocks
    finally:
        conn.close()


def import_workers(path: str | Path = DEFAULT_SOURCE_DB) -> int:
    """別アプリの作業員マスタを、本アプリの社員マスタへ取り込む。"""
    conn = _connect(path)
    try:
        if "workers" not in _tables(conn):
            return 0
        rows = conn.execute(
            "SELECT name, kana, role, is_active FROM workers ORDER BY id").fetchall()
    finally:
        conn.close()
    added = 0
    for w in rows:
        name = (w["name"] or "").strip()
        if not name:
            continue
        if db.get_employee_by_name(name):
            continue
        db.add_employee(name=name, kana=w["kana"] or "", position=w["role"] or "",
                        active=int(w["is_active"] or 1), note="作業日報 から取込")
        added += 1
    return added


def sync(path: str | Path = DEFAULT_SOURCE_DB, date_from: str = "", date_to: str = "",
         break_minutes: int | None = None, include_office: bool = True,
         with_workers: bool = True, settings: dict | None = None) -> dict:
    """別アプリの日報を取り込む(再実行しても重複しない)。

    別アプリは休憩時間を保持していないため、`break_minutes`(既定は設定値)を
    一律で控除して 早朝/通常/残業 を計算する。
    """
    settings = settings or db.get_settings()
    if break_minutes is None:
        break_minutes = int(settings.get("break_minutes") or 0)

    result = {"created": 0, "updated": 0, "entries": 0, "workers_added": 0, "errors": []}
    if with_workers:
        try:
            result["workers_added"] = import_workers(path)
        except Exception as exc:  # マスタ取込の失敗で日報取込を止めない
            result["errors"].append(f"作業員マスタの取込に失敗: {exc}")

    for block in fetch(path, date_from, date_to, include_office):
        items = []
        for e in block["entries"]:
            emp = db.get_employee_by_name(e["name"])
            emp_id = int(emp["id"]) if emp else (
                db.add_employee(name=e["name"], note="作業日報 から自動登録")
                if settings.get("auto_register_employee") else None)
            items.append({
                "employee_id": emp_id,
                "employee_name": e["name"],
                "start_time": e["start"],
                "end_time": e["end"],
                "break_minutes": break_minutes,
            })
        if not items:
            continue
        existing = db.find_report_by_source(block["source_key"])
        if existing:
            db.update_report(existing, report_date=block["date"], site_name=block["site"],
                             work_content=block["content"], note=block["note"],
                             status=block["status"], entries=items, settings=settings)
            result["updated"] += 1
        else:
            db.add_report(report_date=block["date"], site_name=block["site"],
                          work_content=block["content"], note=block["note"],
                          status=block["status"], entries=items, settings=settings,
                          source_key=block["source_key"])
            result["created"] += 1
        result["entries"] += len(items)

    db.link_entries_to_employees()
    return result


def imported_count() -> int:
    """取込済みの日報件数。"""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM attend.reports WHERE source_key LIKE %s",
                (f"{SOURCE_PREFIX}:%",),
            )
            return cur.fetchone()[0]


def delete_imported() -> int:
    """取込分だけを削除する(手入力・自動抽出したデータは残す)。"""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM attend.reports WHERE source_key LIKE %s",
                (f"{SOURCE_PREFIX}:%",),
            )
            ids = [r[0] for r in cur.fetchall()]
    for rid in ids:
        db.delete_report(rid)
    return len(ids)


if __name__ == "__main__":
    db.init_db()
    d_from = sys.argv[1] if len(sys.argv) > 1 else ""
    d_to = sys.argv[2] if len(sys.argv) > 2 else ""
    print("取込元:", DEFAULT_SOURCE_DB)
    print("概要:", peek())
    res = sync(date_from=d_from, date_to=d_to)
    print(f"新規 {res['created']} 件 / 更新 {res['updated']} 件 / "
          f"明細 {res['entries']} 行 / 社員追加 {res['workers_added']} 名")
    for e in res["errors"]:
        print("警告:", e)
