#!/usr/bin/env python
"""現行版（Streamlit/Flask）から次期版（Django SaaS）へのデータ移行スクリプト。

使い方:
    # 環境変数で現行版DBの接続情報を指定
    export LEGACY_DB_URL="postgresql://kem:kem@localhost:5433/kem_main"

    # Django環境で実行
    cd saas/
    DJANGO_SETTINGS_MODULE=config.settings python scripts/migrate_legacy_data.py

    # ドライランモード（DBへの書込みなし）
    DJANGO_SETTINGS_MODULE=config.settings python scripts/migrate_legacy_data.py --dry-run

注意:
    - 既存データがある場合、重複チェックして追加のみ行う（既存は上書きしない）
    - マイグレーション前に Django の migrate を実行しておくこと
    - 現行版と次期版で同じ PostgreSQL サーバーを使用している前提
"""

import argparse
import os
import sys

import psycopg2
from psycopg2.extras import RealDictCursor


def get_legacy_conn():
    """現行版DBへの接続を取得する。"""
    url = os.environ.get("LEGACY_DB_URL", "postgresql://kem:kem@localhost:5433/kem_main")
    return psycopg2.connect(url, cursor_factory=RealDictCursor)


def setup_django():
    """Django 環境を初期化する。"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()


def migrate_company(dry_run=False):
    """テナント（会社）を作成する。現行版はシングルテナントなので1社のみ。"""
    from apps.tenants.models import Company
    company, created = Company.objects.get_or_create(
        name="株式会社ケンモチ電機",
        defaults={"industry_type": "電気工事", "is_active": True},
    )
    action = "作成" if created else "既存"
    print(f"  会社: {company.name} ({action})")
    return company


def migrate_employees(conn, company, dry_run=False):
    """master.employees → workers.Worker"""
    from apps.workers.models import Worker

    cur = conn.cursor()
    cur.execute("SELECT * FROM master.employees ORDER BY id")
    rows = cur.fetchall()
    count = 0

    for row in rows:
        if Worker.unscoped.filter(company=company, name=row["name"]).exists():
            continue
        if dry_run:
            print(f"  [DRY] Worker: {row['name']}")
            count += 1
            continue

        Worker.unscoped.create(
            company=company,
            employee_code=row.get("code", ""),
            name=row["name"],
            name_kana=row.get("kana", ""),
            phone=row.get("phone", ""),
            is_active=row.get("is_active", True),
            note=row.get("note", ""),
            hire_date=None,
        )
        count += 1

    print(f"  作業員: {count}件 移行")
    return count


def migrate_clients(conn, company, dry_run=False):
    """master.clients → masters.Customer"""
    from apps.masters.models import Customer

    cur = conn.cursor()
    cur.execute("SELECT * FROM master.clients ORDER BY id")
    rows = cur.fetchall()
    count = 0

    for row in rows:
        code = f"C{row['id']:04d}"
        if Customer.unscoped.filter(company=company, code=code).exists():
            continue
        if dry_run:
            print(f"  [DRY] Customer: {row['name']}")
            count += 1
            continue

        Customer.unscoped.create(
            company=company,
            code=code,
            name=row["name"],
            phone=row.get("phone", ""),
            is_active=row.get("is_active", True),
        )
        count += 1

    print(f"  得意先: {count}件 移行")
    return count


def migrate_suppliers(conn, company, dry_run=False):
    """master.suppliers → masters.Supplier"""
    from apps.masters.models import Supplier

    cur = conn.cursor()
    cur.execute("SELECT * FROM master.suppliers ORDER BY id")
    rows = cur.fetchall()
    count = 0

    for row in rows:
        code = f"S{row['id']:04d}"
        if Supplier.unscoped.filter(company=company, code=code).exists():
            continue
        if dry_run:
            print(f"  [DRY] Supplier: {row['name']}")
            count += 1
            continue

        Supplier.unscoped.create(
            company=company,
            code=code,
            name=row["name"],
            contact_info=row.get("contact", ""),
            phone=row.get("phone", ""),
            is_active=row.get("is_active", True),
        )
        count += 1

    print(f"  仕入先: {count}件 移行")
    return count


def migrate_sites(conn, company, dry_run=False):
    """master.sites → sites.Site"""
    from apps.sites.models import Site

    cur = conn.cursor()
    cur.execute("SELECT * FROM master.sites ORDER BY id")
    rows = cur.fetchall()
    count = 0

    status_map = {
        "着工前": "ordered",
        "施工中": "in_progress",
        "完工": "completed",
        "請求済": "billed",
        "見積中": "estimating",
        "中止": "cancelled",
    }

    for row in rows:
        code = f"SITE-{row['id']:04d}"
        if Site.unscoped.filter(company=company, code=code).exists():
            continue
        if dry_run:
            print(f"  [DRY] Site: {row['name']}")
            count += 1
            continue

        Site.unscoped.create(
            company=company,
            code=code,
            name=row["name"],
            address=row.get("address", ""),
            status=status_map.get(row.get("status", ""), "estimating"),
            start_date=row.get("start_date"),
            end_date=row.get("end_date"),
        )
        count += 1

    print(f"  現場: {count}件 移行")
    return count


def migrate_bid_projects(conn, company, dry_run=False):
    """bid.projects → bids.BidProject"""
    from apps.bids.models import BidProject

    cur = conn.cursor()
    cur.execute("SELECT * FROM bid.projects ORDER BY id")
    rows = cur.fetchall()
    count = 0

    status_map = {
        "新着": "new", "検討中": "considering", "入札済": "bid",
        "落札": "won", "失注": "lost", "見送り": "skipped",
    }

    for row in rows:
        if BidProject.unscoped.filter(company=company, title=row["title"]).exists():
            continue
        if dry_run:
            print(f"  [DRY] BidProject: {row['title']}")
            count += 1
            continue

        BidProject.unscoped.create(
            company=company,
            title=row["title"],
            client=row.get("client", ""),
            region=row.get("region", ""),
            category=row.get("category", ""),
            deadline=row.get("deadline"),
            budget=row.get("budget", 0) or 0,
            source_url=row.get("source_url", ""),
            status=status_map.get(row.get("status", ""), "new"),
        )
        count += 1

    print(f"  入札案件: {count}件 移行")
    return count


def migrate_sales_visits(conn, company, dry_run=False):
    """sales.visits → sales.SalesVisit"""
    from apps.sales.models import SalesVisit

    cur = conn.cursor()
    cur.execute("SELECT * FROM sales.visits ORDER BY id")
    rows = cur.fetchall()
    count = 0

    industry_map = {
        "電材・資材": "electrical", "メーカー・製造": "manufacturer",
        "IT・ソフトウェア": "it_software", "建設・設備": "construction",
        "保険・金融": "insurance", "車両・リース": "vehicle",
        "福利厚生": "welfare", "教育・研修": "education",
        "環境・エネルギー": "environment", "レンタル・リース": "rental",
        "その他": "other",
    }
    status_map = {
        "下書き": "draft", "確認済": "confirmed",
        "対応中": "in_progress", "完了": "done", "見送り": "rejected",
    }

    for row in rows:
        if SalesVisit.unscoped.filter(
            company=company,
            company_name=row.get("company_name", ""),
            visit_date=row.get("visit_date"),
        ).exists():
            continue
        if dry_run:
            print(f"  [DRY] SalesVisit: {row.get('company_name', '')}")
            count += 1
            continue

        SalesVisit.unscoped.create(
            company=company,
            industry=industry_map.get(row.get("industry", ""), "other"),
            company_name=row.get("company_name", ""),
            rep_name=row.get("rep_name", ""),
            business_overview=row.get("business_overview", ""),
            sales_content=row.get("sales_content", ""),
            phone=row.get("phone", ""),
            email=row.get("email", ""),
            website=row.get("website", ""),
            address=row.get("address", ""),
            visit_date=row.get("visit_date"),
            received_date=row.get("received_date"),
            status=status_map.get(row.get("status", ""), "draft"),
            memo=row.get("memo", ""),
        )
        count += 1

    print(f"  営業来訪: {count}件 移行")
    return count


def migrate_schedule_data(conn, company, dry_run=False):
    """schedule.phases/milestones/assignments → schedules.*"""
    from apps.schedules.models import Milestone, Phase
    from apps.sites.models import Site

    cur = conn.cursor()
    count = 0

    # Phases
    cur.execute("SELECT * FROM schedule.phases ORDER BY id")
    for row in cur.fetchall():
        site = Site.unscoped.filter(company=company, code=f"SITE-{row['site_id']:04d}").first()
        if not site:
            continue
        if Phase.unscoped.filter(company=company, site=site, name=row["name"]).exists():
            continue
        if not dry_run:
            Phase.unscoped.create(
                company=company, site=site, name=row["name"],
                start_date=row.get("start_date"), end_date=row.get("end_date"),
                progress=row.get("progress", 0), sort_order=row.get("sort_order", 0),
                color=row.get("color", "#3b82f6"), memo=row.get("memo", ""),
            )
        count += 1

    # Milestones
    cur.execute("SELECT * FROM schedule.milestones ORDER BY id")
    for row in cur.fetchall():
        site = Site.unscoped.filter(company=company, code=f"SITE-{row['site_id']:04d}").first()
        if not site:
            continue
        if Milestone.unscoped.filter(company=company, site=site, name=row["name"]).exists():
            continue
        if not dry_run:
            Milestone.unscoped.create(
                company=company, site=site, name=row["name"],
                target_date=row.get("target_date"),
                completed=row.get("completed", False), memo=row.get("memo", ""),
            )
        count += 1

    print(f"  工期データ: {count}件 移行")
    return count


def main():
    parser = argparse.ArgumentParser(description="現行版→次期版データ移行")
    parser.add_argument("--dry-run", action="store_true", help="ドライラン（書込みなし）")
    args = parser.parse_args()

    setup_django()

    print("=" * 60)
    print("KEM_DDENKI データ移行: 現行版 → Django SaaS")
    if args.dry_run:
        print("*** ドライランモード（DBへの書込みなし）***")
    print("=" * 60)

    conn = get_legacy_conn()

    try:
        company = migrate_company(args.dry_run)
        print()
        print("--- マスタデータ ---")
        migrate_employees(conn, company, args.dry_run)
        migrate_clients(conn, company, args.dry_run)
        migrate_suppliers(conn, company, args.dry_run)
        migrate_sites(conn, company, args.dry_run)
        print()
        print("--- 業務データ ---")
        migrate_bid_projects(conn, company, args.dry_run)
        migrate_sales_visits(conn, company, args.dry_run)
        migrate_schedule_data(conn, company, args.dry_run)
        print()
        print("=" * 60)
        print("移行完了")
        print()
        print("注意: 以下のデータは手動確認が必要です:")
        print("  - 日報データ (labor.*) → 構造が大きく異なるため個別対応")
        print("  - 勤怠データ (attend.*) → 構造が大きく異なるため個別対応")
        print("  - 評価データ (eval.*) → JSONベースのテンプレートに変換が必要")
        print("  - 材料データ (material.*) → 見積・発注構造が異なるため個別対応")
        print("  - 添付ファイル → ファイルパスの変換とコピーが必要")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
