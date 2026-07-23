"""アプリ全体の設定と、勤務時間の区分計算ロジック。

参照元(作業日報)と同じく、運用パラメータはここに集約する。
ただし「規定の時間」は設定画面から変更できるよう DB(settings テーブル)に保存し、
ここでは *初期値* のみを定義する。

勤務時間の区分:
    早朝出勤時間  … 早朝境界時刻(既定 08:00)より前の実働
    通常勤務時間  … 早朝境界〜規定終業時刻の実働(所定労働時間が上限)
    残業時間      … 規定終業時刻以降の実働 + 所定労働時間の超過分
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv 未導入でも動作させる
    pass

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("NIPPOU_DB_PATH", BASE_DIR / "nippou.db"))

COMPANY_NAME = os.getenv("NIPPOU_COMPANY_NAME", "株式会社ケンモチ電機")
APP_TITLE = "作業日報 自動抽出・勤怠管理システム"

WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]

REPORT_STATUSES = ["未確認", "確認済", "承認済", "差戻し"]

DEPARTMENTS = ["電気工事部", "設備部", "工務部", "管理部", "その他"]
POSITIONS = ["社員", "職長", "主任", "係長", "課長", "部長", "役員", "パート", "外注"]

# ---------------------------------------------------------------------------
# 「規定の時間」の初期値(設定画面から変更可)
# ---------------------------------------------------------------------------
DEFAULT_SETTINGS: dict[str, object] = {
    "standard_start": "08:00",   # 規定始業時刻
    "standard_end": "17:00",     # 規定終業時刻
    "early_boundary": "08:00",   # この時刻より前の実働を「早朝出勤」として集計
    "standard_hours": 8.0,       # 1日の所定労働時間(h)
    "break_minutes": 60,         # 休憩時間の既定値(分)。日報に記載が無い場合に使用
    "round_minutes": 0,          # 時刻の丸め単位(分)。0=丸めなし
    "overtime_mode": "clock",    # clock=規定終業以降を残業 / hours=実働が所定超過分を残業
    "auto_register_employee": 1,  # 日報に出た未登録者を自動で社員マスタに追加
}

SETTING_LABELS = {
    "standard_start": "規定始業時刻",
    "standard_end": "規定終業時刻",
    "early_boundary": "早朝出勤の境界時刻",
    "standard_hours": "所定労働時間(h/日)",
    "break_minutes": "既定の休憩時間(分)",
    "round_minutes": "時刻の丸め単位(分)",
    "overtime_mode": "残業の判定方式",
    "auto_register_employee": "未登録社員の自動登録",
}

OVERTIME_MODES = {
    "clock": "時刻基準(規定終業時刻より後を残業)",
    "hours": "実働基準(所定労働時間を超えた分を残業)",
}


# ---------------------------------------------------------------------------
# 時刻ユーティリティ
# ---------------------------------------------------------------------------
def parse_hhmm(value: object) -> int | None:
    """'HH:MM' → 0時からの経過分。不正値は None。"""
    if value is None:
        return None
    s = str(value).strip().replace("：", ":")
    if not s:
        return None
    if ":" not in s:
        if s.isdigit() and len(s) in (3, 4):  # '730' / '1730'
            s = f"{s[:-2]}:{s[-2:]}"
        elif s.isdigit():
            s = f"{s}:00"
        else:
            return None
    head, _, tail = s.partition(":")
    try:
        h, m = int(head), int(tail or 0)
    except ValueError:
        return None
    if not (0 <= h <= 47 and 0 <= m <= 59):
        return None
    return h * 60 + m


def fmt_hhmm(minutes: int | None) -> str:
    """経過分 → 'HH:MM'。24時以降はそのまま(例 25:30)。"""
    if minutes is None:
        return ""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def fmt_hours(minutes: int | float | None) -> float:
    """分 → 時間(小数第2位)。"""
    if not minutes:
        return 0.0
    return round(float(minutes) / 60.0, 2)


def weekday_jp(iso_date: str) -> str:
    """'YYYY-MM-DD' → 曜日(日本語1文字)。不正な入力は空文字。"""
    try:
        y, m, d = (int(x) for x in str(iso_date).split("-"))
        return WEEKDAYS_JP[date(y, m, d).weekday()]
    except (ValueError, AttributeError, IndexError):
        return ""


def _round_start(minutes: int, unit: int) -> int:
    """始業は繰り上げ(会社基準)。"""
    if unit <= 0:
        return minutes
    return ((minutes + unit - 1) // unit) * unit


def _round_end(minutes: int, unit: int) -> int:
    """終業は切り捨て(会社基準)。"""
    if unit <= 0:
        return minutes
    return (minutes // unit) * unit


def _overlap(a1: int, a2: int, b1: int, b2: int) -> int:
    return max(0, min(a2, b2) - max(a1, b1))


# ---------------------------------------------------------------------------
# 勤怠の区分計算(本アプリの中核)
# ---------------------------------------------------------------------------
def calc_attendance(
    start: object,
    end: object,
    break_minutes: object = None,
    settings: dict | None = None,
) -> dict[str, int]:
    """出退勤時刻から 早朝 / 通常 / 残業 の分数を算出する。

    戻り値: {"early", "normal", "overtime", "total", "break", "start", "end"} (分)
    - 日をまたぐ勤務(例 22:00→06:00)にも対応。
    - 休憩は 通常帯 → 残業帯 → 早朝帯 の順に差し引く。
    """
    s = dict(DEFAULT_SETTINGS)
    if settings:
        s.update(settings)

    zero = {"early": 0, "normal": 0, "overtime": 0, "total": 0,
            "break": 0, "start": None, "end": None}

    st_m, en_m = parse_hhmm(start), parse_hhmm(end)
    if st_m is None or en_m is None:
        return zero

    unit = int(s.get("round_minutes") or 0)
    st_m, en_m = _round_start(st_m, unit), _round_end(en_m, unit)
    if en_m <= st_m:  # 日跨ぎ
        en_m += 24 * 60
    if en_m <= st_m:
        return zero

    brk = break_minutes
    if brk is None or str(brk).strip() == "":
        brk = s.get("break_minutes") or 0
    try:
        brk = max(0, int(float(brk)))
    except (TypeError, ValueError):
        brk = 0

    early_b = parse_hhmm(s.get("early_boundary")) or 0
    std_end = parse_hhmm(s.get("standard_end")) or (17 * 60)
    if std_end < early_b:
        std_end = early_b

    # 日次の時間帯を 0/1/2 日目分だけ並べて重なりを取る(日跨ぎ対応)
    early_m = day_m = late_m = 0
    for d in range(0, 3):
        base = d * 24 * 60
        early_m += _overlap(st_m, en_m, base, base + early_b)
        day_m += _overlap(st_m, en_m, base + early_b, base + std_end)
        late_m += _overlap(st_m, en_m, base + std_end, base + 24 * 60)

    # 休憩控除: 通常帯 → 残業帯 → 早朝帯
    rest = brk
    take = min(day_m, rest); day_m -= take; rest -= take
    take = min(late_m, rest); late_m -= take; rest -= take
    take = min(early_m, rest); early_m -= take; rest -= take
    actual_break = brk - rest

    std_min = int(round(float(s.get("standard_hours") or 8.0) * 60))
    if str(s.get("overtime_mode", "clock")) == "hours":
        base_m = day_m + late_m
        normal = min(base_m, std_min)
        overtime = base_m - normal
    else:
        normal = min(day_m, std_min)
        overtime = late_m + max(0, day_m - std_min)

    return {
        "early": int(early_m),
        "normal": int(normal),
        "overtime": int(overtime),
        "total": int(early_m + normal + overtime),
        "break": int(actual_break),
        "start": st_m,
        "end": en_m,
    }
