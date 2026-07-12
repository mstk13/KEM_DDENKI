"""DB — 統合スキーマ（KEM_DDENKI互換の裏側 + 材料管理UI用）"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

DATABASE = "construction.db"


def get_db():
    """Flask g 用"""
    from flask import g
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    from flask import g
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ================================================================
# スキーマ — KEM_DDENKI 統合構造
# ================================================================
SCHEMA = """
-- 案件/現場（入札~施工~完了を1レコードで追跡）
CREATE TABLE IF NOT EXISTS project (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    client      TEXT DEFAULT '',
    region      TEXT DEFAULT '',
    address     TEXT DEFAULT '',
    category    TEXT DEFAULT '',
    scale       TEXT DEFAULT '',
    deadline    DATE,
    budget      INTEGER,
    status      TEXT NOT NULL DEFAULT '施工中',
    manager     TEXT DEFAULT '',
    source_url  TEXT,
    memo        TEXT DEFAULT '',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 品目マスタ（全案件共通）
CREATE TABLE IF NOT EXISTS item_master (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    spec            TEXT DEFAULT '',
    unit            TEXT NOT NULL DEFAULT '個',
    category        TEXT DEFAULT '',
    subcategory     TEXT DEFAULT '',
    standard_price  INTEGER DEFAULT 0,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 仕入先マスタ
CREATE TABLE IF NOT EXISTS supplier (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    contact     TEXT DEFAULT '',
    category    TEXT DEFAULT '',
    memo        TEXT DEFAULT '',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 見積もりヘッダ（版管理）
CREATE TABLE IF NOT EXISTS estimate_header (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL DEFAULT 1,
    total_amount INTEGER DEFAULT 0,
    submitted   INTEGER NOT NULL DEFAULT 0,
    created_by  TEXT DEFAULT '',
    memo        TEXT DEFAULT '',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 見積もり明細行
CREATE TABLE IF NOT EXISTS estimate_line (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    header_id   INTEGER NOT NULL REFERENCES estimate_header(id) ON DELETE CASCADE,
    item_id     INTEGER NOT NULL REFERENCES item_master(id),
    quantity    REAL NOT NULL,
    unit_price  INTEGER NOT NULL,
    amount      INTEGER NOT NULL,
    sort_order  INTEGER DEFAULT 0,
    memo        TEXT DEFAULT '',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 発注レコード（分割発注対応）
CREATE TABLE IF NOT EXISTS "order" (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    item_id     INTEGER NOT NULL REFERENCES item_master(id),
    supplier_id INTEGER REFERENCES supplier(id),
    quantity    REAL NOT NULL,
    unit_price  INTEGER NOT NULL,
    amount      INTEGER NOT NULL,
    order_date  DATE NOT NULL,
    orderer     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT '発注済',
    memo        TEXT DEFAULT '',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 単価履歴（AI学習用）
CREATE TABLE IF NOT EXISTS price_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id       INTEGER NOT NULL REFERENCES item_master(id),
    supplier_id   INTEGER REFERENCES supplier(id),
    unit_price    INTEGER NOT NULL,
    recorded_date DATE NOT NULL,
    source        TEXT DEFAULT '',
    memo          TEXT DEFAULT ''
);

-- 受領書（発注ごとにアップロード）
CREATE TABLE IF NOT EXISTS receipt (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL REFERENCES "order"(id) ON DELETE CASCADE,
    file_path   TEXT NOT NULL,
    file_name   TEXT NOT NULL,
    uploaded_by TEXT DEFAULT '',
    uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    memo        TEXT DEFAULT ''
);

-- 競合情報（将来KEM_DDENKI統合用）
CREATE TABLE IF NOT EXISTS competitor (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    competitor_name   TEXT,
    competitor_amount INTEGER,
    diff_amount       INTEGER,
    source            TEXT,
    memo              TEXT
);
"""


def init_db():
    conn = sqlite3.connect(DATABASE)
    conn.executescript(SCHEMA)
    conn.close()
    print("DB initialized (unified schema).")


if __name__ == "__main__":
    init_db()
