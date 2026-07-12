"""SQLite スキーマと CRUD。

紙の「作業日報」フォームに準拠した構造:
  reports                … 1現場×1日で1枚（ヘッダー・自社交通手段・現場代理人）
  report_workers         … 自社作業員の明細（複数行）
  report_subcontractors  … 協力会社の明細（複数行）
  workers / sites        … 入力補助用マスタ

作業時間（work_hours）は開始・終了から自動計算する（休憩欄は用紙に無いため span）。

使い方:
    python database.py   # DB を初期化（テーブル作成）
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterable

import config


# --------------------------------------------------------------------------
# 接続
# --------------------------------------------------------------------------
@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# スキーマ
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS workers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,             -- 氏名（漢字）
    kana        TEXT,                      -- よみがな（音声→漢字変換の照合用）
    role        TEXT,
    phone       TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,              -- 現場名
    client      TEXT,                       -- 発注先
    address     TEXT,
    category    TEXT,                       -- 工事種別
    start_date  TEXT,
    end_date    TEXT,
    status      TEXT NOT NULL DEFAULT '着工前',
    memo        TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date         TEXT NOT NULL,      -- 年月日
    site_id             INTEGER NOT NULL,   -- 現場名
    client              TEXT,               -- 発注先（現場から既定・上書き可）
    work_content        TEXT,               -- 作業内容・使用材料（共通欄）
    own_car             INTEGER NOT NULL DEFAULT 0,  -- 交通手段: 車
    own_train           INTEGER NOT NULL DEFAULT 0,  -- 交通手段: 電車
    own_car_count       INTEGER NOT NULL DEFAULT 0,  -- 車 台数
    own_transport_cost  INTEGER NOT NULL DEFAULT 0,  -- 交通費（円）
    manager             TEXT,               -- 現場代理人又は責任者
    status              TEXT NOT NULL DEFAULT '提出済',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY (site_id) REFERENCES sites(id)
);

CREATE TABLE IF NOT EXISTS report_workers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id    INTEGER NOT NULL,
    worker_name  TEXT NOT NULL,             -- 作業員名
    start_time   TEXT,                      -- 'HH:MM'
    end_time     TEXT,
    overtime_h   REAL NOT NULL DEFAULT 0,   -- 残業(h)
    lodging      INTEGER NOT NULL DEFAULT 0,-- 宿泊
    work_hours   REAL NOT NULL DEFAULT 0,   -- 作業時間（自動計算）
    sort_order   INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS report_subcontractors (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id        INTEGER NOT NULL,
    company_name     TEXT NOT NULL,         -- 会社名
    worker_name      TEXT,                  -- 作業員名
    headcount        INTEGER NOT NULL DEFAULT 0,  -- 人数
    start_time       TEXT,
    end_time         TEXT,
    work_content     TEXT,                  -- 作業内容
    transport_car    INTEGER NOT NULL DEFAULT 0,  -- 車
    transport_share  INTEGER NOT NULL DEFAULT 0,  -- 乗合
    transport_train  INTEGER NOT NULL DEFAULT 0,  -- 電車
    car_count        INTEGER NOT NULL DEFAULT 0,
    transport_cost   INTEGER NOT NULL DEFAULT 0,  -- 交通費（円）
    approved         INTEGER NOT NULL DEFAULT 0,  -- 承認印
    sort_order       INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reports_date ON reports(report_date);
CREATE INDEX IF NOT EXISTS idx_reports_site ON reports(site_id);
CREATE INDEX IF NOT EXISTS idx_rworkers_report ON report_workers(report_id);
CREATE INDEX IF NOT EXISTS idx_rsubs_report ON report_subcontractors(report_id);
"""


