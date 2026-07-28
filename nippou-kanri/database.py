"""PostgreSQL データ層。

テーブル構成:
    master.employees … 社員マスタ（共通）
    attend.reports   … 日報ヘッダ(日付・現場・作業内容・原文)
    attend.entries   … 社員別の勤怠明細(1行 = 社員 × 1日報)
    attend.settings  … 規定時間などの運用設定(key-value)
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from db import get_conn  # noqa: E402

import config


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def init_db() -> None:
    """スキーマは shared/schema.sql で管理。"""
    pass


# ---------------------------------------------------------------------------
# 設定(規定時間など)
# ---------------------------------------------------------------------------
def get_settings() -> dict:
    values = dict(config.DEFAULT_SETTINGS)
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT key, value FROM attend.settings")
            rows = cur.fetchall()
    for row in rows:
        key, raw = row["key"], row["value"]
        if key not in values:
            continue
        default = config.DEFAULT_SETTINGS[key]
        try:
            if isinstance(default, bool):
                values[key] = raw in ("1", "True", "true")
            elif isinstance(default, int) and not isinstance(default, bool):
                values[key] = int(float(raw))
            elif isinstance(default, float):
                values[key] = float(raw)
            else:
                values[key] = raw
        except (TypeError, ValueError):
            values[key] = default
    return values


def save_settings(values: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            for k, v in values.items():
                if k in config.DEFAULT_SETTINGS:
                    cur.execute(
                        """INSERT INTO attend.settings(key, value) VALUES (%s, %s)
                           ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value""",
                        (k, str(v)),
                    )


# ---------------------------------------------------------------------------
# 社員マスタ (master.employees)
# ---------------------------------------------------------------------------
def list_employees(active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM master.employees"
    if active_only:
        sql += " WHERE is_active = TRUE"
    sql += " ORDER BY is_active DESC, code, name"
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]


def get_employee_by_name(name: str) -> dict | None:
    if not name:
        return None
    key = str(name).replace(" ", "").replace("\u3000", "")
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM master.employees")
            rows = cur.fetchall()
    for row in rows:
        if row["name"].replace(" ", "").replace("\u3000", "") == key:
            return dict(row)
        if row["kana"] and row["kana"].replace(" ", "").replace("\u3000", "") == key:
            return dict(row)
    return None


def add_employee(name: str, code: str = "", kana: str = "", department: str = "",
                 position: str = "", active: int = 1, note: str = "") -> int:
    existing = get_employee_by_name(name)
    if existing:
        return int(existing["id"])
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                """INSERT INTO master.employees(code, name, kana, department, position, is_active, note, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (code, name.strip(), kana, department, position, bool(active), note, _now()),
            )
            return cur.fetchone()["id"]


def update_employee(emp_id: int, **fields) -> None:
    allowed = {"code", "name", "kana", "department", "position", "is_active", "note"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    # 互換性: 旧コードが "active" を渡す場合
    if "active" in fields and "is_active" not in sets:
        sets["is_active"] = bool(fields["active"])
    if not sets:
        return
    clause = ", ".join(f"{k} = %s" for k in sets)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE master.employees SET {clause} WHERE id = %s",
                        (*sets.values(), int(emp_id)))


def delete_employee(emp_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM master.employees WHERE id = %s", (int(emp_id),))


# ---------------------------------------------------------------------------
# 日報 / 勤怠明細 (attend.reports / attend.entries)
# ---------------------------------------------------------------------------
def _calc(entry: dict, settings: dict) -> dict:
    return config.calc_attendance(
        entry.get("start_time"), entry.get("end_time"),
        entry.get("break_minutes"), settings,
    )


def add_report(report_date: str, site_name: str = "", work_content: str = "",
               note: str = "", status: str = "未確認", source_text: str = "",
               entries: list[dict] | None = None, settings: dict | None = None,
               source_key: str = "") -> int:
    settings = settings or get_settings()
    now = _now()
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                """INSERT INTO attend.reports(report_date, site_name, work_content, note, status,
                   source_text, source_key, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id""",
                (report_date, site_name, work_content, note, status, source_text,
                 source_key, now, now),
            )
            report_id = cur.fetchone()["id"]
    _replace_entries(report_id, entries or [], settings)
    return report_id


