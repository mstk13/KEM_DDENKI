"""全アプリ統一テストデータ投入スクリプト

同じ従業員・現場名を全アプリで使用し、実運用を模したデータを生成する。
Docker環境（PostgreSQL）専用。

Usage:
    python shared/seed_all.py          # 投入
    python shared/seed_all.py --reset  # 全削除してから投入
"""
from __future__ import annotations

import os
import sys
import random
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dbconn import get_conn  # noqa: E402

# =====================================================================
# マスターデータ（全アプリ共通）
# =====================================================================

EMPLOYEES = [
    # code, name, kana, department, position, role, phone
    ("E001", "剣持 太郎",   "けんもち たろう",   "役員",       "代表取締役", "役員",   "090-1111-0001"),
    ("E002", "剣持 花子",   "けんもち はなこ",   "役員",       "取締役",     "役員",   "090-1111-0002"),
    ("E003", "佐藤 健一",   "さとう けんいち",   "電気工事部", "職長",       "電工",   "090-2222-0001"),
    ("E004", "田中 翔太",   "たなか しょうた",   "電気工事部", "主任",       "電工",   "090-2222-0002"),
    ("E005", "鈴木 誠",     "すずき まこと",     "電気工事部", "社員",       "電工",   "090-2222-0003"),
    ("E006", "高橋 健太",   "たかはし けんた",   "電気工事部", "社員",       "電工",   "090-2222-0004"),
    ("E007", "山田 美咲",   "やまだ みさき",     "総務部",     "主任",       "事務",   "090-3333-0001"),
    ("E008", "中村 裕子",   "なかむら ゆうこ",   "総務部",     "社員",       "事務",   "090-3333-0002"),
    ("E009", "伊藤 大輔",   "いとう だいすけ",   "電気工事部", "見習い",     "電工",   "090-2222-0005"),
    ("E010", "渡辺 拓也",   "わたなべ たくや",   "電気工事部", "見習い",     "電工",   "090-2222-0006"),
]

CLIENTS = [
    # name, contact, phone
    ("東京都建設局",         "田村 一郎",   "03-5321-1111"),
    ("埼玉県施設管理公社",   "大野 正",     "048-830-2222"),
    ("川崎市教育委員会",     "木村 隆",     "044-200-3333"),
    ("横浜市建築局",         "小林 由美",   "045-671-4444"),
    ("国土交通省 関東地方整備局", "加藤 誠", "048-600-5555"),
]

SITES = [
    # name, client_index, address, region, category, status, manager
    ("市立第三小学校 電気設備改修工事", 2, "川崎市中原区小杉町1-2",      "神奈川", "電気設備",   "施工中", "佐藤 健一"),
    ("県営住宅A棟 受変電設備更新工事", 1, "さいたま市浦和区高砂3-15",   "埼玉",   "受変電設備", "施工中", "佐藤 健一"),
    ("都営地下鉄 駅務機器電源工事",   0, "東京都港区東新橋1-5-25",     "東京",   "電気設備",   "着工前", "田中 翔太"),
    ("横浜市庁舎 非常用発電機更新工事", 3, "横浜市中区本町6-50-10",     "神奈川", "発電設備",   "完了",   "佐藤 健一"),
    ("関東整備局 河川監視カメラ電源工事", 4, "さいたま市中央区新都心2-1", "埼玉",  "通信設備",   "着工前", "田中 翔太"),
]

SUPPLIERS = [
    # name, contact, category, phone
    ("三和電材株式会社",     "松本 進",   "電材",     "03-3456-7890"),
    ("河村電器産業株式会社", "青木 健",   "分電盤",   "0568-72-1111"),
    ("パナソニック電材",     "西田 真",   "照明・配線", "06-6908-1131"),
    ("古河電工パワーシステムズ", "村田 浩", "ケーブル", "03-3286-3050"),
    ("日東工業株式会社",     "藤井 学",   "キャビネット", "0587-95-6369"),
]

