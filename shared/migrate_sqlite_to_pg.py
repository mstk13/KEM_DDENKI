#!/usr/bin/env python3
"""SQLite → PostgreSQL 移行スクリプト。

既存の SQLite データベース（data/*.db）を読み込み、
PostgreSQL の統合スキーマに投入する。

使い方:
    # スキーマ作成のみ（データ移行なし）
    python migrate_sqlite_to_pg.py --schema-only

    # 全データ移行
    python migrate_sqlite_to_pg.py

    # 特定アプリのみ移行
    python migrate_sqlite_to_pg.py --app bid_manager
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://kem:kem@localhost:5432/kem_ddenki",
)

SCRIPT_DIR = Path(__file__).resolve().parent
SCHEMA_SQL = SCRIPT_DIR / "schema.sql"

DATA_DIR = Path(os.getenv("KEM_DATA_DIR", str(SCRIPT_DIR.parent / "data")))


def get_pg():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn


def get_sqlite(db_name: str):
    path = DATA_DIR / db_name
    if not path.exists():
        print(f"  [skip] {path} が見つかりません")
        return None
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def apply_schema(pg):
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    with pg.cursor() as cur:
        cur.execute(sql)
    pg.commit()
    print("[OK] スキーマ作成完了")


def _rows(sq, table):
    try:
        return [dict(r) for r in sq.execute(f"SELECT * FROM {table}").fetchall()]
    except sqlite3.OperationalError:
        return []


def _insert_batch(pg, table, rows):
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ", ".join(["%s"] * len(cols))
    col_str = ", ".join(cols)
    sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
    with pg.cursor() as cur:
        for row in rows:
            vals = [row[c] for c in cols]
            try:
                cur.execute(sql, vals)
            except Exception as e:
                pg.rollback()
                print(f"  [warn] {table}: {e}")
                return 0
    pg.commit()
    return len(rows)


def _bool(v):
    """SQLite の 0/1 を Python bool に変換。"""
    if v is None:
        return None
    return bool(int(v))


# ==========================================================================
# 各アプリの移行関数
# ==========================================================================

def migrate_bid_manager(pg):
    print("\n--- bid_manager ---")
    sq = get_sqlite("bid_manager.db")
    if not sq:
        return

    # projects
    for r in _rows(sq, "projects"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO bid.projects
                   (id, title, client, region, category, deadline, budget,
                    source_url, status, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (r["id"], r["title"], r.get("client"), r.get("region"),
                 r.get("category"), r.get("deadline"), r.get("budget"),
                 r.get("source_url"), r["status"],
                 r["created_at"], r["updated_at"]),
            )
    pg.commit()
    print("  projects: done")

    # costs
    for r in _rows(sq, "costs"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO bid.costs
                   (id, project_id, estimate_amount, actual_cost, profit, profit_rate, memo, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (r["id"], r["project_id"], r.get("estimate_amount"),
                 r.get("actual_cost"), r.get("profit"), r.get("profit_rate"),
                 r.get("memo"), r["updated_at"]),
            )
    pg.commit()
    print("  costs: done")

    # competitors
    n = _insert_batch(pg, "bid.competitors", _rows(sq, "competitors"))
    print(f"  competitors: {n}")

    # scrape_targets
    for r in _rows(sq, "scrape_targets"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO bid.scrape_targets
                   (id, name, url, region, is_active, last_scraped_at)
                   VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (r["id"], r["name"], r["url"], r.get("region"),
                 _bool(r.get("is_active", 1)), r.get("last_scraped_at")),
            )
    pg.commit()
    print("  scrape_targets: done")

    # unit_prices
    n = _insert_batch(pg, "bid.unit_prices", _rows(sq, "unit_prices"))
    print(f"  unit_prices: {n}")

    # qualifications
    for r in _rows(sq, "qualifications"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO bid.qualifications
                   (id, issuer, category, grade, keisin_score, total_score,
                    vendor_number, valid_from, valid_until, application_type,
                    application_method, renewed, memo, imported_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (r["id"], r["issuer"], r.get("category"), r.get("grade"),
                 r.get("keisin_score"), r.get("total_score"),
                 r.get("vendor_number"), r.get("valid_from"), r.get("valid_until"),
                 r.get("application_type"), r.get("application_method"),
                 _bool(r.get("renewed", 0)), r.get("memo"),
                 r["imported_at"], r["updated_at"]),
            )
    pg.commit()
    print("  qualifications: done")

    # シーケンスをリセット
    _reset_sequences(pg, [
        ("bid.projects", "bid.projects_id_seq"),
        ("bid.costs", "bid.costs_id_seq"),
        ("bid.competitors", "bid.competitors_id_seq"),
        ("bid.scrape_targets", "bid.scrape_targets_id_seq"),
        ("bid.unit_prices", "bid.unit_prices_id_seq"),
        ("bid.qualifications", "bid.qualifications_id_seq"),
    ])

    sq.close()


def migrate_eigyo_kanri(pg):
    print("\n--- eigyo-kanri ---")
    sq = get_sqlite("eigyo_kanri.db")
    if not sq:
        return

    for r in _rows(sq, "visits"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO sales.visits
                   (id, industry, company_name, rep_name, business_overview,
                    sales_content, phone, email, website, address,
                    visit_date, received_date, source_file, status, memo,
                    created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (r["id"], r.get("industry", "その他"),
                 r.get("company_name", ""), r.get("rep_name", ""),
                 r.get("business_overview", ""), r.get("sales_content", ""),
                 r.get("phone", ""), r.get("email", ""),
                 r.get("website", ""), r.get("address", ""),
                 r.get("visit_date"), r.get("received_date"),
                 r.get("source_file", ""), r.get("status", "下書き"),
                 r.get("memo", ""), r["created_at"], r["updated_at"]),
            )
    pg.commit()
    _reset_sequences(pg, [("sales.visits", "sales.visits_id_seq")])
    print("  visits: done")
    sq.close()


def migrate_sagyo_nippou(pg):
    print("\n--- sagyo-nippou ---")
    sq = get_sqlite("sagyo_nippou.db")
    if not sq:
        return

    # workers → master.employees（重複チェック付き）
    for r in _rows(sq, "workers"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO master.employees (name, kana, role, phone, is_active, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (name) DO NOTHING""",
                (r["name"], r.get("kana", ""), r.get("role", ""),
                 r.get("phone", ""), _bool(r.get("is_active", 1)),
                 r["created_at"]),
            )
    pg.commit()
    print("  workers → master.employees: done")

    # clients → master.clients
    for r in _rows(sq, "clients"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO master.clients (name, contact, phone, memo, is_active, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (r["name"], r.get("contact", ""), r.get("phone", ""),
                 r.get("memo", ""), _bool(r.get("is_active", 1)),
                 r["created_at"]),
            )
    pg.commit()
    print("  clients → master.clients: done")

    # sites → master.sites
    for r in _rows(sq, "sites"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO master.sites
                   (id, name, client, address, category, start_date, end_date,
                    status, memo, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (r["id"], r["name"], r.get("client", ""),
                 r.get("address", ""), r.get("category", ""),
                 r.get("start_date"), r.get("end_date"),
                 r.get("status", "着工前"), r.get("memo", ""),
                 r["created_at"]),
            )
    pg.commit()
    print("  sites → master.sites: done")

    # reports
    for r in _rows(sq, "reports"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO labor.reports
                   (id, report_date, reporter_name, site_id, client, work_content,
                    own_car, own_train, own_car_count, own_transport_cost,
                    manager, status, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (r["id"], r["report_date"], r.get("reporter_name"),
                 r["site_id"], r.get("client", ""),
                 r.get("work_content", ""),
                 _bool(r.get("own_car", 0)), _bool(r.get("own_train", 0)),
                 r.get("own_car_count", 0), r.get("own_transport_cost", 0),
                 r.get("manager", ""), r.get("status", "提出済"),
                 r["created_at"], r["updated_at"]),
            )
    pg.commit()
    print("  reports: done")

    # report_workers
    for r in _rows(sq, "report_workers"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO labor.report_workers
                   (id, report_id, worker_name, start_time, end_time,
                    overtime_h, lodging, work_hours, sort_order)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (r["id"], r["report_id"], r["worker_name"],
                 r.get("start_time"), r.get("end_time"),
                 r.get("overtime_h", 0), _bool(r.get("lodging", 0)),
                 r.get("work_hours", 0), r.get("sort_order", 0)),
            )
    pg.commit()
    print("  report_workers: done")

    # report_subcontractors
    for r in _rows(sq, "report_subcontractors"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO labor.report_subcontractors
                   (id, report_id, company_name, worker_name, headcount,
                    start_time, end_time, work_content,
                    transport_car, transport_share, transport_train,
                    car_count, transport_cost, approved, sort_order)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (r["id"], r["report_id"], r["company_name"],
                 r.get("worker_name", ""), r.get("headcount", 0),
                 r.get("start_time"), r.get("end_time"),
                 r.get("work_content", ""),
                 _bool(r.get("transport_car", 0)),
                 _bool(r.get("transport_share", 0)),
                 _bool(r.get("transport_train", 0)),
                 r.get("car_count", 0), r.get("transport_cost", 0),
                 _bool(r.get("approved", 0)), r.get("sort_order", 0)),
            )
    pg.commit()
    print("  report_subcontractors: done")

    # office_reports
    for r in _rows(sq, "office_reports"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO labor.office_reports
                   (id, report_date, worker_name, start_time, end_time,
                    work_hours, work_content, report_content, next_content,
                    role, status, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (r["id"], r["report_date"], r["worker_name"],
                 r.get("start_time"), r.get("end_time"),
                 r.get("work_hours", 0), r.get("work_content", ""),
                 r.get("report_content", ""), r.get("next_content", ""),
                 r.get("role", "事務員"), r.get("status", "提出済"),
                 r["created_at"], r["updated_at"]),
            )
    pg.commit()
    print("  office_reports: done")

    _reset_sequences(pg, [
        ("master.employees", "master.employees_id_seq"),
        ("master.clients", "master.clients_id_seq"),
        ("master.sites", "master.sites_id_seq"),
        ("labor.reports", "labor.reports_id_seq"),
        ("labor.report_workers", "labor.report_workers_id_seq"),
        ("labor.report_subcontractors", "labor.report_subcontractors_id_seq"),
        ("labor.office_reports", "labor.office_reports_id_seq"),
    ])
    sq.close()


def migrate_nippou_kanri(pg):
    print("\n--- nippou-kanri ---")
    sq = get_sqlite("nippou_kanri.db")
    if not sq:
        return

    # employees → master.employees（重複チェック付き）
    for r in _rows(sq, "employees"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO master.employees
                   (name, code, kana, department, position, is_active, note, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (name) DO UPDATE SET
                       code = COALESCE(NULLIF(EXCLUDED.code, ''), master.employees.code),
                       kana = COALESCE(NULLIF(EXCLUDED.kana, ''), master.employees.kana),
                       department = COALESCE(NULLIF(EXCLUDED.department, ''), master.employees.department),
                       position = COALESCE(NULLIF(EXCLUDED.position, ''), master.employees.position)
                """,
                (r["name"], r.get("code", ""), r.get("kana", ""),
                 r.get("department", ""), r.get("position", ""),
                 _bool(r.get("active", 1)), r.get("note", ""),
                 r["created_at"]),
            )
    pg.commit()
    print("  employees → master.employees: done (merged)")

    # reports
    for r in _rows(sq, "reports"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO attend.reports
                   (id, report_date, site_name, work_content, note, status,
                    source_text, source_key, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (r["id"], r["report_date"], r.get("site_name", ""),
                 r.get("work_content", ""), r.get("note", ""),
                 r.get("status", "未確認"), r.get("source_text", ""),
                 r.get("source_key", ""), r["created_at"], r["updated_at"]),
            )
    pg.commit()
    print("  reports: done")

    # entries — employee_id を master.employees に変換
    for r in _rows(sq, "entries"):
        emp_id = None
        emp_name = r.get("employee_name", "")
        if emp_name:
            with pg.cursor() as cur:
                cur.execute("SELECT id FROM master.employees WHERE name = %s", (emp_name,))
                row = cur.fetchone()
                if row:
                    emp_id = row[0]
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO attend.entries
                   (id, report_id, employee_id, employee_name, start_time, end_time,
                    break_minutes, early_minutes, normal_minutes, overtime_minutes,
                    total_minutes, note)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (r["id"], r["report_id"], emp_id, emp_name,
                 r.get("start_time", ""), r.get("end_time", ""),
                 r.get("break_minutes", 0), r.get("early_minutes", 0),
                 r.get("normal_minutes", 0), r.get("overtime_minutes", 0),
                 r.get("total_minutes", 0), r.get("note", "")),
            )
    pg.commit()
    print("  entries: done")

    # settings
    for r in _rows(sq, "settings"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO attend.settings (key, value)
                   VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                (r["key"], r["value"]),
            )
    pg.commit()
    print("  settings: done")

    _reset_sequences(pg, [
        ("attend.reports", "attend.reports_id_seq"),
        ("attend.entries", "attend.entries_id_seq"),
    ])
    sq.close()


def migrate_material_manager(pg):
    print("\n--- material_manager ---")
    sq = get_sqlite("material_manager.db")
    if not sq:
        return

    # item_master
    for r in _rows(sq, "item_master"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO material.item_master
                   (id, name, spec, unit, category, subcategory, standard_price, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (r["id"], r["name"], r.get("spec", ""), r.get("unit", "個"),
                 r.get("category", ""), r.get("subcategory", ""),
                 r.get("standard_price", 0), r.get("updated_at")),
            )
    pg.commit()
    print("  item_master: done")

    # supplier → master.suppliers
    for r in _rows(sq, "supplier"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO master.suppliers
                   (id, name, contact, category, memo, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (r["id"], r["name"], r.get("contact", ""),
                 r.get("category", ""), r.get("memo", ""),
                 r.get("created_at")),
            )
    pg.commit()
    print("  supplier → master.suppliers: done")

    # project — material_manager の project は bid.projects と重複する可能性があるため
    # site_id として master.sites に入れる
    for r in _rows(sq, "project"):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO master.sites
                   (name, client, address, region, category, scale,
                    status, manager, memo, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING
                   RETURNING id""",
                (r["title"], r.get("client", ""), r.get("address", ""),
                 r.get("region", ""), r.get("category", ""),
                 r.get("scale", ""), r.get("status", "施工中"),
                 r.get("manager", ""), r.get("memo", ""),
                 r.get("created_at"), r.get("updated_at")),
            )
    pg.commit()
    print("  project → master.sites: done")

    # estimate_header
    n = _insert_batch(pg, "material.estimate_header",
                      [{k: r[k] for k in dict(r)} for r in _rows(sq, "estimate_header")])
    print(f"  estimate_header: {n}")

    # estimate_line
    n = _insert_batch(pg, "material.estimate_line",
                      [{k: r[k] for k in dict(r)} for r in _rows(sq, "estimate_line")])
    print(f"  estimate_line: {n}")

    # "order" → material.orders
    for r in _rows(sq, '"order"'):
        with pg.cursor() as cur:
            cur.execute(
                """INSERT INTO material.orders
                   (id, project_id, item_id, supplier_id, quantity, unit_price,
                    amount, order_date, orderer, status, memo, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (r["id"], r["project_id"], r["item_id"], r.get("supplier_id"),
                 r["quantity"], r["unit_price"], r["amount"],
                 r["order_date"], r["orderer"], r.get("status", "発注済"),
                 r.get("memo", ""), r.get("created_at")),
            )
    pg.commit()
    print("  orders: done")

    # price_history
    n = _insert_batch(pg, "material.price_history",
                      [{k: r[k] for k in dict(r)} for r in _rows(sq, "price_history")])
    print(f"  price_history: {n}")

    # order_cost
    n = _insert_batch(pg, "material.order_cost",
                      [{k: r[k] for k in dict(r)} for r in _rows(sq, "order_cost")])
    print(f"  order_cost: {n}")

    # receipt
    n = _insert_batch(pg, "material.receipt",
                      [{k: r[k] for k in dict(r)} for r in _rows(sq, "receipt")])
    print(f"  receipt: {n}")

    _reset_sequences(pg, [
        ("material.item_master", "material.item_master_id_seq"),
        ("master.suppliers", "master.suppliers_id_seq"),
        ("material.estimate_header", "material.estimate_header_id_seq"),
        ("material.estimate_line", "material.estimate_line_id_seq"),
        ("material.orders", "material.orders_id_seq"),
        ("material.price_history", "material.price_history_id_seq"),
        ("material.order_cost", "material.order_cost_id_seq"),
        ("material.receipt", "material.receipt_id_seq"),
    ])
    sq.close()


def migrate_evaluation(pg):
    print("\n--- evaluation ---")
    sq = get_sqlite("evaluation.db")
    if not sq:
        return

    for table, pg_table in [
        ("eval_items", "eval.eval_items"),
        ("survey_questions", "eval.survey_questions"),
        ("evaluations", "eval.evaluations"),
        ("eval_scores", "eval.eval_scores"),
        ("eval_answers", "eval.eval_answers"),
        ("eval_overall", "eval.eval_overall"),
    ]:
        rows = _rows(sq, table)
        if not rows:
            print(f"  {table}: 0 rows")
            continue
        # eval_items に anchor_* 列があるか確認
        for r in rows:
            # submitted を bool に変換
            if "submitted" in r:
                r["submitted"] = _bool(r["submitted"])
        n = _insert_batch(pg, pg_table, rows)
        print(f"  {table}: {n}")

    _reset_sequences(pg, [
        ("eval.eval_items", "eval.eval_items_id_seq"),
        ("eval.survey_questions", "eval.survey_questions_id_seq"),
        ("eval.evaluations", "eval.evaluations_id_seq"),
        ("eval.eval_scores", "eval.eval_scores_id_seq"),
        ("eval.eval_answers", "eval.eval_answers_id_seq"),
        ("eval.eval_overall", "eval.eval_overall_id_seq"),
    ])
    sq.close()


def _reset_sequences(pg, pairs):
    """SERIAL シーケンスを現在の最大IDにリセット。"""
    for table, seq in pairs:
        try:
            with pg.cursor() as cur:
                cur.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}")
                max_id = cur.fetchone()[0]
                if max_id > 0:
                    cur.execute(f"SELECT setval('{seq}', %s)", (max_id,))
            pg.commit()
        except Exception:
            pg.rollback()


APP_MIGRATORS = {
    "bid_manager": migrate_bid_manager,
    "eigyo_kanri": migrate_eigyo_kanri,
    "sagyo_nippou": migrate_sagyo_nippou,
    "nippou_kanri": migrate_nippou_kanri,
    "material_manager": migrate_material_manager,
    "evaluation": migrate_evaluation,
}


def main():
    parser = argparse.ArgumentParser(description="SQLite → PostgreSQL 移行")
    parser.add_argument("--schema-only", action="store_true",
                        help="スキーマ作成のみ（データ移行なし）")
    parser.add_argument("--app", choices=list(APP_MIGRATORS.keys()),
                        help="特定アプリのみ移行")
    args = parser.parse_args()

    pg = get_pg()
    apply_schema(pg)

    if args.schema_only:
        pg.close()
        return

    if args.app:
        APP_MIGRATORS[args.app](pg)
    else:
        # sagyo-nippou を先に（master テーブルに投入するため）
        migrate_sagyo_nippou(pg)
        migrate_nippou_kanri(pg)
        migrate_bid_manager(pg)
        migrate_material_manager(pg)
        migrate_eigyo_kanri(pg)
        migrate_evaluation(pg)

    pg.close()
    print("\n[完了] 移行が完了しました。")


if __name__ == "__main__":
    main()
