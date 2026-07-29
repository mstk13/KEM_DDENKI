"""PostgreSQL スキーマと CRUD。

紙の「作業日報」フォームに準拠した構造:
  labor.reports                … 1現場×1日で1枚（ヘッダー・自社交通手段・現場代理人）
  labor.report_workers         … 自社作業員の明細（複数行）
  labor.report_subcontractors  … 協力会社の明細（複数行）
  master.employees / master.sites  … 入力補助用マスタ（共通）

作業時間（work_hours）は開始・終了から自動計算する。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from dbconn import get_conn  # noqa: E402

import config


# --------------------------------------------------------------------------
# ヘルパー
# --------------------------------------------------------------------------
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _dicts(rows) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def calc_span_hours(start: str | None, end: str | None) -> float:
    if not start or not end:
        return 0.0
    try:
        sh, sm = (int(x) for x in start.split(":"))
        eh, em = (int(x) for x in end.split(":"))
    except (ValueError, AttributeError):
        return 0.0
    total = (eh * 60 + em) - (sh * 60 + sm)
    return round(total / 60, 2) if total > 0 else 0.0


def init_db() -> None:
    """スキーマは shared/schema.sql で管理。"""
    pass


# --------------------------------------------------------------------------
# 作業員マスタ CRUD (master.employees)
# --------------------------------------------------------------------------
def add_worker(name: str, role: str = "", phone: str = "", kana: str = "") -> int:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                """INSERT INTO master.employees (name, kana, role, phone, is_active, created_at)
                   VALUES (%s, %s, %s, %s, TRUE, %s)
                   ON CONFLICT (name) DO UPDATE SET
                       kana = COALESCE(NULLIF(EXCLUDED.kana, ''), master.employees.kana),
                       role = COALESCE(NULLIF(EXCLUDED.role, ''), master.employees.role),
                       phone = COALESCE(NULLIF(EXCLUDED.phone, ''), master.employees.phone)
                   RETURNING id""",
                (name, kana, role, phone, _now()),
            )
            return cur.fetchone()["id"]


def _normalize_kana(s: str | None) -> str:
    if not s:
        return ""
    out = []
    for ch in s:
        o = ord(ch)
        if 0x30A1 <= o <= 0x30F6:
            out.append(chr(o - 0x60))
        elif ch in " 　・.,、。･":
            continue
        else:
            out.append(ch)
    return "".join(out)


def match_worker_name(spoken: str) -> tuple[str, bool]:
    from difflib import SequenceMatcher
    ns = _normalize_kana(spoken)
    if not ns:
        return spoken, False
    best_score, best_name = 0.0, None
    for w in list_workers(active_only=True):
        for target in (w.get("kana"), w.get("name")):
            nt = _normalize_kana(target)
            if not nt:
                continue
            r = SequenceMatcher(None, ns, nt).ratio()
            if ns in nt or nt in ns:
                r = max(r, 0.9)
            if r > best_score:
                best_score, best_name = r, w["name"]
    if best_name and best_score >= 0.55:
        return best_name, True
    return spoken.strip(), False


def _is_all_kana(s: str) -> bool:
    ns = _normalize_kana(s)
    return bool(ns) and all(0x3041 <= ord(ch) <= 0x309F for ch in ns)


def register_new_workers(names: list[str]) -> list[str]:
    existing = {_normalize_kana(w["name"]) for w in list_workers()}
    added: list[str] = []
    for name in names:
        nm = (name or "").strip()
        key = _normalize_kana(nm)
        if not nm or not key or key in existing:
            continue
        add_worker(nm, kana=(nm if _is_all_kana(nm) else ""))
        existing.add(key)
        added.append(nm)
    return added


def update_worker(worker_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = %s" for k in fields)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE master.employees SET {cols} WHERE id = %s",
                        (*fields.values(), worker_id))


def list_workers(active_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM master.employees"
    if active_only:
        sql += " WHERE is_active = TRUE"
    sql += " ORDER BY is_active DESC, name"
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(sql)
            return _dicts(cur.fetchall())


def list_workers_by_kana(active_only: bool = True, role: str | None = None) -> list[dict[str, Any]]:
    """社員一覧を50音順（kana）で返す。role でフィルタ可。"""
    where: list[str] = []
    params: list[Any] = []
    if active_only:
        where.append("is_active = TRUE")
    if role:
        where.append("role = %s")
        params.append(role)
    sql = "SELECT * FROM master.employees"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY COALESCE(NULLIF(kana, ''), name), name"
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(sql, params)
            return _dicts(cur.fetchall())


# --------------------------------------------------------------------------
# 現場マスタ CRUD (master.sites)
# --------------------------------------------------------------------------
def add_site(
    name: str,
    client: str = "",
    address: str = "",
    category: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    status: str = "着工前",
    memo: str = "",
) -> int:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                """INSERT INTO master.sites (name, client, address, category, start_date,
                   end_date, status, memo, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (name, client, address, category, start_date, end_date, status, memo, _now()),
            )
            return cur.fetchone()["id"]


