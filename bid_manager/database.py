"""SQLite データベースの初期化と操作。

仕様書 4章のテーブル設計（projects / costs / competitors / scrape_targets /
unit_prices）を実装する。利益・原価率・差額などの派生値は保存時に自動計算する。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterable, Iterator, Optional

from config import DB_PATH


# --------------------------------------------------------------------------- #
# 接続ヘルパ
# --------------------------------------------------------------------------- #
@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """行を dict 風に扱える接続を返すコンテキストマネージャ。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# スキーマ
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    client      TEXT,
    region      TEXT,
    category    TEXT,
    deadline    DATE,
    budget      INTEGER,
    source_url  TEXT,
    status      TEXT NOT NULL DEFAULT '新着',
    created_at  DATETIME NOT NULL,
    updated_at  DATETIME NOT NULL,
    UNIQUE(title, source_url)
);

CREATE TABLE IF NOT EXISTS costs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
    estimate_amount INTEGER,
    actual_cost     INTEGER,
    profit          INTEGER,
    profit_rate     REAL,
    memo            TEXT,
    updated_at      DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS competitors (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    competitor_name   TEXT,
    competitor_amount INTEGER,
    diff_amount       INTEGER,
    source            TEXT,
    memo              TEXT
);

CREATE TABLE IF NOT EXISTS scrape_targets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    url             TEXT NOT NULL UNIQUE,
    region          TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    last_scraped_at DATETIME
);

CREATE TABLE IF NOT EXISTS unit_prices (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    category   TEXT,
    item_name  TEXT NOT NULL,
    unit       TEXT,
    unit_price INTEGER,
    memo       TEXT,
    updated_at DATETIME NOT NULL
);
"""


def init_db() -> None:
    """全テーブルを作成（既存なら何もしない）。"""
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# --------------------------------------------------------------------------- #
# projects
# --------------------------------------------------------------------------- #
def add_project(
    *,
    title: str,
    client: Optional[str] = None,
    region: Optional[str] = None,
    category: Optional[str] = None,
    deadline: Optional[str] = None,
    budget: Optional[int] = None,
    source_url: Optional[str] = None,
    status: str = "新着",
) -> Optional[int]:
    """案件を追加。重複（title + source_url）なら None を返してスキップ。"""
    now = _now()
    with get_conn() as conn:
        try:
            cur = conn.execute(
                """INSERT INTO projects
                   (title, client, region, category, deadline, budget,
                    source_url, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (title, client, region, category, deadline, budget,
                 source_url, status, now, now),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None  # 重複


def list_projects(
    *,
    status: Optional[str] = None,
    region: Optional[str] = None,
    keyword: Optional[str] = None,
    within_days: Optional[int] = None,
    order_by: str = "deadline",
) -> list[sqlite3.Row]:
    """フィルタ・ソート付きで案件一覧を取得。"""
    where: list[str] = []
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status)
    if region:
        where.append("region = ?")
        params.append(region)
    if keyword:
        where.append("(title LIKE ? OR client LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if within_days is not None:
        where.append("deadline IS NOT NULL AND date(deadline) <= date('now', ?)")
        params.append(f"+{within_days} day")

    order = {
        "deadline": "deadline ASC",
        "created": "created_at DESC",
    }.get(order_by, "deadline ASC")

    sql = "SELECT * FROM projects"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {order}"
    with get_conn() as conn:
        return conn.execute(sql, params).fetchall()


def get_project(project_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()


def update_status(project_id: int, status: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), project_id),
        )


# --------------------------------------------------------------------------- #
# costs（利益・原価率を自動計算）
# --------------------------------------------------------------------------- #
def upsert_cost(
    project_id: int,
    *,
    estimate_amount: Optional[int],
    actual_cost: Optional[int],
    memo: Optional[str] = None,
) -> None:
    profit: Optional[int] = None
    profit_rate: Optional[float] = None
    if estimate_amount is not None and actual_cost is not None:
        profit = estimate_amount - actual_cost
        if estimate_amount:
            profit_rate = round(actual_cost / estimate_amount * 100, 2)  # 原価率(%)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO costs
               (project_id, estimate_amount, actual_cost, profit, profit_rate, memo, updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(project_id) DO UPDATE SET
                   estimate_amount=excluded.estimate_amount,
                   actual_cost=excluded.actual_cost,
                   profit=excluded.profit,
                   profit_rate=excluded.profit_rate,
                   memo=excluded.memo,
                   updated_at=excluded.updated_at""",
            (project_id, estimate_amount, actual_cost, profit, profit_rate, memo, _now()),
        )


def get_cost(project_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM costs WHERE project_id = ?", (project_id,)
        ).fetchone()


# --------------------------------------------------------------------------- #
# competitors（自社見積との差額を自動計算）
# --------------------------------------------------------------------------- #
def add_competitor(
    project_id: int,
    *,
    competitor_name: Optional[str],
    competitor_amount: Optional[int],
    source: Optional[str] = None,
    memo: Optional[str] = None,
) -> None:
    diff_amount: Optional[int] = None
    cost = get_cost(project_id)
    if cost and cost["estimate_amount"] is not None and competitor_amount is not None:
        diff_amount = cost["estimate_amount"] - competitor_amount
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO competitors
               (project_id, competitor_name, competitor_amount, diff_amount, source, memo)
               VALUES (?,?,?,?,?,?)""",
            (project_id, competitor_name, competitor_amount, diff_amount, source, memo),
        )


def list_competitors(project_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM competitors WHERE project_id = ? ORDER BY id", (project_id,)
        ).fetchall()


# --------------------------------------------------------------------------- #
# scrape_targets
# --------------------------------------------------------------------------- #
def add_target(name: str, url: str, region: Optional[str] = None) -> Optional[int]:
    with get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO scrape_targets (name, url, region, is_active) VALUES (?,?,?,1)",
                (name, url, region),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def list_targets(active_only: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM scrape_targets"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY id"
    with get_conn() as conn:
        return conn.execute(sql).fetchall()


def set_target_active(target_id: int, active: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE scrape_targets SET is_active = ? WHERE id = ?",
            (1 if active else 0, target_id),
        )


def delete_target(target_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM scrape_targets WHERE id = ?", (target_id,))


def mark_target_scraped(target_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE scrape_targets SET last_scraped_at = ? WHERE id = ?",
            (_now(), target_id),
        )


# --------------------------------------------------------------------------- #
# unit_prices（単価マスタ）
# --------------------------------------------------------------------------- #
def add_unit_price(
    *, category: str, item_name: str, unit: str, unit_price: int, memo: Optional[str] = None
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO unit_prices (category, item_name, unit, unit_price, memo, updated_at)
               VALUES (?,?,?,?,?,?)""",
            (category, item_name, unit, unit_price, memo, _now()),
        )
        return cur.lastrowid


def list_unit_prices() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM unit_prices ORDER BY category, item_name").fetchall()


if __name__ == "__main__":
    init_db()
    print(f"Initialized database at {DB_PATH}")