def find_report_by_source(source_key: str) -> int | None:
    if not source_key:
        return None
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT id FROM attend.reports WHERE source_key = %s ORDER BY id LIMIT 1",
                (source_key,),
            )
            row = cur.fetchone()
    return int(row["id"]) if row else None


def update_report(report_id: int, entries: list[dict] | None = None,
                  settings: dict | None = None, **fields) -> None:
    allowed = {"report_date", "site_name", "work_content", "note", "status", "source_key"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    with get_conn() as conn:
        if sets:
            clause = ", ".join(f"{k} = %s" for k in sets)
            with conn.cursor() as cur:
                cur.execute(f"UPDATE attend.reports SET {clause}, updated_at = %s WHERE id = %s",
                            (*sets.values(), _now(), int(report_id)))
    if entries is not None:
        _replace_entries(report_id, entries, settings or get_settings())


def _replace_entries(report_id: int, entries: list[dict], settings: dict) -> None:
    rows = []
    for e in entries:
        calc = _calc(e, settings)
        emp_id = e.get("employee_id")
        emp_name = (e.get("employee_name") or "").strip()
        rows.append((
            int(report_id), emp_id, emp_name,
            e.get("start_time") or "", e.get("end_time") or "",
            int(calc["break"]),
            calc["early"], calc["normal"], calc["overtime"], calc["total"],
            e.get("note") or "",
        ))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM attend.entries WHERE report_id = %s", (int(report_id),))
            if rows:
                for row in rows:
                    cur.execute(
                        """INSERT INTO attend.entries(report_id, employee_id, employee_name, start_time,
                           end_time, break_minutes, early_minutes, normal_minutes, overtime_minutes,
                           total_minutes, note) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        row,
                    )


def delete_report(report_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM attend.entries WHERE report_id = %s", (int(report_id),))
            cur.execute("DELETE FROM attend.reports WHERE id = %s", (int(report_id),))


def get_report(report_id: int) -> dict | None:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM attend.reports WHERE id = %s", (int(report_id),))
            r = cur.fetchone()
            return dict(r) if r else None


def get_report_entries(report_id: int) -> list[dict]:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT * FROM attend.entries WHERE report_id = %s ORDER BY id",
                (int(report_id),),
            )
            return [dict(r) for r in cur.fetchall()]


def find_report_id(report_date: str, site_name: str) -> int | None:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT id FROM attend.reports WHERE report_date = %s AND site_name = %s "
                "ORDER BY id LIMIT 1",
                (report_date, site_name),
            )
            row = cur.fetchone()
    return int(row["id"]) if row else None


def list_reports(date_from: str = "", date_to: str = "", sites: list[str] | None = None,
                 statuses: list[str] | None = None, keyword: str = "") -> list[dict]:
    sql = [
        "SELECT r.*, COUNT(e.id) AS worker_count,",
        "  COALESCE(SUM(e.early_minutes),0)    AS early_minutes,",
        "  COALESCE(SUM(e.normal_minutes),0)   AS normal_minutes,",
        "  COALESCE(SUM(e.overtime_minutes),0) AS overtime_minutes,",
        "  COALESCE(SUM(e.total_minutes),0)    AS total_minutes,",
        "  COALESCE(STRING_AGG(e.employee_name, '、'), '') AS worker_names",
        "FROM attend.reports r LEFT JOIN attend.entries e ON e.report_id = r.id WHERE 1=1",
    ]
    params: list = []
    if date_from:
        sql.append("AND r.report_date >= %s"); params.append(date_from)
    if date_to:
        sql.append("AND r.report_date <= %s"); params.append(date_to)
    if sites:
        sql.append(f"AND r.site_name IN ({','.join('%s' for _ in sites)})"); params += list(sites)
    if statuses:
        sql.append(f"AND r.status IN ({','.join('%s' for _ in statuses)})"); params += list(statuses)
    if keyword:
        sql.append("AND (r.site_name LIKE %s OR r.work_content LIKE %s OR r.note LIKE %s "
                   "OR r.id IN (SELECT report_id FROM attend.entries WHERE employee_name LIKE %s))")
        params += [f"%{keyword}%"] * 4
    sql.append("GROUP BY r.id ORDER BY r.report_date DESC, r.id DESC")
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(" ".join(sql), params)
            return [dict(r) for r in cur.fetchall()]


def list_entries(date_from: str = "", date_to: str = "", employee_ids: list[int] | None = None,
                 employee_names: list[str] | None = None, sites: list[str] | None = None,
                 statuses: list[str] | None = None, keyword: str = "") -> list[dict]:
    sql = [
        "SELECT e.*, r.report_date, r.site_name, r.work_content, r.status, r.note AS report_note,",
        "  emp.code AS employee_code, emp.department, emp.position",
        "FROM attend.entries e JOIN attend.reports r ON r.id = e.report_id",
        "LEFT JOIN master.employees emp ON emp.id = e.employee_id WHERE 1=1",
    ]
    params: list = []
    if date_from:
        sql.append("AND r.report_date >= %s"); params.append(date_from)
    if date_to:
        sql.append("AND r.report_date <= %s"); params.append(date_to)
    if employee_ids:
        sql.append(f"AND e.employee_id IN ({','.join('%s' for _ in employee_ids)})")
        params += [int(i) for i in employee_ids]
    if employee_names:
        sql.append(f"AND e.employee_name IN ({','.join('%s' for _ in employee_names)})")
        params += list(employee_names)
    if sites:
        sql.append(f"AND r.site_name IN ({','.join('%s' for _ in sites)})"); params += list(sites)
    if statuses:
        sql.append(f"AND r.status IN ({','.join('%s' for _ in statuses)})"); params += list(statuses)
    if keyword:
        sql.append("AND (r.site_name LIKE %s OR r.work_content LIKE %s OR e.employee_name LIKE %s)")
        params += [f"%{keyword}%"] * 3
    sql.append("ORDER BY r.report_date DESC, e.employee_name, e.id")
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(" ".join(sql), params)
            return [dict(r) for r in cur.fetchall()]


def list_sites() -> list[str]:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT DISTINCT site_name FROM attend.reports WHERE site_name <> '' ORDER BY site_name"
            )
            return [r["site_name"] for r in cur.fetchall()]


def link_entries_to_employees() -> int:
    linked = 0
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT id, name, kana FROM master.employees")
            emps = cur.fetchall()
            lookup = {}
            for e in emps:
                lookup[e["name"].replace(" ", "").replace("\u3000", "")] = e["id"]
                if e["kana"]:
                    lookup.setdefault(e["kana"].replace(" ", "").replace("\u3000", ""), e["id"])
            cur.execute(
                "SELECT id, employee_name FROM attend.entries WHERE employee_id IS NULL"
            )
            rows = cur.fetchall()
        with conn.cursor() as cur2:
            for row in rows:
                emp_id = lookup.get((row["employee_name"] or "").replace(" ", "").replace("\u3000", ""))
                if emp_id:
                    cur2.execute("UPDATE attend.entries SET employee_id = %s WHERE id = %s",
                                (emp_id, row["id"]))
                    linked += 1
    return linked


def recalculate_all(settings: dict | None = None) -> int:
    settings = settings or get_settings()
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT id, start_time, end_time, break_minutes FROM attend.entries"
            )
            rows = cur.fetchall()
        updates = []
        for row in rows:
            calc = config.calc_attendance(
                row["start_time"], row["end_time"], row["break_minutes"], settings
            )
            updates.append((calc["early"], calc["normal"], calc["overtime"],
                            calc["total"], calc["break"], row["id"]))
        if updates:
            with conn.cursor() as cur2:
                for u in updates:
                    cur2.execute(
                        "UPDATE attend.entries SET early_minutes=%s, normal_minutes=%s, "
                        "overtime_minutes=%s, total_minutes=%s, break_minutes=%s WHERE id=%s",
                        u,
                    )
    return len(rows) if rows else 0


if __name__ == "__main__":
    init_db()
    print(f"初期化しました (PostgreSQL)")
