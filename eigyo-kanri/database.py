"""PostgreSQL スキーマと CRUD。

営業に来た人の「会社名・担当者名・営業内容」を一覧管理するためのテーブル。
金額や日付は将来の集計・分析に備えて素直な型で保存する。
"""
from __future__ import annotations

import sys
from datetime import datetime, date
from pathlib import Path
from typing import Any

import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from dbconn import get_conn  # noqa: E402

from config import DEFAULT_STATUS, DEFAULT_INDUSTRY


def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    """スキーマは shared/schema.sql で管理。ここでは何もしない。"""
    print("DB 初期化完了 (PostgreSQL)")


def add_visit(**fields):
    now = datetime.now().isoformat(timespec="seconds")
    row = {
        "industry": DEFAULT_INDUSTRY,
        "company_name": "",
        "rep_name": "",
        "business_overview": "",
        "sales_content": "",
        "phone": "",
        "email": "",
        "website": "",
        "address": "",
        "visit_date": None,
        "received_date": date.today().isoformat(),
        "source_file": "",
        "status": DEFAULT_STATUS,
        "memo": "",
    }
    row.update({k: v for k, v in fields.items() if k in row})
    cols = list(row.keys()) + ["created_at", "updated_at"]
    vals = list(row.values()) + [now, now]
    placeholders = ", ".join("%s" for _ in cols)
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                f"INSERT INTO sales.visits ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id",
                vals,
            )
            return cur.fetchone()["id"]


def update_visit(visit_id, **fields):
    allowed = {
        "industry", "company_name", "rep_name", "business_overview", "sales_content",
        "phone", "email", "website", "address", "visit_date", "received_date",
        "source_file", "status", "memo",
    }
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    sets["updated_at"] = datetime.now().isoformat(timespec="seconds")
    assignments = ", ".join(f"{k} = %s" for k in sets)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE sales.visits SET {assignments} WHERE id = %s",
                        list(sets.values()) + [visit_id])


def delete_visit(visit_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sales.visits WHERE id = %s", (visit_id,))


def get_visit(visit_id):
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM sales.visits WHERE id = %s", (visit_id,))
            r = cur.fetchone()
            return dict(r) if r else None


def get_visits(status=None, keyword=None, industry=None, company=None, order_by="received_date"):
    sql = "SELECT * FROM sales.visits WHERE 1=1"
    params: list[Any] = []
    if status and status != "すべて":
        sql += " AND status = %s"
        params.append(status)
    if industry:
        sql += " AND industry = %s"
        params.append(industry)
    if company is not None:
        sql += " AND company_name = %s"
        params.append(company)
    if keyword:
        sql += " AND (company_name LIKE %s OR rep_name LIKE %s OR sales_content LIKE %s)"
        like = f"%{keyword}%"
        params += [like, like, like]
    order_col = order_by if order_by in {"received_date", "visit_date", "created_at", "company_name"} else "received_date"
    sql += f" ORDER BY {order_col} DESC, id DESC"
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def get_industry_counts():
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                """
                SELECT industry,
                       COUNT(DISTINCT company_name) AS companies,
                       COUNT(*) AS records
                FROM sales.visits
                GROUP BY industry
                ORDER BY records DESC, industry
                """
            )
            return [dict(r) for r in cur.fetchall()]


def get_companies_in_industry(industry):
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                """
                SELECT company_name,
                       COUNT(*) AS records,
                       MAX(received_date)::TEXT AS last_received
                FROM sales.visits
                WHERE industry = %s
                GROUP BY company_name
                ORDER BY MAX(received_date) DESC, company_name
                """,
                (industry,),
            )
            rows = [dict(r) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT company_name, business_overview
                FROM sales.visits
                WHERE industry = %s AND business_overview <> ''
                ORDER BY received_date ASC, id ASC
                """,
                (industry,),
            )
            overview = {}
            for r in cur.fetchall():
                overview[r["company_name"]] = r["business_overview"]

            for r in rows:
                r["business_overview"] = overview.get(r["company_name"], "")
            return rows


def source_file_exists(path):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM sales.visits WHERE source_file = %s LIMIT 1", (path,)
            )
            return cur.fetchone() is not None


def stats():
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM sales.visits")
            total = cur.fetchone()["cnt"]
            cur.execute(
                "SELECT status, COUNT(*) AS c FROM sales.visits GROUP BY status"
            )
            by_status = {r["status"]: r["c"] for r in cur.fetchall()}
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM sales.visits "
                "WHERE TO_CHAR(received_date, 'YYYY-MM') = TO_CHAR(CURRENT_DATE, 'YYYY-MM')"
            )
            this_month = cur.fetchone()["cnt"]
            return {"total": total, "by_status": by_status, "this_month": this_month}


if __name__ == "__main__":
    init_db()
