"""SQLite データ層。

テーブル構成:
    employees  … 社員マスタ
    reports    … 日報ヘッダ(日付・現場・作業内容・原文)
    entries    … 社員別の勤怠明細(1行 = 社員 × 1日報)
    settings   … 規定時間などの運用設定(key-value)

`python database.py` で初期化(テーブル作成)できる。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT,
    name        TEXT NOT NULL UNIQUE,
    kana        TEXT DEFAULT '',
    department  TEXT DEFAULT '',
    position    TEXT DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 1,
    note        TEXT DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date   TEXT NOT NULL,
    site_name     TEXT DEFAULT '',
    work_content  TEXT DEFAULT '',
    note          TEXT DEFAULT '',
    status        TEXT NOT NULL DEFAULT '未確認',
    source_text   TEXT DEFAULT '',
    source_key    TEXT DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entries (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id        INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    employee_id      INTEGER REFERENCES employees(id) ON DELETE SET NULL,
    employee_name    TEXT NOT NULL DEFAULT '',
    start_time       TEXT DEFAULT '',
    end_time         TEXT DEFAULT '',
    break_minutes    INTEGER DEFAULT 0,
    early_minutes    INTEGER NOT NULL DEFAULT 0,
    normal_minutes   INTEGER NOT NULL DEFAULT 0,
    overtime_minutes INTEGER NOT NULL DEFAULT 0,
    total_minutes    INTEGER NOT NULL DEFAULT 0,
    note             TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reports_date   ON reports(report_date);
CREATE INDEX IF NOT EXISTS idx_entries_report ON entries(report_id);
CREATE INDEX IF NOT EXISTS idx_entries_emp    ON entries(employee_id);
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def get_conn():
    """コミット/ロールバックを自動化した接続。"""
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn) -> None:
    """既存 DB に対する後方互換のためのカラム追加。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(reports)")}
    if "source_key" not in cols:
        conn.execute("ALTER TABLE reports ADD COLUMN source_key TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_source ON reports(source_key)")


# ---------------------------------------------------------------------------
# 設定(規定時間など)
# ---------------------------------------------------------------------------
def get_settings() -> dict:
    """DB の設定を既定値にマージして返す。"""
    values = dict(config.DEFAULT_SETTINGS)
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
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
        conn.executemany(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(k, str(v)) for k, v in values.items() if k in config.DEFAULT_SETTINGS],
        )


