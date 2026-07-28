"""DB — PostgreSQL 統合スキーマ（材料管理UI用）"""
import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from dbconn import get_conn as _shared_get_conn, DATABASE_URL  # noqa: E402


class _PgWrapper:
    """SQLite 互換インターフェースで psycopg2 接続をラップする。

    app.py の `db.execute(sql, params).fetchone()` パターンをそのまま動かすため、
    ? プレースホルダを %s に変換し、結果を辞書アクセス可能にする。
    テーブル名の "order" → material.orders 等のマッピングも行う。
    """

    # SQLite テーブル名 → PostgreSQL スキーマ付きテーブル名
    _TABLE_MAP = {
        '"order"': 'material.orders',
        'project': 'master.sites',
        'item_master': 'material.item_master',
        'supplier': 'master.suppliers',
        'estimate_header': 'material.estimate_header',
        'estimate_line': 'material.estimate_line',
        'price_history': 'material.price_history',
        'order_cost': 'material.order_cost',
        'receipt': 'material.receipt',
        'competitor': 'bid.competitors',
    }

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        # ? → %s
        sql = sql.replace("?", "%s")
        # テーブル名をマッピング（FROM/INTO/UPDATE/JOIN の直後）
        for old, new in self._TABLE_MAP.items():
            sql = sql.replace(f" {old} ", f" {new} ")
            sql = sql.replace(f" {old}\n", f" {new}\n")
            sql = sql.replace(f" {old}(", f" {new}(")
            if sql.strip().startswith(f"INSERT INTO {old.strip('\"')}"):
                sql = sql.replace(f"INSERT INTO {old.strip('\"')}", f"INSERT INTO {new}")
            if sql.strip().startswith(f"UPDATE {old.strip('\"')}"):
                sql = sql.replace(f"UPDATE {old.strip('\"')}", f"UPDATE {new}")
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params or ())
        return _CursorWrapper(cur, self._conn)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


class _CursorWrapper:
    """fetchone/fetchall を辞書で返すラッパー。lastrowid をエミュレート。"""

    def __init__(self, cursor, conn):
        self._cursor = cursor
        self._conn = conn

    def fetchone(self):
        row = self._cursor.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(r) for r in self._cursor.fetchall()]

    @property
    def lastrowid(self):
        # PostgreSQL では RETURNING を使う必要がある。
        # INSERT 文の場合、RETURNING id を追加して再実行はできないので、
        # currval で代用する。
        try:
            cur2 = self._conn.cursor()
            cur2.execute("SELECT lastval()")
            return cur2.fetchone()[0]
        except Exception:
            return None


def get_db():
    """Flask g 用 — SQLite 互換ラッパーを返す。"""
    from flask import g
    if "db" not in g:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        g.db = _PgWrapper(conn)
    return g.db


def close_db(e=None):
    from flask import g
    db = g.pop("db", None)
    if db is not None:
        try:
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def init_db():
    """スキーマは shared/schema.sql で管理。"""
    print("DB initialized (PostgreSQL unified schema).")


if __name__ == "__main__":
    init_db()
