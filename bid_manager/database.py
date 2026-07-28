"""PostgreSQL データベースの初期化と操作。

仕様書 4章のテーブル設計（bid.projects / bid.costs / bid.competitors /
bid.scrape_targets / bid.unit_prices / bid.qualifications）を実装する。
利益・原価率・差額などの派生値は保存時に自動計算する。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import psycopg2
import psycopg2.extras

# shared モジュールをパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from dbconn import get_conn  # noqa: E402

from config import BASE_DIR


# --------------------------------------------------------------------------- #
# ヘルパー
# --------------------------------------------------------------------------- #
def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _dict(row) -> dict[str, Any] | None:
    return dict(row) if row else None


def _dicts(rows) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


# --------------------------------------------------------------------------- #
# スキーマ初期化
# --------------------------------------------------------------------------- #
QUALIFICATIONS_JSON = BASE_DIR / "data" / "qualifications.json"


def init_db() -> None:
    """スキーマは docker-entrypoint-initdb.d で適用済み。
    資格テーブルが空で qualifications.json が存在すれば自動復元する。"""
    _restore_qualifications_if_empty()


def _restore_qualifications_if_empty() -> None:
    if not QUALIFICATIONS_JSON.exists():
        return
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM bid.qualifications")
            count = cur.fetchone()["cnt"]
            if count > 0:
                return
    try:
        records = json.loads(QUALIFICATIONS_JSON.read_text(encoding="utf-8"))
        for rec in records:
            add_qualification(**rec)
        print(f"資格データを {QUALIFICATIONS_JSON} から {len(records)} 件復元しました。")
    except Exception as exc:
        print(f"資格データの復元に失敗: {exc}")


def save_qualifications_to_json() -> None:
    quals = list_qualifications()
    records = []
    for q in quals:
        records.append({
            "issuer": q["issuer"],
            "category": q["category"],
            "grade": q["grade"],
            "keisin_score": q["keisin_score"],
            "total_score": q["total_score"],
            "vendor_number": q["vendor_number"],
            "valid_from": str(q["valid_from"]) if q["valid_from"] else None,
            "valid_until": str(q["valid_until"]) if q["valid_until"] else None,
            "application_type": q["application_type"],
            "application_method": q["application_method"],
            "memo": q["memo"],
        })
    QUALIFICATIONS_JSON.parent.mkdir(parents=True, exist_ok=True)
    QUALIFICATIONS_JSON.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"資格データを {QUALIFICATIONS_JSON} に {len(records)} 件保存しました。")


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
    now = _now()
    with get_conn() as conn:
        with _cur(conn) as cur:
            if source_url is None:
                cur.execute(
                    "SELECT id FROM bid.projects WHERE title = %s AND source_url IS NULL",
                    (title,),
                )
                if cur.fetchone():
                    return None
            try:
                cur.execute(
                    """INSERT INTO bid.projects
                       (title, client, region, category, deadline, budget,
                        source_url, status, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (title, client, region, category, deadline, budget,
                     source_url, status, now, now),
                )
                return cur.fetchone()["id"]
            except psycopg2.IntegrityError:
                conn.rollback()
                return None