def update_site(site_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = %s" for k in fields)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE master.sites SET {cols} WHERE id = %s",
                        (*fields.values(), site_id))


def get_site(site_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM master.sites WHERE id = %s", (site_id,))
            r = cur.fetchone()
            return dict(r) if r else None


def list_sites(active_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM master.sites"
    if active_only:
        sql += " WHERE status IN ('着工前', '施工中')"
    sql += " ORDER BY (CASE WHEN status IN ('着工前','施工中') THEN 0 ELSE 1 END), name"
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(sql)
            return _dicts(cur.fetchall())


def get_or_create_site(name: str, client: str = "") -> tuple[int, bool]:
    nm = (name or "").strip()
    if not nm:
        raise ValueError("現場名が空です")
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT id FROM master.sites WHERE TRIM(name) = %s", (nm,)
            )
            row = cur.fetchone()
            if row:
                return row["id"], False
    return add_site(nm, client=(client or "").strip()), True


# --------------------------------------------------------------------------
# 発注先マスタ CRUD (master.clients)
# --------------------------------------------------------------------------
def add_client(name: str, contact: str = "", phone: str = "", memo: str = "") -> int:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "INSERT INTO master.clients (name, contact, phone, memo, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (name, contact, phone, memo, _now()),
            )
            return cur.fetchone()["id"]


def update_client(client_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = %s" for k in fields)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE master.clients SET {cols} WHERE id = %s",
                        (*fields.values(), client_id))


def list_clients(active_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM master.clients"
    if active_only:
        sql += " WHERE is_active = TRUE"
    sql += " ORDER BY is_active DESC, name"
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(sql)
            return _dicts(cur.fetchall())


def get_or_create_client(name: str) -> tuple[int, bool]:
    nm = (name or "").strip()
    if not nm:
        raise ValueError("発注先名が空です")
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT id FROM master.clients WHERE TRIM(name) = %s", (nm,)
            )
            row = cur.fetchone()
            if row:
                return row["id"], False
    return add_client(nm), True


def import_clients_from_sites() -> list[str]:
    added: list[str] = []
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT name FROM master.clients")
            existing = {(r["name"] or "").strip().lower() for r in cur.fetchall()}
            cur.execute(
                "SELECT DISTINCT client FROM master.sites WHERE client IS NOT NULL AND TRIM(client) <> ''"
            )
            for r in cur.fetchall():
                nm = (r["client"] or "").strip()
                if not nm or nm.lower() in existing:
                    continue
                add_client(nm)
                existing.add(nm.lower())
                added.append(nm)
    return added


# --------------------------------------------------------------------------
# 日報 CRUD (labor.reports / labor.report_workers / labor.report_subcontractors)
# --------------------------------------------------------------------------
def _insert_workers(conn, report_id: int, workers: list[dict[str, Any]]) -> None:
    for i, w in enumerate(workers or []):
        name = (w.get("worker_name") or "").strip()
        if not name:
            continue
        start, end = w.get("start_time"), w.get("end_time")
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO labor.report_workers (report_id, worker_name, start_time, end_time,
                   overtime_h, lodging, work_hours, sort_order) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    report_id, name, start, end,
                    float(w.get("overtime_h", 0) or 0),
                    bool(w.get("lodging")),
                    calc_span_hours(start, end),
                    i,
                ),
            )


def _insert_subs(conn, report_id: int, subs: list[dict[str, Any]]) -> None:
    for i, s in enumerate(subs or []):
        company = (s.get("company_name") or "").strip()
        if not company:
            continue
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO labor.report_subcontractors (report_id, company_name, worker_name,
                   headcount, start_time, end_time, work_content, transport_car, transport_share,
                   transport_train, car_count, transport_cost, approved, sort_order)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    report_id, company, (s.get("worker_name") or "").strip(),
                    int(s.get("headcount", 0) or 0), s.get("start_time"), s.get("end_time"),
                    (s.get("work_content") or "").strip(),
                    bool(s.get("transport_car")),
                    bool(s.get("transport_share")),
                    bool(s.get("transport_train")),
                    int(s.get("car_count", 0) or 0),
                    int(s.get("transport_cost", 0) or 0),
                    bool(s.get("approved")),
                    i,
                ),
            )


