"""日報で使う所定の始業・終業（ADR-0055）。

日報を書くときの開始・終了の初期値と、作業時間だけの日報を PDF に書くときの
範囲の割り出し（ADR-0054）で使う。

- 会社の勤怠設定（AttendSettings）に standard_start / standard_end が **保存されていれば** その時刻
- 保存が無い、または読めない値なら 8:30 / 17:30

勤怠の計算そのもの（AttendSettings.DEFAULTS の 08:00〜17:00）は変えない。
日報では現場の実際の始業に合わせて 8:30〜17:30 を基準にする（要望。2026-09-14）。
"""

import datetime

REPORT_DEFAULT_START = datetime.time(8, 30)
REPORT_DEFAULT_END = datetime.time(17, 30)


def _parse_time(value):
    """「08:30」「8:30」を time にする。読めなければ None。"""
    try:
        hour, minute = (int(x) for x in str(value).strip().split(":")[:2])
        return datetime.time(hour, minute)
    except (ValueError, TypeError):
        return None


def standard_work_times(company):
    """(所定始業, 所定終業) を返す。company は会社か会社の ID。"""
    from apps.attendance.models import AttendSettings

    company_id = getattr(company, "pk", company)
    if not company_id:
        return REPORT_DEFAULT_START, REPORT_DEFAULT_END
    # unscoped: 会社を引数で受けて明示的に絞る（PDF はリクエストの会社と同じだが、
    # 管理コマンドなどリクエスト外からも呼べるようにする）
    saved = dict(
        AttendSettings.unscoped.filter(
            company_id=company_id, key__in=("standard_start", "standard_end"),
        ).values_list("key", "value")
    )
    start = _parse_time(saved.get("standard_start")) or REPORT_DEFAULT_START
    end = _parse_time(saved.get("standard_end")) or REPORT_DEFAULT_END
    return start, end