ITEMS = [
    # name, spec, unit, category, standard_price
    ("VVFケーブル",       "2.0mm 2芯",    "m",   "ケーブル",   120),
    ("VVFケーブル",       "1.6mm 3芯",    "m",   "ケーブル",   150),
    ("CVTケーブル",       "38sq",         "m",   "ケーブル",   850),
    ("LED照明器具",       "40W相当 直管",  "台",  "照明",       3500),
    ("LED照明器具",       "20W相当 直管",  "台",  "照明",       2800),
    ("分電盤",           "20回路",        "面",  "盤",         45000),
    ("ブレーカー",       "30A 2P",        "個",  "盤",         1200),
    ("ブレーカー",       "20A 2P",        "個",  "盤",         980),
    ("PF管",             "22mm",          "m",   "配管",       85),
    ("ボックス",         "4方出 深型",    "個",  "配管",       350),
    ("アウトレットボックス", "中型",      "個",  "配管",       180),
    ("コンセント",       "2口 接地付",    "個",  "配線器具",   450),
    ("スイッチ",         "3路 埋込",      "個",  "配線器具",   380),
    ("非常用発電機",     "100kVA",        "台",  "発電",       2800000),
    ("蓄電池",           "200Ah",         "台",  "蓄電",       350000),
]


# =====================================================================
# シード実行
# =====================================================================
def reset_all(conn):
    """全テーブルのデータを削除（逆依存順）"""
    schemas = ["eval", "attend", "sales", "labor", "material", "bid", "master"]
    with conn.cursor() as cur:
        for schema in schemas:
            cur.execute(f"""
                SELECT tablename FROM pg_tables WHERE schemaname = '{schema}'
            """)
            tables = [r[0] for r in cur.fetchall()]
            for t in tables:
                cur.execute(f"TRUNCATE {schema}.{t} CASCADE")
    print("全データを削除しました")


