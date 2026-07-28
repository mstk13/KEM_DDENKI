"""工期管理 — DB アクセス層。

master.sites   … 現場マスタ（工期の start_date / end_date / status を含む）
schedule.phases     … 工程フェーズ（1現場に複数）
schedule.milestones … マイルストーン（検査日・引き渡し等）
labor.reports       … 作業日報（実績日数の参照用）
"""
from __future__ import annotations

import sys
from datetime import datetime, date
from pathlib import Path
from typing import Any

import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from dbconn import get_conn  # noqa: E402


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _dicts(rows) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def init_db() -> None:
    """スキーマは shared/schema.sql で管理。"""
    pass


# ---------------------------------------------------------------------------
# 現場一覧（master.sites）
# ---------------------------------------------------------------------------
def list_sites(active_only: bool = False, keyword: str = "") -> list[dict]:
    sql = "SELECT * FROM master.sites WHERE 1=1"
    params: list[Any] = []
    if active_only:
        sql += " AND status IN ('着工前', '施工中')"
    if keyword:
        sql += " AND (name LIKE %s OR client LIKE %s OR category LIKE %s)"
        params += [f"%{keyword}%"] * 3
    sql += " ORDER BY (CASE WHEN status IN ('着工前','施工中') THEN 0 ELSE 1 END), start_date ASC NULLS LAST, name"
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(sql, params)
            return _dicts(cur.fetchall())


def add_site(name: str, client: str = "", category: str = "",
             start_date=None, end_date=None, status: str = "着工前",
             address: str = "", manager: str = "", memo: str = "") -> int:
    """工期管理から現場を新規登録する。"""
    now = _now()
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                """INSERT INTO master.sites
                   (name, client, category, start_date, end_date, status,
                    address, manager, memo, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (name, client, category, start_date, end_date, status,
                 address, manager, memo, now, now),
            )
            return cur.fetchone()["id"]


def get_site(site_id: int) -> dict | None:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM master.sites WHERE id = %s", (site_id,))
            r = cur.fetchone()
            return dict(r) if r else None


def update_site(site_id: int, **fields) -> None:
    allowed = {"name", "client", "address", "region", "category", "start_date",
               "end_date", "status", "manager", "memo"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    sets["updated_at"] = _now()
    clause = ", ".join(f"{k} = %s" for k in sets)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE master.sites SET {clause} WHERE id = %s",
                        (*sets.values(), site_id))


# ---------------------------------------------------------------------------
# 工程フェーズ（schedule.phases）
# ---------------------------------------------------------------------------
def add_phase(site_id: int, name: str, start_date=None, end_date=None,
              progress: int = 0, sort_order: int = 0, color: str = "", memo: str = "") -> int:
    now = _now()
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                """INSERT INTO schedule.phases
                   (site_id, name, start_date, end_date, progress, sort_order, color, memo, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (site_id, name, start_date, end_date, progress, sort_order, color, memo, now, now),
            )
            return cur.fetchone()["id"]


def update_phase(phase_id: int, **fields) -> None:
    allowed = {"name", "start_date", "end_date", "progress", "sort_order", "color", "memo"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    sets["updated_at"] = _now()
    clause = ", ".join(f"{k} = %s" for k in sets)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE schedule.phases SET {clause} WHERE id = %s",
                        (*sets.values(), phase_id))


def delete_phase(phase_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM schedule.phases WHERE id = %s", (phase_id,))


def list_phases(site_id: int) -> list[dict]:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT * FROM schedule.phases WHERE site_id = %s ORDER BY sort_order, start_date, id",
                (site_id,),
            )
            return _dicts(cur.fetchall())


