"""デモデータ投入（用紙準拠の1枚型: 1現場×1日で複数作業員＋協力会社）。

    python seed.py          # DB初期化 + デモデータ投入（既存があれば確認）
    python seed.py --force  # 既存データを消してから投入
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

import database as db


# (氏名, 役職, 電話, よみがな)
WORKERS = [
    ("剣持 大輔", "職長", "090-1111-2222", "けんもちだいすけ"),
    ("佐藤 健一", "電工", "090-3333-4444", "さとうけんいち"),
    ("鈴木 誠", "電工", "090-5555-6666", "すずきまこと"),
    ("田中 翔", "見習い", "090-7777-8888", "たなかしょう"),
]

SITES = [
    ("〇〇ビル 電気設備更新", "大手不動産(株)", "東京都新宿区", "電気設備", "施工中"),
    ("△△工場 受変電改修", "△△製造(株)", "神奈川県川崎市", "受変電設備", "施工中"),
    ("市立□□小学校 照明LED化", "□□市教育委員会", "埼玉県さいたま市", "照明設備", "着工前"),
    ("××マンション 幹線改修", "××管理組合", "東京都世田谷区", "配線工事", "完了"),
]

CONTENTS = [
    "1階分電盤の更新作業。既設撤去後、新盤据付・結線まで完了。使用材料: VVFケーブル2.0-3C 50m、分電盤1面。",
    "2階天井配線ルート確認とケーブル敷設 約120m。使用材料: CVケーブル、Fケーブル。",
    "受変電キュービクル内部点検、端子増し締め。使用材料: 圧着端子一式。",
    "照明器具のLED化 3教室分の器具交換と点灯試験。使用材料: LEDベースライト12台。",
    "幹線ケーブルの引替え作業 CV38sq×3条。使用材料: CV38sq 80m、ケーブルラック。",
]

SUBS = [
    ("山田電設(株)", "山田・高橋", 2, "配線補助・材料運搬", 3000),
    ("(有)関東テック", "小林", 1, "計装配線", 0),
]


def _clear() -> None:
    with db.get_conn() as conn:
        for t in ("report_subcontractors", "report_workers", "reports", "sites", "workers"):
            conn.execute(f"DELETE FROM {t}")
            conn.execute(f"DELETE FROM sqlite_sequence WHERE name = '{t}'")


def seed(force: bool = False) -> None:
    db.init_db()
    with db.get_conn() as conn:
        existing = conn.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"]
    if existing and not force:
        print(f"既にデータがあります（日報 {existing} 枚）。上書きは --force を付けてください。")
        return
    if force:
        _clear()

    for w in WORKERS:
        db.add_worker(*w)
    worker_names = [w[0] for w in WORKERS]
    site_ids = []
    for i, (name, client, addr, cat, status) in enumerate(SITES):
        start = (date.today() - timedelta(days=30 - i * 5)).isoformat()
        end = (date.today() + timedelta(days=30 + i * 10)).isoformat()
        site_ids.append(db.add_site(name, client, addr, cat, start_date=start,
                                    end_date=end, status=status))

    today = date.today()
    n = 0
    for d in range(21):
        day = today - timedelta(days=d)
        if day.weekday() == 6:  # 日曜休み
            continue
        # その日ごとに稼働中の現場を1〜2枚
        for site_idx in {(d) % 3, (d + 1) % 3}:
            site_id = site_ids[site_idx]
            # 自社作業員（2〜3名）
            members = worker_names[: 2 + (d % 2) + (0 if site_idx else 1)]
            members = members[:4]
            workers = []
            for wi, wname in enumerate(members):
                overtime = 2.0 if (d + wi) % 5 == 0 else 0.0
                end_t = "19:00" if overtime else "17:00"
                workers.append({
                    "worker_name": wname, "start_time": "08:00", "end_time": end_t,
                    "overtime_h": overtime, "lodging": (d % 7 == 0 and wi == 0),
                })
            # 協力会社（3日に1回程度）
            subs = []
            if d % 3 == 0:
                comp, wn, hc, wc, cost = SUBS[site_idx % len(SUBS)]
                subs = [{
                    "company_name": comp, "worker_name": wn, "headcount": hc,
                    "start_time": "08:30", "end_time": "17:00", "work_content": wc,
                    "transport_car": True, "transport_share": False, "transport_train": False,
                    "car_count": 1, "transport_cost": cost, "approved": d > 3,
                }]
            db.add_report(
                report_date=day.isoformat(), site_id=site_id,
                client=SITES[site_idx][1],
                work_content=CONTENTS[(d + site_idx) % len(CONTENTS)],
                own_car=True, own_train=False, own_car_count=1,
                own_transport_cost=1500 + (d % 3) * 500,
                manager=worker_names[0], status="承認済" if d > 2 else "提出済",
                workers=workers, subcontractors=subs,
            )
            n += 1

    print(f"デモデータを投入しました: 作業員{len(WORKERS)}名 / 現場{len(site_ids)}件 / 日報{n}枚")
    print(f"DB: {db.config.DB_PATH}")


if __name__ == "__main__":
    seed(force="--force" in sys.argv)
