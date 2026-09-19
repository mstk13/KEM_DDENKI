"""運転免許証の取得日・有効期限を入れる（ADR-0101）。

免許証の券面には「交付」年月日と「〇年（令和〇年）〇月〇日まで有効」が必ず載っている。
ところが有効期限は**色の帯に白抜き**で印刷されており、OCR（ADR-0096）が文字として
拾えない。実測でも、期限のある資格証12件のうち読めなかった4件はすべて免許証だった。

そこで免許証だけは、券面を人が読んだ日付をここに置き、資格証が付いているのに
日付が入っていない人へ入れる。交付日を取得日、「〜まで有効」を有効期限とする。

- 入れるのは**空いているところだけ**。既に入っている日付は上書きしない
- 資格証（証明書ファイル）が付いていない資格には入れない。券面を確かめていないため
- 名前は空白・旧字の違いを無視して合わせる（ADR-0068 と同じ）
- ここに無い人は、管理コマンドの報告に「日付がまだ」として出す
"""

import datetime

from apps.workers.certificate_import import name_keys

SOURCE = "資格書一覧の運転免許証（2026-09-18 時点）"

# 氏名 → (交付日, 有効期限)。券面をそのまま読んだ値
LICENSE_DATES = {
    "佐藤　榮一": (datetime.date(2022, 10, 4), datetime.date(2026, 11, 21)),
    "佐野　歩": (datetime.date(2023, 3, 2), datetime.date(2028, 3, 27)),
    "出永　修": (datetime.date(2026, 5, 11), datetime.date(2029, 5, 29)),
    "杉本　和幸": (datetime.date(2025, 2, 10), datetime.date(2030, 4, 9)),
    "梅田　義彦": (datetime.date(2024, 5, 30), datetime.date(2027, 6, 20)),
    "江頭　敏幸": (datetime.date(2022, 6, 1), datetime.date(2027, 7, 24)),
    "片桐　徳男": (datetime.date(2025, 2, 20), datetime.date(2028, 4, 11)),
    "釼持　政宏": (datetime.date(2025, 2, 12), datetime.date(2028, 3, 9)),
    "釼持　陽子": (datetime.date(2026, 7, 7), datetime.date(2029, 8, 3)),
    "釼持　雅崇": (datetime.date(2024, 1, 14), datetime.date(2027, 2, 26)),
    "高橋　章": (datetime.date(2026, 3, 6), datetime.date(2029, 3, 25)),
    "髙橋　昇汰": (datetime.date(2026, 5, 13), datetime.date(2031, 6, 17)),
}

# この語を含む資格名を運転免許証とみなす。
# 取り込みで資格名がファイル名にそろうため（ADR-0097）、
# 「運転免許証」「普通自動車第一種運転免許証」の両方が出てくる。
LICENSE_WORD = "運転免許"

# クレーン・デリック運転士免許証など、車の免許ではないもの
NOT_CAR_LICENSE = ("クレーン", "デリック", "フォークリフト")


def is_car_license(name: str) -> bool:
    """車の運転免許証の資格名かどうか。"""
    if LICENSE_WORD not in (name or ""):
        return False
    return not any(word in name for word in NOT_CAR_LICENSE)


def _dates_for(worker_name):
    keys = name_keys(worker_name)
    for name, dates in LICENSE_DATES.items():
        if name_keys(name) & keys:
            return dates
    return None


def fill_license_dates(company, WorkerQualification, *, apply=True):
    """資格証が付いていて日付が空の運転免許証に、券面の日付を入れる。

    Returns:
        {
          "filled": [(氏名, 資格名, 取得日, 有効期限)],  … 入れた（予定）
          "already": [(氏名, 資格名)],   … 既に日付がある
          "unknown": [(氏名, 資格名)],   … 券面の日付が手元に無い
          "no_file": [(氏名, 資格名)],   … 資格証が付いていない
        }
    """
    report = {"filled": [], "already": [], "unknown": [], "no_file": []}

    # unscoped: 会社を明示して絞る。データ移送・コマンドの両方から呼ぶため
    rows = (
        WorkerQualification._base_manager
        .filter(company=company)
        .select_related("worker")
        .order_by("worker__name", "name")
    )
    for qualification in rows:
        if not is_car_license(qualification.name):
            continue
        worker_name = qualification.worker.name

        if qualification.acquired_date and qualification.expiry_date:
            report["already"].append((worker_name, qualification.name))
            continue
        if not qualification.certificate_image:
            report["no_file"].append((worker_name, qualification.name))
            continue

        dates = _dates_for(worker_name)
        if dates is None:
            report["unknown"].append((worker_name, qualification.name))
            continue

        acquired, expiry = dates
        changed = []
        if not qualification.acquired_date:
            qualification.acquired_date = acquired
            changed.append("acquired_date")
        if not qualification.expiry_date:
            qualification.expiry_date = expiry
            changed.append("expiry_date")
        if not changed:
            report["already"].append((worker_name, qualification.name))
            continue

        report["filled"].append(
            (worker_name, qualification.name, acquired, expiry),
        )
        if apply:
            qualification.save(update_fields=[*changed, "updated_at"])

    return report