def add_report(
    report_date: str,
    site_id: int,
    reporter_name: str = "",
    client: str = "",
    work_content: str = "",
    own_car: bool = False,
    own_train: bool = False,
    own_car_count: int = 0,
    own_transport_cost: int = 0,
    manager: str = "",
    status: str = "提出済",
    workers: list[dict[str, Any]] | None = None,
    subcontractors: list[dict[str, Any]] | None = None,
) -> int:
    now = _now()
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                """INSERT INTO labor.reports (report_date, reporter_name, site_id, client, work_content, own_car,
                   own_train, own_car_count, own_transport_cost, manager, status, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (
                    report_date, reporter_name, site_id, client, work_content,
                    bool(own_car), bool(own_train),
                    int(own_car_count or 0), int(own_transport_cost or 0),
                    manager, status, now, now,
                ),
            )
            report_id = cur.fetchone()["id"]
        _insert_workers(conn, report_id, workers or [])
        _insert_subs(conn, report_id, subcontractors or [])
    return report_id


def update_report(
    report_id: int,
    workers: list[dict[str, Any]] | None = None,
    subcontractors: list[dict[str, Any]] | None = None,
    **fields: Any,
) -> None:
    fields["updated_at"] = _now()
    for k in ("own_car", "own_train"):
        if k in fields:
            fields[k] = bool(fields[k])
    cols = ", ".join(f"{k} = %s" for k in fields)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE labor.reports SET {cols} WHERE id = %s",
                        (*fields.values(), report_id))
            if workers is not None:
                cur.execute("DELETE FROM labor.report_workers WHERE report_id = %s", (report_id,))
                _insert_workers(conn, report_id, workers)
            if subcontractors is not None:
                cur.execute("DELETE FROM labor.report_subcontractors WHERE report_id = %s", (report_id,))
                _insert_subs(conn, report_id, subcontractors)


def delete_report(report_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM labor.reports WHERE id = %s", (report_id,))


def get_report(report_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT r.*, s.name AS site_name FROM labor.reports r "
                "JOIN master.sites s ON s.id = r.site_id WHERE r.id = %s",
                (report_id,),
            )
            r = cur.fetchone()
            return dict(r) if r else None


def get_report_workers(report_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT * FROM labor.report_workers WHERE report_id = %s ORDER BY sort_order, id",
                (report_id,),
            )
            return _dicts(cur.fetchall())


def get_report_subcontractors(report_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT * FROM labor.report_subcontractors WHERE report_id = %s ORDER BY sort_order, id",
                (report_id,),
            )
            return _dicts(cur.fetchall())


def list_reports(
    date_from: str | None = None,
    date_to: str | None = None,
    site_id: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
    sql = [
        """
        SELECT r.*, s.name AS site_name,
          (SELECT COUNT(*) FROM labor.report_workers rw WHERE rw.report_id = r.id) AS worker_count,
          (SELECT COALESCE(SUM(rw.work_hours),0) FROM labor.report_workers rw WHERE rw.report_id = r.id) AS total_hours,
          (SELECT COALESCE(SUM(rw.overtime_h),0) FROM labor.report_workers rw WHERE rw.report_id = r.id) AS total_overtime,
          (SELECT COALESCE(SUM(rs.headcount),0) FROM labor.report_subcontractors rs WHERE rs.report_id = r.id) AS sub_headcount,
          (r.own_transport_cost +
           (SELECT COALESCE(SUM(rs.transport_cost),0) FROM labor.report_subcontractors rs WHERE rs.report_id = r.id)) AS total_transport_cost
        FROM labor.reports r
        JOIN master.sites s ON s.id = r.site_id
        WHERE 1 = 1
        """
    ]
    params: list[Any] = []
    if date_from:
        sql.append("AND r.report_date >= %s"); params.append(date_from)
    if date_to:
        sql.append("AND r.report_date <= %s"); params.append(date_to)
    if site_id:
        sql.append("AND r.site_id = %s"); params.append(site_id)
    if status:
        sql.append("AND r.status = %s"); params.append(status)
    if keyword:
        sql.append(
            "AND (r.work_content LIKE %s OR r.manager LIKE %s OR "
            "EXISTS (SELECT 1 FROM labor.report_workers rw WHERE rw.report_id = r.id AND rw.worker_name LIKE %s))"
        )
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
    sql.append("ORDER BY r.report_date DESC, r.id DESC")
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("\n".join(sql), params)
            return _dicts(cur.fetchall())


def list_worker_lines(date_from: str | None = None, date_to: str | None = None) -> list[dict[str, Any]]:
    sql = [
        """
        SELECT rw.*, r.report_date, s.name AS site_name
        FROM labor.report_workers rw
        JOIN labor.reports r ON r.id = rw.report_id
        JOIN master.sites s ON s.id = r.site_id
        WHERE 1 = 1
        """
    ]
    params: list[Any] = []
    if date_from:
        sql.append("AND r.report_date >= %s"); params.append(date_from)
    if date_to:
        sql.append("AND r.report_date <= %s"); params.append(date_to)
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("\n".join(sql), params)
            return _dicts(cur.fetchall())


# --------------------------------------------------------------------------
# 事務員 日報 CRUD (labor.office_reports)
# --------------------------------------------------------------------------
def add_office_report(
    report_date: str,
    worker_name: str,
    start_time: str | None = None,
    end_time: str | None = None,
    work_content: str = "",
    report_content: str = "",
    next_content: str = "",
    role: str = "事務員",
    status: str = "提出済",
) -> int:
    now = _now()
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                """INSERT INTO labor.office_reports (report_date, worker_name, start_time, end_time,
                   work_hours, work_content, report_content, next_content, role, status, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (
                    report_date, worker_name, start_time, end_time,
                    calc_span_hours(start_time, end_time),
                    work_content, report_content, next_content, role, status, now, now,
                ),
            )
            return cur.fetchone()["id"]