# ---------------------------------------------------------------------------
# マイルストーン（schedule.milestones）
# ---------------------------------------------------------------------------
def add_milestone(site_id: int, name: str, target_date: str, memo: str = "") -> int:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                """INSERT INTO schedule.milestones (site_id, name, target_date, memo, created_at)
                   VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                (site_id, name, target_date, memo, _now()),
            )
            return cur.fetchone()["id"]


def update_milestone(ms_id: int, **fields) -> None:
    allowed = {"name", "target_date", "completed", "memo"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    clause = ", ".join(f"{k} = %s" for k in sets)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE schedule.milestones SET {clause} WHERE id = %s",
                        (*sets.values(), ms_id))


def delete_milestone(ms_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM schedule.milestones WHERE id = %s", (ms_id,))


def list_milestones(site_id: int) -> list[dict]:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT * FROM schedule.milestones WHERE site_id = %s ORDER BY target_date, id",
                (site_id,),
            )
            return _dicts(cur.fetchall())


# ---------------------------------------------------------------------------
# 作業実績（labor.reports から集計）
# ---------------------------------------------------------------------------
def get_site_work_summary(site_id: int) -> dict:
    """現場の作業日報実績を集計。"""
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("""
                SELECT
                    COUNT(DISTINCT r.report_date) AS work_days,
                    MIN(r.report_date) AS first_work_date,
                    MAX(r.report_date) AS last_work_date,
                    COALESCE(SUM(rw.work_hours), 0) AS total_hours,
                    COUNT(DISTINCT rw.worker_name) AS unique_workers
                FROM labor.reports r
                LEFT JOIN labor.report_workers rw ON rw.report_id = r.id
                WHERE r.site_id = %s
            """, (site_id,))
            row = cur.fetchone()
            return dict(row) if row else {
                "work_days": 0, "first_work_date": None,
                "last_work_date": None, "total_hours": 0, "unique_workers": 0,
            }


def get_daily_worker_counts(site_id: int) -> list[dict]:
    """日別の作業員数。ガントチャートへのオーバーレイ用。"""
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("""
                SELECT r.report_date, COUNT(rw.id) AS worker_count
                FROM labor.reports r
                JOIN labor.report_workers rw ON rw.report_id = r.id
                WHERE r.site_id = %s
                GROUP BY r.report_date
                ORDER BY r.report_date
            """, (site_id,))
            return _dicts(cur.fetchall())


# ---------------------------------------------------------------------------
# 日報データ（labor.reports — 日付ごとの詳細）
# ---------------------------------------------------------------------------
def list_site_reports(site_id: int) -> list[dict]:
    """現場に紐づく日報を日付順に取得（作業員数・時間の集計付き）。"""
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("""
                SELECT
                    r.id,
                    r.report_date,
                    r.work_content,
                    r.status,
                    r.manager,
                    COUNT(rw.id) AS worker_count,
                    COALESCE(SUM(rw.work_hours), 0) AS total_hours,
                    COALESCE(SUM(rw.overtime_h), 0) AS overtime_hours,
                    COALESCE(STRING_AGG(DISTINCT rw.worker_name, '、'), '') AS worker_names,
                    (SELECT COALESCE(SUM(rs.headcount), 0)
                     FROM labor.report_subcontractors rs WHERE rs.report_id = r.id) AS sub_headcount
                FROM labor.reports r
                LEFT JOIN labor.report_workers rw ON rw.report_id = r.id
                WHERE r.site_id = %s
                GROUP BY r.id, r.report_date, r.work_content, r.status, r.manager
                ORDER BY r.report_date DESC, r.id DESC
            """, (site_id,))
            return _dicts(cur.fetchall())


def get_daily_hours(site_id: int) -> list[dict]:
    """日別の合計作業時間。タイムライン可視化用。"""
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("""
                SELECT r.report_date,
                       COUNT(DISTINCT rw.worker_name) AS workers,
                       COALESCE(SUM(rw.work_hours), 0) AS hours
                FROM labor.reports r
                JOIN labor.report_workers rw ON rw.report_id = r.id
                WHERE r.site_id = %s
                GROUP BY r.report_date
                ORDER BY r.report_date
            """, (site_id,))
            return _dicts(cur.fetchall())


# ---------------------------------------------------------------------------
# 材料費データ（material.orders + material.order_cost）
# ---------------------------------------------------------------------------
def get_site_material_summary(site_id: int) -> dict:
    """現場に紐づく材料発注の合計を取得。"""
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("""
                SELECT
                    COUNT(o.id) AS order_count,
                    COALESCE(SUM(o.amount), 0) AS total_amount,
                    COALESCE((SELECT SUM(oc.amount) FROM material.order_cost oc
                              JOIN material.orders o2 ON o2.id = oc.order_id
                              WHERE o2.project_id = %s), 0) AS overhead,
                    MIN(o.order_date) AS first_order,
                    MAX(o.order_date) AS last_order
                FROM material.orders o
                WHERE o.project_id = %s
            """, (site_id, site_id))
            row = cur.fetchone()
            return dict(row) if row else {
                "order_count": 0, "total_amount": 0, "overhead": 0,
                "first_order": None, "last_order": None,
            }


def list_site_orders(site_id: int) -> list[dict]:
    """現場に紐づく発注一覧（品目名・仕入先名付き）。"""
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("""
                SELECT
                    o.id,
                    o.order_date,
                    im.name AS item_name,
                    im.spec,
                    im.unit,
                    o.quantity,
                    o.unit_price,
                    o.amount,
                    o.status,
                    COALESCE(s.name, '') AS supplier_name,
                    o.orderer,
                    o.memo,
                    COALESCE((SELECT SUM(oc.amount) FROM material.order_cost oc
                              WHERE oc.order_id = o.id), 0) AS overhead
                FROM material.orders o
                JOIN material.item_master im ON im.id = o.item_id
                LEFT JOIN master.suppliers s ON s.id = o.supplier_id
                WHERE o.project_id = %s
                ORDER BY o.order_date DESC, o.id DESC
            """, (site_id,))
            return _dicts(cur.fetchall())


def get_daily_material_cost(site_id: int) -> list[dict]:
    """日別の材料発注金額。タイムライン可視化用。"""
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("""
                SELECT o.order_date, SUM(o.amount) AS daily_amount, COUNT(o.id) AS order_count
                FROM material.orders o
                WHERE o.project_id = %s
                GROUP BY o.order_date
                ORDER BY o.order_date
            """, (site_id,))
            return _dicts(cur.fetchall())


# ---------------------------------------------------------------------------
# 見積もりデータ（material.estimate_header / estimate_line）
# ---------------------------------------------------------------------------
def get_site_estimate_summary(site_id: int) -> dict | None:
    """現場の最新見積もりの合計を取得。"""
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT * FROM material.estimate_header WHERE project_id = %s ORDER BY version DESC LIMIT 1",
                (site_id,),
            )
            header = cur.fetchone()
            if not header:
                return None
            return dict(header)


if __name__ == "__main__":
    init_db()
    print("工期管理 DB 初期化完了 (PostgreSQL)")