def seed_master(conn):
    """マスターデータ投入"""
    with conn.cursor() as cur:
        # 従業員
        for code, name, kana, dept, pos, role, phone in EMPLOYEES:
            cur.execute("""
                INSERT INTO master.employees (code, name, kana, department, position, role, phone, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (name) DO NOTHING
            """, (code, name, kana, dept, pos, role, phone))
        print(f"  従業員: {len(EMPLOYEES)}名")

        # 顧客
        for name, contact, phone in CLIENTS:
            cur.execute("""
                INSERT INTO master.clients (name, contact, phone, is_active)
                VALUES (%s, %s, %s, TRUE)
                ON CONFLICT DO NOTHING
            """, (name, contact, phone))
        print(f"  顧客: {len(CLIENTS)}社")

        # 現場
        for name, ci, addr, region, cat, status, mgr in SITES:
            cur.execute("SELECT id FROM master.clients OFFSET %s LIMIT 1", (ci,))
            client_row = cur.fetchone()
            client_id = client_row[0] if client_row else None
            cur.execute("""
                INSERT INTO master.sites (name, client, client_id, address, region, category, status, manager)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (name, CLIENTS[ci][0], client_id, addr, region, cat, status, mgr))
        print(f"  現場: {len(SITES)}件")

        # 仕入先
        for name, contact, cat, phone in SUPPLIERS:
            cur.execute("""
                INSERT INTO master.suppliers (name, contact, category, phone, is_active)
                VALUES (%s, %s, %s, %s, TRUE)
                ON CONFLICT DO NOTHING
            """, (name, contact, cat, phone))
        print(f"  仕入先: {len(SUPPLIERS)}社")


def seed_bid(conn):
    """入札案件管理テストデータ"""
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, category, region FROM master.sites ORDER BY id")
        sites = cur.fetchall()

        projects = [
            # site_idx, title, budget, status, estimate, actual
            (0, "市立第三小学校 電気設備改修工事", 15000000, "受注",     14200000, 12800000),
            (1, "県営住宅A棟 受変電設備更新工事",  28000000, "受注",     26500000, None),
            (2, "都営地下鉄 駅務機器電源工事",     8500000,  "見積作成中", None,   None),
            (3, "横浜市庁舎 非常用発電機更新工事",  42000000, "受注",     39800000, 38500000),
            (4, "関東整備局 河川監視カメラ電源工事", 5200000, "新着",      None,    None),
            (None, "都立高校 体育館照明LED化工事",   12000000, "失注",    11500000, None),
            (None, "某マンション 幹線ケーブル更新",  6800000, "検討中",    None,    None),
        ]

        for si, title, budget, status, est, actual in projects:
            site_id = sites[si][0] if si is not None else None
            client = CLIENTS[si][0] if si is not None and si < len(CLIENTS) else "民間顧客"
            region = sites[si][3] if si is not None else "東京"
            category = sites[si][2] if si is not None else "電気設備"
            deadline = date.today() + timedelta(days=random.randint(-30, 60))

            cur.execute("""
                INSERT INTO bid.projects (site_id, title, client, region, category, deadline, budget, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (site_id, title, client, region, category, deadline, budget, status))
            pid = cur.fetchone()[0]

            if est is not None:
                profit = est - actual if actual else None
                rate = round(profit / est * 100, 1) if profit else None
                cur.execute("""
                    INSERT INTO bid.costs (project_id, estimate_amount, actual_cost, profit, profit_rate)
                    VALUES (%s, %s, %s, %s, %s)
                """, (pid, est, actual, profit, rate))

            # 競合データ（受注・失注案件に）
            if status in ("受注", "失注"):
                competitors = [("山本電気工業", random.randint(-500000, 500000)),
                               ("大和電設", random.randint(-300000, 800000))]
                for cname, diff in competitors:
                    cur.execute("""
                        INSERT INTO bid.competitors (project_id, competitor_name, competitor_amount, diff_amount)
                        VALUES (%s, %s, %s, %s)
                    """, (pid, cname, (est or budget) + diff, diff))

        print(f"  入札案件: {len(projects)}件")


def seed_material(conn):
    """材料管理テストデータ"""
    with conn.cursor() as cur:
        # 品目マスタ
        item_ids = []
        for name, spec, unit, cat, price in ITEMS:
            cur.execute("""
                INSERT INTO material.item_master (name, spec, unit, category, standard_price)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            """, (name, spec, unit, cat, price))
            item_ids.append(cur.fetchone()[0])
        print(f"  品目マスタ: {len(ITEMS)}件")

        # 受注現場の見積もり・発注
        cur.execute("SELECT id FROM bid.projects WHERE status = '受注' ORDER BY id")
        projects = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT id FROM master.suppliers ORDER BY id")
        supplier_ids = [r[0] for r in cur.fetchall()]

        for pi, proj_id in enumerate(projects[:2]):
            # 見積もりヘッダー
            cur.execute("""
                INSERT INTO material.estimate_header (project_id, version, total_amount, submitted, created_by)
                VALUES (%s, 1, 0, TRUE, %s) RETURNING id
            """, (proj_id, "山田 美咲"))
            header_id = cur.fetchone()[0]

            total = 0
            selected_items = random.sample(range(len(item_ids)), min(6, len(item_ids)))
            for order, ii in enumerate(selected_items):
                qty = random.randint(5, 100)
                price = ITEMS[ii][4]
                amount = qty * price
                total += amount
                cur.execute("""
                    INSERT INTO material.estimate_line (header_id, item_id, quantity, unit_price, amount, sort_order)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (header_id, item_ids[ii], qty, price, amount, order))

                # 一部発注済み
                if random.random() > 0.3:
                    oqty = random.randint(1, qty)
                    sup = random.choice(supplier_ids)
                    odate = date.today() - timedelta(days=random.randint(5, 60))
                    cur.execute("""
                        INSERT INTO material.orders
                        (project_id, item_id, supplier_id, quantity, unit_price, amount, order_date, orderer, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (proj_id, item_ids[ii], sup, oqty, price, oqty * price, odate, "山田 美咲",
                          random.choice(["発注済", "納品済", "検収済"])))

            cur.execute("UPDATE material.estimate_header SET total_amount = %s WHERE id = %s", (total, header_id))

        print(f"  見積もり・発注: {len(projects[:2])}現場分")


def seed_labor(conn):
    """作業日報テストデータ（30日分）"""
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM master.employees WHERE role = '電工' ORDER BY id")
        workers = cur.fetchall()
        cur.execute("SELECT id, name FROM master.sites WHERE status IN ('施工中', '完了') ORDER BY id")
        sites = cur.fetchall()
        if not workers or not sites:
            print("  作業日報: スキップ（従業員または現場なし）")
            return

        count = 0
        for day_offset in range(30, 0, -1):
            d = date.today() - timedelta(days=day_offset)
            if d.weekday() >= 5:  # 土日スキップ
                continue

            site = random.choice(sites)
            today_workers = random.sample(workers, min(random.randint(2, 4), len(workers)))

            cur.execute("""
                INSERT INTO labor.reports
                (report_date, reporter_name, site_id, client, work_content, manager, status)
                VALUES (%s, %s, %s, %s, %s, %s, '提出済') RETURNING id
            """, (d, today_workers[0][1], site[0], "", "配線工事・器具取付", "佐藤 健一"))
            report_id = cur.fetchone()[0]

            for i, w in enumerate(today_workers):
                start = "08:00"
                end = random.choice(["17:00", "17:30", "18:00", "19:00"])
                overtime = max(0, int(end.split(":")[0]) - 17)
                hours = int(end.split(":")[0]) - 8 - 1  # 1h休憩
                cur.execute("""
                    INSERT INTO labor.report_workers
                    (report_id, worker_id, worker_name, start_time, end_time, overtime_h, work_hours, sort_order)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (report_id, w[0], w[1], start, end, overtime, hours, i))

            # 協力会社（たまに）
            if random.random() > 0.7:
                cur.execute("""
                    INSERT INTO labor.report_subcontractors
                    (report_id, company_name, worker_name, headcount, start_time, end_time, work_content, approved, sort_order)
                    VALUES (%s, %s, %s, %s, '08:00', '17:00', '配管工事', TRUE, 0)
                """, (report_id, "協栄電気工業", "木下 浩二", random.randint(1, 3)))

            count += 1

        # 事務員の日報
        cur.execute("SELECT id, name FROM master.employees WHERE role = '事務' ORDER BY id")
        office_workers = cur.fetchall()
        for day_offset in range(30, 0, -1):
            d = date.today() - timedelta(days=day_offset)
            if d.weekday() >= 5:
                continue
            for ow in office_workers:
                cur.execute("""
                    INSERT INTO labor.office_reports
                    (report_date, worker_id, worker_name, start_time, end_time, work_hours,
                     work_content, role, status)
                    VALUES (%s, %s, %s, '09:00', '18:00', 8, %s, '事務員', '提出済')
                """, (d, ow[0], ow[1], random.choice([
                    "請求書処理・見積書作成",
                    "発注書作成・仕入先連絡",
                    "経費精算・給与計算準備",
                    "資格申請書類作成・提出",
                ])))
            count += len(office_workers)

        print(f"  作業日報: {count}件")


def seed_attend(conn):
    """勤怠管理テストデータ"""
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM master.employees WHERE is_active = TRUE ORDER BY id")
        employees = cur.fetchall()
        cur.execute("SELECT name FROM master.sites ORDER BY id")
        site_names = [r[0] for r in cur.fetchall()]
        if not employees or not site_names:
            print("  勤怠管理: スキップ")
            return

        count = 0
        for day_offset in range(14, 0, -1):
            d = date.today() - timedelta(days=day_offset)
            if d.weekday() >= 5:
                continue

            site = random.choice(site_names)
            cur.execute("""
                INSERT INTO attend.reports (report_date, site_name, work_content, status)
                VALUES (%s, %s, '電気設備工事', '確認済') RETURNING id
            """, (d, site))
            rid = cur.fetchone()[0]

            for emp in random.sample(employees, min(random.randint(3, 6), len(employees))):
                start_h = random.choice([7, 8])
                end_h = random.choice([17, 18, 19])
                brk = 60
                total = (end_h - start_h) * 60 - brk
                normal = min(total, 480)
                overtime = max(0, total - 480)
                early = 60 if start_h < 8 else 0
                cur.execute("""
                    INSERT INTO attend.entries
                    (report_id, employee_id, employee_name, start_time, end_time,
                     break_minutes, early_minutes, normal_minutes, overtime_minutes, total_minutes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (rid, emp[0], emp[1], f"{start_h:02d}:00", f"{end_h:02d}:00",
                      brk, early, normal, overtime, total))
                count += 1

        print(f"  勤怠管理: {count}件")


def seed_sales(conn):
    """営業管理テストデータ"""
    visits = [
        ("電気設備", "三和電材株式会社",     "松本 進",   "電材全般の卸売・技術サポート",   "新製品LED照明の提案", "確認済"),
        ("電気設備", "河村電器産業株式会社", "青木 健",   "分電盤・制御盤の製造販売",       "高効率分電盤の見積提出", "対応中"),
        ("通信",     "NTT東日本",           "野口 慎一", "通信インフラ・光回線",           "現場の通信環境整備の提案", "確認済"),
        ("保険",     "あいおいニッセイ同和", "清水 香織", "建設業向け総合保険",             "工事保険の更新案内", "見送り"),
        ("電気設備", "古河電工パワーシステムズ", "村田 浩", "ケーブル・電力機器",           "CVTケーブル価格改定の案内", "確認済"),
        ("IT",       "サイボウズ株式会社",   "堀 大介",   "グループウェア・業務システム",   "施工管理クラウドの提案", "下書き"),
        ("電気設備", "日東工業株式会社",     "藤井 学",   "キャビネット・配電機器",         "新型キャビネットのカタログ送付", "確認済"),
    ]

    with conn.cursor() as cur:
        for industry, company, rep, overview, content, status in visits:
            vdate = date.today() - timedelta(days=random.randint(1, 90))
            cur.execute("""
                INSERT INTO sales.visits
                (industry, company_name, rep_name, business_overview, sales_content, visit_date, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (industry, company, rep, overview, content, vdate, status))
        print(f"  営業管理: {len(visits)}件")


def seed_eval(conn):
    """人事評価テストデータ"""
    with conn.cursor() as cur:
        # 評価項目がなければスキップ
        cur.execute("SELECT COUNT(*) FROM eval.eval_items")
        if cur.fetchone()[0] == 0:
            print("  人事評価: スキップ（評価項目未登録）")
            return

        cur.execute("SELECT id, section, num, name, max_score FROM eval.eval_items ORDER BY section, sort_order, num")
        all_items = cur.fetchall()

        # 評価対象 = 全従業員
        role_map = {
            "役員": "社長", "代表取締役": "社長", "取締役": "役員",
            "職長": "現場方", "主任": "現場方", "社員": "現場方", "見習い": "現場方",
        }
        # 事務 → 事務方
        eval_targets = []
        for code, name, kana, dept, pos, role, phone in EMPLOYEES:
            if role == "事務":
                erole = "事務方"
            elif role == "役員":
                erole = "社長" if pos == "代表取締役" else "役員"
            else:
                erole = "現場方"
            eval_targets.append((name, erole))

        period = "2025-04-01 〜 2026-03-31"

        evaluators = [
            ("剣持 太郎", "社長"),
            ("佐藤 健一", "現場方"),
        ]

        count = 0
        for emp_name, emp_role in eval_targets:
            for ev_name, ev_role in evaluators:
                # 自己評価 + 他者評価
                is_self = (emp_name == ev_name)
                if not is_self and ev_role not in ("社長", "役員") and emp_role == ev_role:
                    continue  # 同じ役割の他者評価は社長・役員のみ

                common_items = [i for i in all_items if i[1] == "共通"]
                role_items = [i for i in all_items if i[1] == emp_role]
                items_for_eval = common_items + role_items
                if not items_for_eval:
                    continue

                max_total = sum(i[4] for i in items_for_eval)
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                cur.execute("""
                    INSERT INTO eval.evaluations
                    (employee, role, period, evaluator, max_total, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
                """, (emp_name, emp_role, period, ev_name, max_total, now, now))
                eval_id = cur.fetchone()[0]

                for item in items_for_eval:
                    # ランダムスコア（自己評価はやや高め）
                    base = random.uniform(0.5, 0.9) if is_self else random.uniform(0.4, 0.85)
                    score = min(item[4], round(item[4] * base))
                    cur.execute("""
                        INSERT INTO eval.eval_scores
                        (evaluation_id, item_num, item_name, score, comment)
                        VALUES (%s, %s, %s, %s, '')
                    """, (eval_id, item[2], item[3], score))

                count += 1

        print(f"  人事評価: {count}件")


def main():
    reset = "--reset" in sys.argv

    print("=" * 50)
    print("ケンモチ電機 テストデータ投入")
    print("=" * 50)

    with get_conn() as conn:
        if reset:
            reset_all(conn)

        print("\n[1/7] マスターデータ...")
        seed_master(conn)

        print("[2/7] 入札案件管理...")
        seed_bid(conn)

        print("[3/7] 材料管理...")
        seed_material(conn)

        print("[4/7] 作業日報...")
        seed_labor(conn)

        print("[5/7] 勤怠管理...")
        seed_attend(conn)

        print("[6/7] 営業管理...")
        seed_sales(conn)

        print("[7/7] 人事評価...")
        seed_eval(conn)

    print("\n" + "=" * 50)
    print("テストデータ投入完了")
    print("=" * 50)


if __name__ == "__main__":
    main()