def init_db() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn) -> None:
    """既存DBへの後方互換マイグレーション（不足カラムを追加）。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(workers)")}
    if "kana" not in cols:
        conn.execute("ALTER TABLE workers ADD COLUMN kana TEXT")


# --------------------------------------------------------------------------
# ヘルパー
# --------------------------------------------------------------------------
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def calc_span_hours(start: str | None, end: str | None) -> float:
    """'HH:MM' の開始〜終了から作業時間(h)を計算する。休憩欄は用紙に無いため span。"""
    if not start or not end:
        return 0.0
    try:
        sh, sm = (int(x) for x in start.split(":"))
        eh, em = (int(x) for x in end.split(":"))
    except (ValueError, AttributeError):
        return 0.0
    total = (eh * 60 + em) - (sh * 60 + sm)
    return round(total / 60, 2) if total > 0 else 0.0


def _dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# 作業員マスタ CRUD
# --------------------------------------------------------------------------
def add_worker(name: str, role: str = "", phone: str = "", kana: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO workers (name, kana, role, phone, is_active, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (name, kana, role, phone, _now()),
        )
        return cur.lastrowid


def _normalize_kana(s: str | None) -> str:
    """照合用の正規化: カタカナ→ひらがな、空白・記号を除去。"""
    if not s:
        return ""
    out = []
    for ch in s:
        o = ord(ch)
        if 0x30A1 <= o <= 0x30F6:  # カタカナ → ひらがな
            out.append(chr(o - 0x60))
        elif ch in " 　・.,、。･":
            continue
        else:
            out.append(ch)
    return "".join(out)


def match_worker_name(spoken: str) -> tuple[str, bool]:
    """話した/入力された名前（ひらがな・カタカナ・漢字）を作業員名簿と照合し、
    最も近い登録氏名（漢字）を返す。(氏名, 一致したか) を返す。
    一致しなければ入力をそのまま返す。"""
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
            if ns in nt or nt in ns:  # 姓だけ言う等の部分一致を優遇
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
    """日報で入力された作業員名のうち、名簿に無いものを新規登録する。
    登録した氏名の一覧を返す。かなのみの名前は照合用に kana にも入れる。"""
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
    cols = ", ".join(f"{k} = ?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE workers SET {cols} WHERE id = ?", (*fields.values(), worker_id))


def list_workers(active_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM workers"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY is_active DESC, name"
    with get_conn() as conn:
        return _dicts(conn.execute(sql).fetchall())


# --------------------------------------------------------------------------
# 現場マスタ CRUD
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
        cur = conn.execute(
            "INSERT INTO sites (name, client, address, category, start_date, "
            "end_date, status, memo, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, client, address, category, start_date, end_date, status, memo, _now()),
        )
        return cur.lastrowid


def update_site(site_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE sites SET {cols} WHERE id = ?", (*fields.values(), site_id))


def get_site(site_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
        return dict(row) if row else None


def list_sites(active_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM sites"
    if active_only:
        sql += " WHERE status IN ('着工前', '施工中')"
    sql += " ORDER BY (status IN ('着工前','施工中')) DESC, name"
    with get_conn() as conn:
        return _dicts(conn.execute(sql).fetchall())


# --------------------------------------------------------------------------
# 日報 CRUD
# --------------------------------------------------------------------------
def _insert_workers(conn, report_id: int, workers: list[dict[str, Any]]) -> None:
    for i, w in enumerate(workers or []):
        name = (w.get("worker_name") or "").strip()
        if not name:
            continue
        start, end = w.get("start_time"), w.get("end_time")
        conn.execute(
            "INSERT INTO report_workers (report_id, worker_name, start_time, end_time, "
            "overtime_h, lodging, work_hours, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                report_id, name, start, end,
                float(w.get("overtime_h", 0) or 0),
                1 if w.get("lodging") else 0,
                calc_span_hours(start, end),
                i,
            ),
        )


def _insert_subs(conn, report_id: int, subs: list[dict[str, Any]]) -> None:
    for i, s in enumerate(subs or []):
        company = (s.get("company_name") or "").strip()
        if not company:
            continue
        conn.execute(
            "INSERT INTO report_subcontractors (report_id, company_name, worker_name, "
            "headcount, start_time, end_time, work_content, transport_car, transport_share, "
            "transport_train, car_count, transport_cost, approved, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                report_id, company, (s.get("worker_name") or "").strip(),
                int(s.get("headcount", 0) or 0), s.get("start_time"), s.get("end_time"),
                (s.get("work_content") or "").strip(),
                1 if s.get("transport_car") else 0,
                1 if s.get("transport_share") else 0,
                1 if s.get("transport_train") else 0,
                int(s.get("car_count", 0) or 0),
                int(s.get("transport_cost", 0) or 0),
                1 if s.get("approved") else 0,
                i,
            ),
        )


def add_report(
    report_date: str,
    site_id: int,
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
        cur = conn.execute(
            "INSERT INTO reports (report_date, site_id, client, work_content, own_car, "
            "own_train, own_car_count, own_transport_cost, manager, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                report_date, site_id, client, work_content,
                1 if own_car else 0, 1 if own_train else 0,
                int(own_car_count or 0), int(own_transport_cost or 0),
                manager, status, now, now,
            ),
        )
        report_id = cur.lastrowid
        _insert_workers(conn, report_id, workers or [])
        _insert_subs(conn, report_id, subcontractors or [])
    return report_id


def update_report(
    report_id: int,
    workers: list[dict[str, Any]] | None = None,
    subcontractors: list[dict[str, Any]] | None = None,
    **fields: Any,
) -> None:
    """ヘッダー項目を更新。workers / subcontractors を渡した場合は明細を全置き換え。"""
    fields["updated_at"] = _now()
    # bool を 0/1 に正規化
    for k in ("own_car", "own_train"):
        if k in fields:
            fields[k] = 1 if fields[k] else 0
    cols = ", ".join(f"{k} = ?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE reports SET {cols} WHERE id = ?", (*fields.values(), report_id))
        if workers is not None:
            conn.execute("DELETE FROM report_workers WHERE report_id = ?", (report_id,))
            _insert_workers(conn, report_id, workers)
        if subcontractors is not None:
            conn.execute("DELETE FROM report_subcontractors WHERE report_id = ?", (report_id,))
            _insert_subs(conn, report_id, subcontractors)


def delete_report(report_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))


def get_report(report_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT r.*, s.name AS site_name FROM reports r "
            "JOIN sites s ON s.id = r.site_id WHERE r.id = ?",
            (report_id,),
        ).fetchone()
        return dict(row) if row else None


def get_report_workers(report_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        return _dicts(conn.execute(
            "SELECT * FROM report_workers WHERE report_id = ? ORDER BY sort_order, id",
            (report_id,),
        ).fetchall())


def get_report_subcontractors(report_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        return _dicts(conn.execute(
            "SELECT * FROM report_subcontractors WHERE report_id = ? ORDER BY sort_order, id",
            (report_id,),
        ).fetchall())


def list_reports(
    date_from: str | None = None,
    date_to: str | None = None,
    site_id: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
    """日報一覧。人数・作業時間・交通費の集計列を含む。"""
    sql = [
        """
        SELECT r.*, s.name AS site_name,
          (SELECT COUNT(*) FROM report_workers rw WHERE rw.report_id = r.id) AS worker_count,
          (SELECT COALESCE(SUM(rw.work_hours),0) FROM report_workers rw WHERE rw.report_id = r.id) AS total_hours,
          (SELECT COALESCE(SUM(rw.overtime_h),0) FROM report_workers rw WHERE rw.report_id = r.id) AS total_overtime,
          (SELECT COALESCE(SUM(rs.headcount),0) FROM report_subcontractors rs WHERE rs.report_id = r.id) AS sub_headcount,
          (r.own_transport_cost +
           (SELECT COALESCE(SUM(rs.transport_cost),0) FROM report_subcontractors rs WHERE rs.report_id = r.id)) AS total_transport_cost
        FROM reports r
        JOIN sites s ON s.id = r.site_id
        WHERE 1 = 1
        """
    ]
    params: list[Any] = []
    if date_from:
        sql.append("AND r.report_date >= ?"); params.append(date_from)
    if date_to:
        sql.append("AND r.report_date <= ?"); params.append(date_to)
    if site_id:
        sql.append("AND r.site_id = ?"); params.append(site_id)
    if status:
        sql.append("AND r.status = ?"); params.append(status)
    if keyword:
        sql.append(
            "AND (r.work_content LIKE ? OR r.manager LIKE ? OR "
            "EXISTS (SELECT 1 FROM report_workers rw WHERE rw.report_id = r.id AND rw.worker_name LIKE ?))"
        )
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
    sql.append("ORDER BY r.report_date DESC, r.id DESC")
    with get_conn() as conn:
        return _dicts(conn.execute("\n".join(sql), params).fetchall())


def list_worker_lines(date_from: str | None = None, date_to: str | None = None) -> list[dict[str, Any]]:
    """分析用: 自社作業員の明細に現場・日付を結合した行を返す。"""
    sql = [
        """
        SELECT rw.*, r.report_date, s.name AS site_name
        FROM report_workers rw
        JOIN reports r ON r.id = rw.report_id
        JOIN sites s ON s.id = r.site_id
        WHERE 1 = 1
        """
    ]
    params: list[Any] = []
    if date_from:
        sql.append("AND r.report_date >= ?"); params.append(date_from)
    if date_to:
        sql.append("AND r.report_date <= ?"); params.append(date_to)
    with get_conn() as conn:
        return _dicts(conn.execute("\n".join(sql), params).fetchall())


if __name__ == "__main__":
    init_db()
    print(f"DB を初期化しました: {config.DB_PATH}")
