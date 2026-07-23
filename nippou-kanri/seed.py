"""デモデータ投入スクリプト。

    py -3 seed.py          … 既存データを残したままデモデータを追加
    py -3 seed.py --reset  … 日報・勤怠・社員を全削除してから投入
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta

import config
import database as db
import extractor

EMPLOYEES = [
    ("E001", "田中 太郎", "タナカタロウ", "電気工事部", "職長"),
    ("E002", "佐藤 花子", "サトウハナコ", "電気工事部", "社員"),
    ("E003", "鈴木 一郎", "スズキイチロウ", "設備部", "主任"),
    ("E004", "高橋 健二", "タカハシケンジ", "電気工事部", "社員"),
    ("E005", "伊藤 美咲", "イトウミサキ", "工務部", "社員"),
    ("E006", "渡辺 大輔", "ワタナベダイスケ", "設備部", "社員"),
]

SITES = [
    ("A様邸 新築工事", "1F配線工事、分電盤取付"),
    ("B工場 改修工事", "動力盤更新、ケーブル敷設"),
    ("C商業ビル 電気設備", "照明器具交換、非常灯点検"),
    ("D倉庫 LED化工事", "高天井LED取付、既存撤去"),
    ("E市役所 受変電点検", "キュービクル年次点検"),
]

# 素の日報テキスト(自動抽出のデモ用)
SAMPLE_TEXT = """
2026/07/21(火) 現場: A様邸 新築工事
作業内容: 1F配線工事、分電盤取付
田中 太郎 7:30〜19:00 休憩60分
佐藤 花子 出勤 8:00 退勤 17:00
備考: 材料追加発注あり

---
7月22日 現場:B工場 改修工事
作業員: 田中 太郎、鈴木 一郎
6:00-20:30 休憩1時間
作業内容: 動力盤更新
"""


def reset() -> None:
    with db.get_conn() as conn:
        conn.execute("DELETE FROM entries")
        conn.execute("DELETE FROM reports")
        conn.execute("DELETE FROM employees")
    print("既存データを削除しました。")


def main() -> None:
    db.init_db()
    if "--reset" in sys.argv:
        reset()

    settings = db.get_settings()
    for code, name, kana, dept, pos in EMPLOYEES:
        db.add_employee(name=name, code=code, kana=kana, department=dept, position=pos)
    print(f"社員 {len(EMPLOYEES)} 名を登録しました。")

    rng = random.Random(20260723)
    names = [e[1] for e in EMPLOYEES]
    today = date.today()
    reports = 0

    for offset in range(45, 0, -1):
        day = today - timedelta(days=offset)
        if day.weekday() == 6:  # 日曜は休み
            continue
        site, content = rng.choice(SITES)
        crew = rng.sample(names, rng.choice([2, 2, 3, 4]))
        entries = []
        for name in crew:
            early = rng.random() < 0.25          # 25% の確率で早朝出勤
            late = rng.random() < 0.45           # 45% の確率で残業
            start = rng.choice(["05:30", "06:00", "06:30", "07:00"]) if early else \
                rng.choice(["07:50", "08:00", "08:00", "08:10"])
            end = rng.choice(["18:00", "19:00", "19:30", "20:30", "21:00"]) if late else \
                rng.choice(["16:30", "17:00", "17:00", "17:15"])
            entries.append({
                "employee_id": db.get_employee_by_name(name)["id"],
                "employee_name": name,
                "start_time": start,
                "end_time": end,
                "break_minutes": rng.choice([60, 60, 60, 75, 90]),
            })
        db.add_report(report_date=day.isoformat(), site_name=site, work_content=content,
                      status=rng.choice(["確認済", "確認済", "承認済", "未確認"]),
                      entries=entries, settings=settings)
        reports += 1

    # 自動抽出の実演: 生テキストから登録
    for block in extractor.extract(SAMPLE_TEXT):
        items = []
        for e in block["entries"]:
            emp = db.get_employee_by_name(e["name"])
            items.append({
                "employee_id": emp["id"] if emp else db.add_employee(name=e["name"]),
                "employee_name": e["name"],
                "start_time": e["start"],
                "end_time": e["end"],
                "break_minutes": e["break_minutes"],
            })
        if items and block["date"]:
            db.add_report(report_date=block["date"], site_name=block["site"],
                          work_content=block["content"], note=block["note"],
                          source_text=block["raw"], entries=items, settings=settings)
            reports += 1

    db.link_entries_to_employees()
    print(f"日報 {reports} 件を登録しました。 DB: {config.DB_PATH}")


if __name__ == "__main__":
    main()