def update_office_report(report_id: int, **fields: Any) -> None:
    if not fields:
        return
    if "start_time" in fields or "end_time" in fields:
        fields["work_hours"] = calc_span_hours(fields.get("start_time"), fields.get("end_time"))
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = %s" for k in fields)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE labor.office_reports SET {cols} WHERE id = %s",
                        (*fields.values(), report_id))


def delete_office_report(report_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM labor.office_reports WHERE id = %s", (report_id,))


def get_office_report(report_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM labor.office_reports WHERE id = %s", (report_id,))
            r = cur.fetchone()
            return dict(r) if r else None


def list_office_reports(
    date_from: str | None = None,
    date_to: str | None = None,
    worker_name: str | None = None,
    role: str | None = None,
) -> list[dict[str, Any]]:
    sql = ["SELECT * FROM labor.office_reports WHERE 1 = 1"]
    params: list[Any] = []
    if date_from:
        sql.append("AND report_date >= %s"); params.append(date_from)
    if date_to:
        sql.append("AND report_date <= %s"); params.append(date_to)
    if worker_name:
        sql.append("AND worker_name = %s"); params.append(worker_name)
    if role:
        sql.append("AND role = %s"); params.append(role)
    sql.append("ORDER BY report_date DESC, id DESC")
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("\n".join(sql), params)
            return _dicts(cur.fetchall())


def list_reports_for_worker(
    worker_name: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """指定社員の現場日報（report_workers に名前がある行）を返す。"""
    sql = [
        """
        SELECT r.*, s.name AS site_name,
          rw.start_time AS w_start, rw.end_time AS w_end, rw.work_hours AS w_hours
        FROM labor.report_workers rw
        JOIN labor.reports r ON r.id = rw.report_id
        JOIN master.sites s ON s.id = r.site_id
        WHERE rw.worker_name = %s
        """
    ]
    params: list[Any] = [worker_name]
    if date_from:
        sql.append("AND r.report_date >= %s"); params.append(date_from)
    if date_to:
        sql.append("AND r.report_date <= %s"); params.append(date_to)
    sql.append("ORDER BY r.report_date DESC, r.id DESC")
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("\n".join(sql), params)
            return _dicts(cur.fetchall())


def list_reports_for_site(
    site_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """指定現場の日報一覧（作業員数・作業時間・協力人数を含む）を返す。"""
    sql = [
        """
        SELECT r.*, s.name AS site_name,
          (SELECT COUNT(*) FROM labor.report_workers rw WHERE rw.report_id = r.id) AS worker_count,
          (SELECT COALESCE(SUM(rw.work_hours),0) FROM labor.report_workers rw WHERE rw.report_id = r.id) AS total_hours,
          (SELECT COALESCE(SUM(rs.headcount),0) FROM labor.report_subcontractors rs WHERE rs.report_id = r.id) AS sub_headcount
        FROM labor.reports r
        JOIN master.sites s ON s.id = r.site_id
        WHERE r.site_id = %s
        """
    ]
    params: list[Any] = [site_id]
    if date_from:
        sql.append("AND r.report_date >= %s"); params.append(date_from)
    if date_to:
        sql.append("AND r.report_date <= %s"); params.append(date_to)
    sql.append("ORDER BY r.report_date DESC, r.id DESC")
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("\n".join(sql), params)
            return _dicts(cur.fetchall())


if __name__ == "__main__":
    init_db()
    print(f"DB を初期化しました (PostgreSQL)")