# ---------------------------------------------------------------------------
# 社員マスタ
# ---------------------------------------------------------------------------
def list_employees(active_only: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM employees"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY active DESC, code, name"
    with get_conn() as conn:
        return conn.execute(sql).fetchall()


def get_employee_by_name(name: str) -> sqlite3.Row | None:
    """氏名(空白差を無視)で社員を検索する。"""
    if not name:
        return None
    key = str(name).replace(" ", "").replace("　", "")
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM employees").fetchall()
    for row in rows:
        if row["name"].replace(" ", "").replace("　", "") == key:
            return row
        if row["kana"] and row["kana"].replace(" ", "").replace("　", "") == key:
            return row
    return None


def add_employee(name: str, code: str = "", kana: str = "", department: str = "",
                 position: str = "", active: int = 1, note: str = "") -> int:
    """社員を追加。既存名なら既存 ID を返す。"""
    existing = get_employee_by_name(name)
    if existing:
        return int(existing["id"])
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO employees(code, name, kana, department, position, active, note, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (code, name.strip(), kana, department, position, int(active), note, _now()),
        )
        return int(cur.lastrowid)


def update_employee(emp_id: int, **fields) -> None:
    allowed = {"code", "name", "kana", "department", "position", "active", "note"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    clause = ", ".join(f"{k} = ?" for k in sets)
    with get_conn() as conn:
        conn.execute(f"UPDATE employees SET {clause} WHERE id = ?",
                     (*sets.values(), int(emp_id)))


def delete_employee(emp_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM employees WHERE id = ?", (int(emp_id),))


# ---------------------------------------------------------------------------
# 日報 / 勤怠明細
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
    """日報ヘッダ + 勤怠明細を登録し、report_id を返す。"""
    settings = settings or get_settings()
    now = _now()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO reports(report_date, site_name, work_content, note, status, "
            "source_text, source_key, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (report_date, site_name, work_content, note, status, source_text,
             source_key, now, now),
        )
        report_id = int(cur.lastrowid)
    _replace_entries(report_id, entries or [], settings)
    return report_id


def find_report_by_source(source_key: str) -> int | None:
    """外部アプリ由来の日報を source_key で特定する(重複取込の防止)。"""
    if not source_key:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM reports WHERE source_key = ? ORDER BY id LIMIT 1", (source_key,)
        ).fetchone()
    return int(row["id"]) if row else None


def update_report(report_id: int, entries: list[dict] | None = None,
                  settings: dict | None = None, **fields) -> None:
    allowed = {"report_date", "site_name", "work_content", "note", "status", "source_key"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    with get_conn() as conn:
        if sets:
            clause = ", ".join(f"{k} = ?" for k in sets)
            conn.execute(f"UPDATE reports SET {clause}, updated_at = ? WHERE id = ?",
                         (*sets.values(), _now(), int(report_id)))
    if entries is not None:
        _replace_entries(report_id, entries, settings or get_settings())


def _replace_entries(report_id: int, entries: list[dict], settings: dict) -> None:
    rows = []
    for e in entries:
        calc = _calc(e, settings)
        rows.append((
            int(report_id),
            e.get("employee_id"),
            (e.get("employee_name") or "").strip(),
            e.get("start_time") or "",
            e.get("end_time") or "",
            int(calc["break"]),
            calc["early"], calc["normal"], calc["overtime"], calc["total"],
            e.get("note") or "",
        ))
    with get_conn() as conn:
        conn.execute("DELETE FROM entries WHERE report_id = ?", (int(report_id),))
        if rows:
            conn.executemany(
                "INSERT INTO entries(report_id, employee_id, employee_name, start_time, "
                "end_time, break_minutes, early_minutes, normal_minutes, overtime_minutes, "
                "total_minutes, note) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )


def delete_report(report_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM entries WHERE report_id = ?", (int(report_id),))
        conn.execute("DELETE FROM reports WHERE id = ?", (int(report_id),))


def get_report(report_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM reports WHERE id = ?", (int(report_id),)).fetchone()


def get_report_entries(report_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM entries WHERE report_id = ? ORDER BY id", (int(report_id),)
        ).fetchall()


def find_report_id(report_date: str, site_name: str) -> int | None:
    """同じ日付・現場の日報 ID を返す(重複登録の判定用)。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM reports WHERE report_date = ? AND site_name = ? "
            "ORDER BY id LIMIT 1",
            (report_date, site_name),
        ).fetchone()
    return int(row["id"]) if row else None


def list_reports(date_from: str = "", date_to: str = "", sites: list[str] | None = None,
                 statuses: list[str] | None = None, keyword: str = "") -> list[sqlite3.Row]:
    """日報単位の一覧(人数・時間の集計付き)。"""
    sql = [
        "SELECT r.*, COUNT(e.id) AS worker_count,",
        "  COALESCE(SUM(e.early_minutes),0)    AS early_minutes,",
        "  COALESCE(SUM(e.normal_minutes),0)   AS normal_minutes,",
        "  COALESCE(SUM(e.overtime_minutes),0) AS overtime_minutes,",
        "  COALESCE(SUM(e.total_minutes),0)    AS total_minutes,",
        "  COALESCE(GROUP_CONCAT(e.employee_name, '、'), '') AS worker_names",
        "FROM reports r LEFT JOIN entries e ON e.report_id = r.id WHERE 1=1",
    ]
    params: list = []
    if date_from:
        sql.append("AND r.report_date >= ?"); params.append(date_from)
    if date_to:
        sql.append("AND r.report_date <= ?"); params.append(date_to)
    if sites:
        sql.append(f"AND r.site_name IN ({','.join('?' * len(sites))})"); params += list(sites)
    if statuses:
        sql.append(f"AND r.status IN ({','.join('?' * len(statuses))})"); params += list(statuses)
    if keyword:
        sql.append("AND (r.site_name LIKE ? OR r.work_content LIKE ? OR r.note LIKE ? "
                   "OR r.id IN (SELECT report_id FROM entries WHERE employee_name LIKE ?))")
        params += [f"%{keyword}%"] * 4
    sql.append("GROUP BY r.id ORDER BY r.report_date DESC, r.id DESC")
    with get_conn() as conn:
        return conn.execute(" ".join(sql), params).fetchall()


def list_entries(date_from: str = "", date_to: str = "", employee_ids: list[int] | None = None,
                 employee_names: list[str] | None = None, sites: list[str] | None = None,
                 statuses: list[str] | None = None, keyword: str = "") -> list[sqlite3.Row]:
    """勤怠明細の一覧(1行 = 社員 × 1日報)。"""
    sql = [
        "SELECT e.*, r.report_date, r.site_name, r.work_content, r.status, r.note AS report_note,",
        "  emp.code AS employee_code, emp.department, emp.position",
        "FROM entries e JOIN reports r ON r.id = e.report_id",
        "LEFT JOIN employees emp ON emp.id = e.employee_id WHERE 1=1",
    ]
    params: list = []
    if date_from:
        sql.append("AND r.report_date >= ?"); params.append(date_from)
    if date_to:
        sql.append("AND r.report_date <= ?"); params.append(date_to)
    if employee_ids:
        sql.append(f"AND e.employee_id IN ({','.join('?' * len(employee_ids))})")
        params += [int(i) for i in employee_ids]
    if employee_names:
        sql.append(f"AND e.employee_name IN ({','.join('?' * len(employee_names))})")
        params += list(employee_names)
    if sites:
        sql.append(f"AND r.site_name IN ({','.join('?' * len(sites))})"); params += list(sites)
    if statuses:
        sql.append(f"AND r.status IN ({','.join('?' * len(statuses))})"); params += list(statuses)
    if keyword:
        sql.append("AND (r.site_name LIKE ? OR r.work_content LIKE ? OR e.employee_name LIKE ?)")
        params += [f"%{keyword}%"] * 3
    sql.append("ORDER BY r.report_date DESC, e.employee_name, e.id")
    with get_conn() as conn:
        return conn.execute(" ".join(sql), params).fetchall()


def list_sites() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT site_name FROM reports WHERE site_name <> '' ORDER BY site_name"
        ).fetchall()
    return [r["site_name"] for r in rows]


def link_entries_to_employees() -> int:
    """employee_id が未設定の明細を、氏名一致で社員マスタに紐付ける。"""
    linked = 0
    with get_conn() as conn:
        emps = conn.execute("SELECT id, name, kana FROM employees").fetchall()
        lookup = {}
        for e in emps:
            lookup[e["name"].replace(" ", "").replace("　", "")] = e["id"]
            if e["kana"]:
                lookup.setdefault(e["kana"].replace(" ", "").replace("　", ""), e["id"])
        rows = conn.execute(
            "SELECT id, employee_name FROM entries WHERE employee_id IS NULL"
        ).fetchall()
        for row in rows:
            emp_id = lookup.get((row["employee_name"] or "").replace(" ", "").replace("　", ""))
            if emp_id:
                conn.execute("UPDATE entries SET employee_id = ? WHERE id = ?", (emp_id, row["id"]))
                linked += 1
    return linked


def recalculate_all(settings: dict | None = None) -> int:
    """規定時間の変更後に、全明細の早朝/通常/残業を再計算する。"""
    settings = settings or get_settings()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, start_time, end_time, break_minutes FROM entries"
        ).fetchall()
        updates = []
        for row in rows:
            calc = config.calc_attendance(
                row["start_time"], row["end_time"], row["break_minutes"], settings
            )
            updates.append((calc["early"], calc["normal"], calc["overtime"],
                            calc["total"], calc["break"], row["id"]))
        if updates:
            conn.executemany(
                "UPDATE entries SET early_minutes=?, normal_minutes=?, overtime_minutes=?, "
                "total_minutes=?, break_minutes=? WHERE id=?",
                updates,
            )
    return len(rows)


if __name__ == "__main__":
    init_db()
    print(f"初期化しました: {config.DB_PATH}")
