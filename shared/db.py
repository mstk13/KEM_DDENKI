"""共通データベース接続モジュール。

全アプリが PostgreSQL に統一接続するための共通レイヤー。
SQLite 互換の Row オブジェクト（辞書アクセス可能）を提供する。

環境変数:
    DATABASE_URL  ... PostgreSQL 接続文字列 (例: postgresql://kem:kem@postgres:5432/kem_ddenki)
    KEM_USE_SQLITE ... "1" にすると従来の SQLite モードで動作（移行期間用）
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2
import psycopg2.extras

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://kem:kem@localhost:5432/kem_ddenki",
)


@contextmanager
def get_conn() -> Iterator[psycopg2.extensions.connection]:
    """自動コミット付きの PostgreSQL 接続を返すコンテキストマネージャ。"""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute(sql: str, params: tuple | list = (), *, conn=None) -> list[dict[str, Any]]:
    """SQL を実行し、結果を辞書のリストで返す。"""
    def _run(c):
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                return [dict(row) for row in cur.fetchall()]
            return []

    if conn is not None:
        return _run(conn)

    with get_conn() as c:
        return _run(c)


def execute_one(sql: str, params: tuple | list = (), *, conn=None) -> dict[str, Any] | None:
    """SQL を実行し、最初の1行を辞書で返す。結果が無ければ None。"""
    rows = execute(sql, params, conn=conn)
    return rows[0] if rows else None


def execute_insert(sql: str, params: tuple | list = (), *, conn=None) -> int | None:
    """INSERT ... RETURNING id を実行し、id を返す。"""
    def _run(c):
        with c.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else None

    if conn is not None:
        return _run(conn)

    with get_conn() as c:
        result = _run(c)
        return result