def list_projects(
    *,
    status: Optional[str] = None,
    region: Optional[str] = None,
    keyword: Optional[str] = None,
    within_days: Optional[int] = None,
    order_by: str = "deadline",
) -> list[dict]:
    where: list[str] = []
    params: list[Any] = []
    if status:
        where.append("status = %s")
        params.append(status)
    if region:
        where.append("region = %s")
        params.append(region)
    if keyword:
        where.append("(title LIKE %s OR client LIKE %s)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if within_days is not None:
        where.append("deadline IS NOT NULL AND deadline <= CURRENT_DATE + make_interval(days => %s)")
        params.append(within_days)

    order = {
        "deadline": "deadline ASC NULLS LAST",
        "created": "created_at DESC",
    }.get(order_by, "deadline ASC NULLS LAST")

    sql = "SELECT * FROM bid.projects"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {order}"
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(sql, params)
            return _dicts(cur.fetchall())


def get_project(project_id: int) -> Optional[dict]:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM bid.projects WHERE id = %s", (project_id,))
            return _dict(cur.fetchone())


def update_project(project_id: int, *, title=None, client=None, region=None,
    category=None, deadline=None, budget=None, source_url=None, status=None) -> None:
    fields: list[str] = []
    params: list[Any] = []
    for col, val in [
        ("title", title), ("client", client), ("region", region),
        ("category", category), ("deadline", deadline), ("budget", budget),
        ("source_url", source_url), ("status", status),
    ]:
        if val is not None:
            fields.append(f"{col} = %s")
            params.append(val)
    if not fields:
        return
    fields.append("updated_at = %s")
    params.append(_now())
    params.append(project_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE bid.projects SET {', '.join(fields)} WHERE id = %s", params)


def update_status(project_id: int, status: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE bid.projects SET status = %s, updated_at = %s WHERE id = %s",
                (status, _now(), project_id),
            )


# --------------------------------------------------------------------------- #
# costs
# --------------------------------------------------------------------------- #
def upsert_cost(project_id, *, estimate_amount, actual_cost, memo=None) -> None:
    profit = None
    profit_rate = None
    if estimate_amount is not None and actual_cost is not None:
        profit = estimate_amount - actual_cost
        if estimate_amount:
            profit_rate = round(actual_cost / estimate_amount * 100, 2)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO bid.costs
                   (project_id, estimate_amount, actual_cost, profit, profit_rate, memo, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(project_id) DO UPDATE SET
                       estimate_amount=EXCLUDED.estimate_amount,
                       actual_cost=EXCLUDED.actual_cost,
                       profit=EXCLUDED.profit,
                       profit_rate=EXCLUDED.profit_rate,
                       memo=EXCLUDED.memo,
                       updated_at=EXCLUDED.updated_at""",
                (project_id, estimate_amount, actual_cost, profit, profit_rate, memo, _now()),
            )


def get_cost(project_id: int) -> Optional[dict]:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM bid.costs WHERE project_id = %s", (project_id,))
            return _dict(cur.fetchone())


# --------------------------------------------------------------------------- #
# competitors
# --------------------------------------------------------------------------- #
def add_competitor(project_id, *, competitor_name, competitor_amount, source=None, memo=None) -> None:
    diff_amount = None
    cost = get_cost(project_id)
    if cost and cost["estimate_amount"] is not None and competitor_amount is not None:
        diff_amount = cost["estimate_amount"] - competitor_amount
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO bid.competitors
                   (project_id, competitor_name, competitor_amount, diff_amount, source, memo)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (project_id, competitor_name, competitor_amount, diff_amount, source, memo),
            )


def list_competitors(project_id: int) -> list[dict]:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT * FROM bid.competitors WHERE project_id = %s ORDER BY id", (project_id,)
            )
            return _dicts(cur.fetchall())


# --------------------------------------------------------------------------- #
# scrape_targets
# --------------------------------------------------------------------------- #
def add_target(name, url, region=None) -> Optional[int]:
    with get_conn() as conn:
        with _cur(conn) as cur:
            try:
                cur.execute(
                    "INSERT INTO bid.scrape_targets (name, url, region, is_active) VALUES (%s,%s,%s,TRUE) RETURNING id",
                    (name, url, region),
                )
                return cur.fetchone()["id"]
            except psycopg2.IntegrityError:
                conn.rollback()
                return None


def list_targets(active_only=False) -> list[dict]:
    sql = "SELECT * FROM bid.scrape_targets"
    if active_only:
        sql += " WHERE is_active = TRUE"
    sql += " ORDER BY id"
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(sql)
            return _dicts(cur.fetchall())


def set_target_active(target_id, active) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE bid.scrape_targets SET is_active = %s WHERE id = %s",
                        (bool(active), target_id))


def delete_target(target_id) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bid.scrape_targets WHERE id = %s", (target_id,))


def mark_target_scraped(target_id) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE bid.scrape_targets SET last_scraped_at = %s WHERE id = %s",
                        (_now(), target_id))


# --------------------------------------------------------------------------- #
# unit_prices
# --------------------------------------------------------------------------- #
def add_unit_price(*, category, item_name, unit, unit_price, memo=None) -> int:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                """INSERT INTO bid.unit_prices (category, item_name, unit, unit_price, memo, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                (category, item_name, unit, unit_price, memo, _now()),
            )
            return cur.fetchone()["id"]


def list_unit_prices() -> list[dict]:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM bid.unit_prices ORDER BY category, item_name")
            return _dicts(cur.fetchall())


# --------------------------------------------------------------------------- #
# qualifications
# --------------------------------------------------------------------------- #
def add_qualification(*, issuer, category=None, grade=None, keisin_score=None,
    total_score=None, vendor_number=None, valid_from=None, valid_until=None,
    application_type=None, application_method=None, memo=None) -> int:
    now = _now()
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                """INSERT INTO bid.qualifications
                   (issuer, category, grade, keisin_score, total_score, vendor_number,
                    valid_from, valid_until, application_type, application_method,
                    renewed, memo, imported_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE,%s,%s,%s) RETURNING id""",
                (issuer, category, grade, keisin_score, total_score, vendor_number,
                 valid_from, valid_until, application_type, application_method, memo, now, now),
            )
            return cur.fetchone()["id"]


def list_qualifications() -> list[dict]:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM bid.qualifications ORDER BY valid_until, issuer")
            return _dicts(cur.fetchall())


def get_qualification(qid) -> Optional[dict]:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM bid.qualifications WHERE id = %s", (qid,))
            return _dict(cur.fetchone())


def mark_qualification_renewed(qid) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE bid.qualifications SET renewed = TRUE, updated_at = %s WHERE id = %s",
                        (_now(), qid))


def unmark_qualification_renewed(qid) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE bid.qualifications SET renewed = FALSE, updated_at = %s WHERE id = %s",
                        (_now(), qid))


def delete_all_qualifications() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bid.qualifications")


def list_qualifications_expiring(within_days) -> list[dict]:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                """SELECT * FROM bid.qualifications
                   WHERE renewed = FALSE
                     AND valid_until IS NOT NULL
                     AND valid_until <= CURRENT_DATE + make_interval(days => %s)
                   ORDER BY valid_until, issuer""",
                (within_days,),
            )
            return _dicts(cur.fetchall())


if __name__ == "__main__":
    init_db()
    print("Database initialized (PostgreSQL)")
