"""全アプリ統一テストデータ投入スクリプト

同じ従業員・現場名を全アプリで使用し、実運用を模したデータを生成する。
Docker環境（PostgreSQL）専用。

Usage:
    python shared/seed_all.py          # 投入
    python shared/seed_all.py --reset  # 全削除してから投入

社長（代表取締役）のログイン番号: 001  → 社員コード E001（人事評価 管理アプリ）
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
    # name, client_index, address, region, category, status, manager, start_date_offset, end_date_offset
    ("市立第三小学校 電気設備改修工事", 2, "川崎市中原区小杉町1-2",      "神奈川", "電気設備",   "施工中", "佐藤 健一", -60, 30),
    ("県営住宅A棟 受変電設備更新工事", 1, "さいたま市浦和区高砂3-15",   "埼玉",   "受変電設備", "施工中", "佐藤 健一", -45, 45),
    ("都営地下鉄 駅務機器電源工事",   0, "東京都港区東新橋1-5-25",     "東京",   "電気設備",   "着工前", "田中 翔太", 14, 90),
    ("横浜市庁舎 非常用発電機更新工事", 3, "横浜市中区本町6-50-10",     "神奈川", "発電設備",   "完了",   "佐藤 健一", -120, -10),
    ("関東整備局 河川監視カメラ電源工事", 4, "さいたま市中央区新都心2-1", "埼玉",  "通信設備",   "着工前", "田中 翔太", 30, 120),
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
    schemas = ["schedule", "eval", "attend", "sales", "labor", "material", "bid", "master"]
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
        today = date.today()
        for name, ci, addr, region, cat, status, mgr, s_off, e_off in SITES:
            cur.execute("SELECT id FROM master.clients OFFSET %s LIMIT 1", (ci,))
            client_row = cur.fetchone()
            client_id = client_row[0] if client_row else None
            start_d = today + timedelta(days=s_off)
            end_d = today + timedelta(days=e_off)
            cur.execute("""
                INSERT INTO master.sites (name, client, client_id, address, region, category, status, manager, start_date, end_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (name, CLIENTS[ci][0], client_id, addr, region, cat, status, mgr, start_d, end_d))
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

        # 入札参加資格
        qualifications = [
            ("東京都",   "電気工事", "A", 780, 1050, "13-012345", -365, 365, "定期", "電子申請"),
            ("神奈川県", "電気工事", "B", 720, 980,  "14-067890", -300, 430, "定期", "電子申請"),
            ("埼玉県",   "電気工事", "B", 710, 960,  "11-034567", -200, 530, "定期", "郵送"),
            ("川崎市",   "電気工事", "A", 750, 1020, "KC-001234", -180, 550, "定期", "持参"),
            ("横浜市",   "電気工事", "B", 700, 940,  "YH-005678", -400, 330, "定期", "電子申請"),
            ("国土交通省 関東地方整備局", "電気工事", "C", 690, 920, "KK-009012", -150, 580, "定期", "電子申請"),
        ]
        for issuer, cat, grade, keisin, total, vendor, vf_off, vu_off, app_type, app_method in qualifications:
            cur.execute("""
                INSERT INTO bid.qualifications
                (issuer, category, grade, keisin_score, total_score, vendor_number,
                 valid_from, valid_until, application_type, application_method, renewed)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (issuer, cat, grade, keisin, total, vendor,
                  date.today() + timedelta(days=vf_off),
                  date.today() + timedelta(days=vu_off),
                  app_type, app_method, True))

        # 単価マスタ
        unit_prices = [
            ("ケーブル", "VVF 2.0-2C", "m", 120),
            ("ケーブル", "VVF 1.6-3C", "m", 150),
            ("ケーブル", "CVT 38sq",   "m", 850),
            ("照明",     "LED直管 40W", "台", 3500),
            ("配管",     "PF管 22",     "m", 85),
            ("配線器具", "コンセント 2口 EET", "個", 450),
            ("人件費",   "電工 1人工", "人日", 22000),
            ("人件費",   "見習い 1人工", "人日", 14000),
        ]
        for cat, item, unit, price in unit_prices:
            cur.execute("""
                INSERT INTO bid.unit_prices (category, item_name, unit, unit_price)
                VALUES (%s, %s, %s, %s)
            """, (cat, item, unit, price))

        print(f"  入札案件: {len(projects)}件 + 資格{len(qualifications)}件 + 単価{len(unit_prices)}件")


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

        order_count = 0
        for pi, proj_id in enumerate(projects[:3]):
            # 見積もりヘッダー
            cur.execute("""
                INSERT INTO material.estimate_header (project_id, version, total_amount, submitted, created_by)
                VALUES (%s, 1, 0, TRUE, %s) RETURNING id
            """, (proj_id, "山田 美咲"))
            header_id = cur.fetchone()[0]

            total = 0
            selected_items = random.sample(range(len(item_ids)), min(8, len(item_ids)))
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
                    order_status = random.choice(["発注済", "納品済", "検収済"])
                    cur.execute("""
                        INSERT INTO material.orders
                        (project_id, item_id, supplier_id, quantity, unit_price, amount, order_date, orderer, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                    """, (proj_id, item_ids[ii], sup, oqty, price, oqty * price, odate, "山田 美咲",
                          order_status))
                    order_id = cur.fetchone()[0]
                    order_count += 1

                    # 発注付帯コスト（輸送費・荷揚費）
                    if random.random() > 0.5:
                        cur.execute("""
                            INSERT INTO material.order_cost (order_id, cost_type, amount, memo)
                            VALUES (%s, %s, %s, %s)
                        """, (order_id, "輸送費", random.choice([3000, 5000, 8000, 12000]), ""))
                    if random.random() > 0.7:
                        cur.execute("""
                            INSERT INTO material.order_cost (order_id, cost_type, amount, memo)
                            VALUES (%s, %s, %s, %s)
                        """, (order_id, "荷揚費", random.choice([5000, 10000, 15000]), ""))

            cur.execute("UPDATE material.estimate_header SET total_amount = %s WHERE id = %s", (total, header_id))

        # 価格履歴（過去6ヶ月分、主要品目のみ）
        ph_count = 0
        for ii in range(min(8, len(item_ids))):
            for month_ago in range(6, 0, -1):
                for sup in random.sample(supplier_ids, min(2, len(supplier_ids))):
                    base_price = ITEMS[ii][4]
                    # 価格変動（±10%）
                    fluctuation = random.uniform(0.90, 1.10)
                    rec_price = int(base_price * fluctuation)
                    rec_date = date.today() - timedelta(days=month_ago * 30 + random.randint(0, 15))
                    cur.execute("""
                        INSERT INTO material.price_history (item_id, supplier_id, unit_price, recorded_date, source)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (item_ids[ii], sup, rec_price, rec_date, "見積回答"))
                    ph_count += 1

        print(f"  見積もり・発注: {len(projects[:3])}現場分 ({order_count}発注) + 価格履歴{ph_count}件")


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

        work_contents = [
            "配線工事・器具取付",
            "幹線ケーブル敷設",
            "分電盤取付・結線",
            "照明器具取付・調整",
            "コンセント・スイッチ取付",
            "受変電設備点検",
            "接地工事",
            "PF管敷設・ボックス取付",
            "竣工検査準備・手直し",
            "搬入・荷揚げ・墨出し",
        ]

        count = 0
        for day_offset in range(30, 0, -1):
            d = date.today() - timedelta(days=day_offset)
            if d.weekday() >= 5:  # 土日スキップ
                continue

            site = random.choice(sites)
            today_workers = random.sample(workers, min(random.randint(2, 5), len(workers)))

            cur.execute("""
                INSERT INTO labor.reports
                (report_date, reporter_name, site_id, client, work_content, manager,
                 own_car, own_car_count, own_transport_cost, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '提出済') RETURNING id
            """, (d, today_workers[0][1], site[0], "",
                  random.choice(work_contents), "佐藤 健一",
                  random.random() > 0.5, random.randint(0, 2), random.choice([0, 500, 800, 1200])))
            report_id = cur.fetchone()[0]

            for i, w in enumerate(today_workers):
                start = random.choice(["07:30", "08:00"])
                end = random.choice(["17:00", "17:30", "18:00", "18:30", "19:00"])
                end_h = int(end.split(":")[0])
                end_m = int(end.split(":")[1])
                start_h = int(start.split(":")[0])
                start_m = int(start.split(":")[1])
                overtime = max(0, (end_h * 60 + end_m) - 17 * 60) / 60
                hours = (end_h * 60 + end_m - start_h * 60 - start_m - 60) / 60  # 1h休憩
                cur.execute("""
                    INSERT INTO labor.report_workers
                    (report_id, worker_id, worker_name, start_time, end_time, overtime_h, work_hours, sort_order)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (report_id, w[0], w[1], start, end, round(overtime, 1), round(hours, 1), i))

            # 協力会社（たまに）
            if random.random() > 0.6:
                sub_companies = [
                    ("協栄電気工業", "木下 浩二"),
                    ("永和設備",     "石川 正樹"),
                    ("三共電設",     "松原 達也"),
                ]
                sub = random.choice(sub_companies)
                cur.execute("""
                    INSERT INTO labor.report_subcontractors
                    (report_id, company_name, worker_name, headcount, start_time, end_time,
                     work_content, transport_car, car_count, transport_cost, approved, sort_order)
                    VALUES (%s, %s, %s, %s, '08:00', '17:00', %s, %s, %s, %s, TRUE, 0)
                """, (report_id, sub[0], sub[1], random.randint(1, 3),
                      random.choice(["配管工事", "ケーブル敷設補助", "搬入作業", "足場組立"]),
                      random.random() > 0.5, random.randint(0, 1), random.choice([0, 500, 1000])))

            count += 1

        # 事務員の日報
        cur.execute("SELECT id, name FROM master.employees WHERE role = '事務' ORDER BY id")
        office_workers = cur.fetchall()
        office_contents = [
            ("請求書処理・見積書作成",     "取引先3社分の請求書を処理。市立三小の追加見積書を作成・提出。"),
            ("発注書作成・仕入先連絡",     "VVFケーブル・LED照明の発注書作成。三和電材へ納期確認の電話。"),
            ("経費精算・給与計算準備",     "今月分の交通費・消耗品の経費精算。タイムカード集計の準備。"),
            ("資格申請書類作成・提出",     "東京都入札参加資格の更新申請書類を作成。電子申請にて提出完了。"),
            ("材料管理システム入力",       "納品分の検収処理。品目マスタの単価更新（三和電材の価格改定反映）。"),
            ("工事保険更新手続き",         "あいおいニッセイの工事保険更新書類を確認・社長印を依頼。"),
            ("入札書類準備・印刷",         "都営地下鉄案件の入札書類一式を準備。積算書・会社概要を印刷。"),
            ("現場写真整理・報告書作成",   "横浜市庁舎の竣工写真を整理。完了報告書のドラフトを作成。"),
        ]
        for day_offset in range(30, 0, -1):
            d = date.today() - timedelta(days=day_offset)
            if d.weekday() >= 5:
                continue
            for ow in office_workers:
                content, detail = random.choice(office_contents)
                end_time = random.choice(["17:30", "18:00", "18:30"])
                end_h = int(end_time.split(":")[0])
                work_h = (end_h * 60 + int(end_time.split(":")[1]) - 9 * 60 - 60) / 60
                cur.execute("""
                    INSERT INTO labor.office_reports
                    (report_date, worker_id, worker_name, start_time, end_time, work_hours,
                     work_content, report_content, role, status)
                    VALUES (%s, %s, %s, '09:00', %s, %s, %s, %s, '事務員', '提出済')
                """, (d, ow[0], ow[1], end_time, round(work_h, 1), content, detail))
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

            for emp in random.sample(employees, min(random.randint(3, 7), len(employees))):
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

        # 勤怠設定
        settings = [
            ("overtime_boundary", "17:00"),
            ("early_boundary", "08:00"),
            ("break_minutes", "60"),
            ("round_minutes", "15"),
        ]
        for key, value in settings:
            cur.execute("""
                INSERT INTO attend.settings (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (key, value))

        print(f"  勤怠管理: {count}件 + 設定{len(settings)}件")


def seed_sales(conn):
    """営業管理テストデータ"""
    visits = [
        ("電気設備", "三和電材株式会社",     "松本 進",   "03-3456-7890", "matsumoto@sanwa-denzai.co.jp",
         "電材全般の卸売・技術サポート",   "新製品LED照明の提案。従来品比30%省エネ。サンプル2台を受領。", "確認済"),
        ("電気設備", "河村電器産業株式会社", "青木 健",   "0568-72-1111", "aoki@kawamura.co.jp",
         "分電盤・制御盤の製造販売",       "高効率分電盤の見積提出。県営住宅A棟向け20回路×8面。納期4週。", "対応中"),
        ("通信",     "NTT東日本",           "野口 慎一", "03-5359-5111", "",
         "通信インフラ・光回線",           "現場の通信環境整備の提案。仮設Wi-Fi+光回線の工事費見積依頼。", "確認済"),
        ("保険",     "あいおいニッセイ同和", "清水 香織", "03-5424-0101", "shimizu@aioi-nd.co.jp",
         "建設業向け総合保険",             "工事保険の更新案内。来年度の保険料試算を依頼。パンフレット受領。", "見送り"),
        ("電気設備", "古河電工パワーシステムズ", "村田 浩", "03-3286-3050", "",
         "ケーブル・電力機器",           "CVTケーブル価格改定の案内。銅価上昇により来月から5%値上げ予定。", "確認済"),
        ("IT",       "サイボウズ株式会社",   "堀 大介",   "03-4306-0808", "hori@cybozu.co.jp",
         "グループウェア・業務システム",   "施工管理クラウドの提案。月額5,000円/ユーザー。30日無料トライアル可。", "下書き"),
        ("電気設備", "日東工業株式会社",     "藤井 学",   "0587-95-6369", "",
         "キャビネット・配電機器",         "新型屋外キャビネット（IP55対応）のカタログ送付。河川監視カメラ案件に適合。", "確認済"),
        ("電気設備", "パナソニック電材",     "西田 真",   "06-6908-1131", "nishida@panasonic-denzai.co.jp",
         "照明・配線器具の製造販売",       "LED照明の一括見積。市立三小向けにVS競合品で20%安い提案。", "確認済"),
        ("通信",     "KDDI株式会社",         "浅野 健",   "03-3347-0077", "",
         "法人向け通信・IoTソリューション", "現場監視カメラのLTE回線提案。月額980円/回線。", "下書き"),
    ]

    with conn.cursor() as cur:
        for industry, company, rep, phone, email, overview, content, status in visits:
            vdate = date.today() - timedelta(days=random.randint(1, 90))
            cur.execute("""
                INSERT INTO sales.visits
                (industry, company_name, rep_name, phone, email, business_overview,
                 sales_content, visit_date, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (industry, company, rep, phone, email, overview, content, vdate, status))
        print(f"  営業管理: {len(visits)}件")


def seed_eval(conn):
    """人事評価テストデータ（アンケート回答含む）"""
    with conn.cursor() as cur:
        # 評価項目がなければスキップ
        cur.execute("SELECT COUNT(*) FROM eval.eval_items")
        if cur.fetchone()[0] == 0:
            print("  人事評価: スキップ（評価項目未登録）")
            return

        cur.execute("SELECT id, section, num, name, max_score FROM eval.eval_items ORDER BY section, sort_order, num")
        all_items = cur.fetchall()

        # 評価対象 = 全従業員
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

        # 評価者: 社長（E001）が全員を評価 + 職長が現場方を評価 + 各自の自己評価
        evaluators = [
            ("剣持 太郎", "社長"),    # E001 = ログイン番号 001
            ("佐藤 健一", "現場方"),
        ]

        # アンケート設問を取得
        cur.execute("""
            SELECT sq.id, sq.item_id, sq.qnum, sq.text, ei.section, ei.name
            FROM eval.survey_questions sq
            JOIN eval.eval_items ei ON ei.id = sq.item_id
            ORDER BY ei.section, ei.sort_order, sq.sort_order
        """)
        survey_questions = cur.fetchall()

        count = 0
        for emp_name, emp_role in eval_targets:
            # 自己評価
            self_items = _create_evaluation(cur, emp_name, emp_role, period, emp_name, all_items, is_self=True)
            if self_items:
                _create_survey_answers(cur, self_items, survey_questions, emp_role, is_self=True)
                count += 1

            # 他者評価
            for ev_name, ev_role in evaluators:
                if emp_name == ev_name:
                    continue  # 自己評価は上で処理済み
                # 社長は全員を評価、職長は現場方のみ
                if ev_role == "現場方" and emp_role not in ("現場方",):
                    continue

                eval_id = _create_evaluation(cur, emp_name, emp_role, period, ev_name, all_items, is_self=False)
                if eval_id:
                    _create_survey_answers(cur, eval_id, survey_questions, emp_role, is_self=False)
                    _create_overall_comments(cur, eval_id, emp_name, ev_name)
                    count += 1

        print(f"  人事評価: {count}件（自己評価+他者評価+アンケート回答）")


def _create_evaluation(cur, emp_name, emp_role, period, ev_name, all_items, is_self):
    """評価レコード1件を作成し、evaluation_idを返す"""
    common_items = [i for i in all_items if i[1] == "共通"]
    role_items = [i for i in all_items if i[1] == emp_role]
    items_for_eval = common_items + role_items
    if not items_for_eval:
        return None

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
        base = random.uniform(0.55, 0.92) if is_self else random.uniform(0.40, 0.88)
        score = min(item[4], max(1, round(item[4] * base)))
        comment = _generate_eval_comment(item[3], score, item[4], is_self)
        cur.execute("""
            INSERT INTO eval.eval_scores
            (evaluation_id, item_num, item_name, score, comment)
            VALUES (%s, %s, %s, %s, %s)
        """, (eval_id, item[2], item[3], score, comment))

    return eval_id


def _generate_eval_comment(item_name, score, max_score, is_self):
    """評価項目に応じた短いコメントを生成"""
    ratio = score / max_score if max_score > 0 else 0
    if ratio >= 0.8:
        comments = {
            "勤怠・規律": "遅刻・欠勤なし。模範的。",
            "コミュニケーション": "報連相が的確で、周囲からの信頼も厚い。",
            "責任感": "最後までやり切る姿勢が見られる。",
            "成長意欲": "資格取得に積極的に取り組んでいる。",
            "施工品質": "手直しがほとんどなく、検査も一発合格。",
            "安全管理": "KY活動を主導し、事故ゼロを維持。",
            "技術力・資格": "幅広い工事に対応でき、後輩からも頼られている。",
            "工程管理": "段取りがよく、工期を守れている。",
            "業務処理の正確性": "ミスが非常に少なく、チェック体制も整っている。",
            "業務効率": "テンプレート化により処理時間を短縮。",
            "経営判断": "適切な判断で受注率向上に貢献。",
        }
    elif ratio >= 0.5:
        comments = {
            "勤怠・規律": "概ね問題ないが、数回の事前連絡遅れあり。",
            "コミュニケーション": "基本的な報連相はできている。",
            "責任感": "指示された業務は期限内に完了。",
            "成長意欲": "会社指定の研修には参加している。",
            "施工品質": "標準的な品質。軽微な手直しあり。",
            "安全管理": "安全ルールは守れている。",
            "技術力・資格": "担当範囲の工事は問題なくこなせる。",
            "工程管理": "指示された工程どおりに進められる。",
            "業務処理の正確性": "通常業務のミスは少ないが、繁忙期に注意。",
            "業務効率": "標準的なスピードで処理できている。",
            "経営判断": "大きな判断ミスはないが、スピードに改善余地。",
        }
    else:
        comments = {
            "勤怠・規律": "遅刻が目立つ。改善が必要。",
            "コミュニケーション": "報告が遅れがち。改善を期待。",
            "責任感": "期限遅れが散見される。",
            "成長意欲": "自主的な学習姿勢が不足。",
            "施工品質": "手直しが多い。基本を見直す必要あり。",
            "安全管理": "保護具の着用忘れあり。注意が必要。",
            "技術力・資格": "補助が必要な場面が多い。",
            "工程管理": "段取り不足で手戻りが発生。",
            "業務処理の正確性": "入力ミスが繰り返されている。",
            "業務効率": "処理スピードの向上が必要。",
            "経営判断": "判断に時間がかかりすぎる場面あり。",
        }

    return comments.get(item_name, "")


def _create_survey_answers(cur, eval_id, survey_questions, emp_role, is_self):
    """アンケート設問への回答を作成"""
    for sq_id, item_id, qnum, text, section, item_name in survey_questions:
        if section not in ("共通", emp_role):
            continue
        # 自己評価はやや高め（3-5）、他者評価は幅広く（1-5）
        if is_self:
            answer = random.choices([3, 4, 5], weights=[30, 45, 25])[0]
        else:
            answer = random.choices([1, 2, 3, 4, 5], weights=[5, 15, 35, 30, 15])[0]
        cur.execute("""
            INSERT INTO eval.eval_answers
            (evaluation_id, item_id, item_name, qnum, question_text, answer)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (eval_id, item_id, item_name, qnum, text, answer))


def _create_overall_comments(cur, eval_id, emp_name, ev_name):
    """総合コメント（A-1〜A-3）を作成（他者評価のみ）"""
    overall_data = {
        "佐藤 健一": {
            "A-1": "1. 施工品質が安定しており手直しがほぼない\n2. 後輩への指導が丁寧で、若手の成長に貢献\n3. 工期管理の見通しが正確",
            "A-2": "1. 書類作成のスピード → 日報を当日中に提出\n2. 新技術への関心 → LED・太陽光の知識を強化\n3. PC操作 → Excel集計を自力でできるように",
            "A-3": "1. 第一種電気工事士の取得\n2. 受持ち現場の全案件で工期遅延ゼロ\n3. 後輩2名を単独作業可能レベルに育成",
        },
        "田中 翔太": {
            "A-1": "1. 段取り力が向上し、材料手配のムダが減った\n2. 協力会社との連携がスムーズ\n3. 安全意識が高く、KY活動を積極的にリード",
            "A-2": "1. 報告タイミング → 問題発生時にもう少し早く上げる\n2. 原価意識 → 材料の使用量を意識する\n3. 図面読解 → 複雑な結線図を自力で読めるように",
            "A-3": "1. 1級電気工事施工管理技士の学科合格\n2. 担当現場の利益率15%以上\n3. ヒヤリハット報告を月1件以上提出",
        },
        "山田 美咲": {
            "A-1": "1. 見積書の精度が高く、顧客からの差し戻しがゼロ\n2. 材料管理システムの運用を軌道に乗せた\n3. 経費精算の効率化（処理時間30%短縮）",
            "A-2": "1. 電気工事の専門知識 → 材料の用途をもう少し理解する\n2. 繁忙期の業務分散 → 前倒しで処理する習慣づけ\n3. AI活用 → ChatGPTを定型文作成に活用する",
            "A-3": "1. 簿記2級の取得\n2. 月次決算の処理時間を2日→1.5日に短縮\n3. 入札書類作成を他の事務員にも引き継げるようマニュアル化",
        },
    }

    if emp_name in overall_data:
        data = overall_data[emp_name]
    else:
        data = {
            "A-1": "1. 担当業務を安定して遂行\n2. チームワークへの貢献\n3. 規律正しい勤務態度",
            "A-2": "1. 報連相のタイミング改善\n2. 自主的な行動の増加\n3. 技術・知識の幅を広げる",
            "A-3": "1. 必要資格の計画的取得\n2. 担当業務の品質向上\n3. 後輩のサポート",
        }

    for qnum, answer_text in data.items():
        cur.execute("""
            INSERT INTO eval.eval_overall
            (evaluation_id, qnum, question_text, answer_text)
            VALUES (%s, %s, %s, %s)
        """, (eval_id, qnum,
              {"A-1": "この1年で最も評価できる成果・貢献を3つ挙げてください",
               "A-2": "改善が必要な点を3つ挙げ、それぞれ具体的にどう変わってほしいかを記入してください",
               "A-3": "次期（1年間）に達成してほしい目標を、測定可能な形で3つ設定してください"}[qnum],
              answer_text))


def seed_schedule(conn):
    """工期管理テストデータ"""
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, status FROM master.sites ORDER BY id")
        sites = cur.fetchall()

        phase_templates = {
            "施工中": [
                ("仮設・搬入",   "#94a3b8", -60, -45, 100),
                ("墨出し・配管", "#3b82f6", -45, -20,  100),
                ("幹線敷設",     "#22c55e", -20,   0,   80),
                ("器具取付",     "#f59e0b",   0,  15,   40),
                ("検査・手直し", "#ef4444",  15,  30,    0),
            ],
            "着工前": [
                ("仮設・搬入",   "#94a3b8",  14,  25,   0),
                ("墨出し・配管", "#3b82f6",  25,  50,   0),
                ("幹線敷設",     "#22c55e",  50,  70,   0),
                ("器具取付",     "#f59e0b",  70,  85,   0),
                ("検査・手直し", "#ef4444",  85,  90,   0),
            ],
            "完了": [
                ("仮設・搬入",     "#94a3b8", -120, -105, 100),
                ("受変電設備撤去", "#dc2626", -105,  -90, 100),
                ("新設備据付",     "#22c55e",  -90,  -50, 100),
                ("試運転・調整",   "#f59e0b",  -50,  -25, 100),
                ("竣工検査",       "#3b82f6",  -25,  -10, 100),
            ],
        }

        milestone_templates = {
            "施工中": [
                ("中間検査", 10, False),
                ("完了検査", 28, False),
                ("引き渡し", 30, False),
            ],
            "着工前": [
                ("着工",     14, False),
                ("中間検査", 60, False),
                ("完了検査", 88, False),
                ("引き渡し", 90, False),
            ],
            "完了": [
                ("中間検査", -50, True),
                ("完了検査", -12, True),
                ("引き渡し", -10, True),
            ],
        }

        today = date.today()
        phase_count = 0
        ms_count = 0

        for site_id, site_name, status in sites:
            phases = phase_templates.get(status, [])
            for name, color, s_off, e_off, progress in phases:
                cur.execute("""
                    INSERT INTO schedule.phases
                    (site_id, name, start_date, end_date, progress, sort_order, color)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (site_id, name, today + timedelta(days=s_off),
                      today + timedelta(days=e_off), progress, phase_count, color))
                phase_count += 1

            milestones = milestone_templates.get(status, [])
            for name, off, completed in milestones:
                cur.execute("""
                    INSERT INTO schedule.milestones
                    (site_id, name, target_date, completed)
                    VALUES (%s, %s, %s, %s)
                """, (site_id, name, today + timedelta(days=off), completed))
                ms_count += 1

        print(f"  工期管理: 工程{phase_count}件 + マイルストーン{ms_count}件")


def main():
    reset = "--reset" in sys.argv

    print("=" * 50)
    print("ケンモチ電機 テストデータ投入")
    print("=" * 50)
    print(f"社長ログイン番号: 001 (社員コード E001 = 剣持 太郎)")
    print()

    with get_conn() as conn:
        if reset:
            reset_all(conn)

        print("[1/8] マスターデータ...")
        seed_master(conn)

        print("[2/8] 入札案件管理...")
        seed_bid(conn)

        print("[3/8] 材料管理...")
        seed_material(conn)

        print("[4/8] 作業日報...")
        seed_labor(conn)

        print("[5/8] 勤怠管理...")
        seed_attend(conn)

        print("[6/8] 営業管理...")
        seed_sales(conn)

        print("[7/8] 人事評価...")
        seed_eval(conn)

        print("[8/8] 工期管理...")
        seed_schedule(conn)

    print("\n" + "=" * 50)
    print("テストデータ投入完了")
    print("=" * 50)


if __name__ == "__main__":
    main()
