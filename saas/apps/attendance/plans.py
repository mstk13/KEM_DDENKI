"""出社予定の画面データを組み立てる。

予定が入っていない日は AttendPlan の行を作らない。未定はマスを空にして表す。

入力の向きは2つある。どちらも同じ AttendPlan を読み書きする。

  * 月グリッド（build_plan_board） … 「行＝作業員 × 列＝日」。1人の1ヶ月を横に見る。
    人繰りの全体像と、月をまたいだ偏りを見るための画面。
  * 日シート（build_day_sheet）   … 1日を固定して全員を縦に並べる。
    「明日は誰がどこへ行くか」を朝礼前に一度に埋めるための画面。

月グリッドだけだと、1日ぶんを全員に入れるのに列を目で追うことになる。
日シートだけだと、1人の月の偏り（出張が続く等）が見えない。両方要る。

もう1つ、build_day_timeline は入力ではなく確認用。1日を24時間の横軸にして、
誰がいつどこにいるかを帯で見せる。月グリッドは「その日に出るか」までしか
分からず、朝と午後で現場が違うといった時間の重なりが読めないため。
"""
from __future__ import annotations

import calendar
import datetime

from django.utils import timezone

from apps.attendance.models import AttendPlan, format_time_range

# 曜日の表示。date.weekday() の 0=月 に合わせる。
WEEKDAY_LABELS = ("月", "火", "水", "木", "金", "土", "日")

# まとめて記入の対象。曜日は date.weekday() の値をそのまま文字列で使う。
# "dates" は画面のカレンダーで選んだ日だけを対象にする（日付は別パラメータで受ける）。
FILL_TARGET_DATES = "dates"
FILL_TARGETS = (
    ("weekday", "平日（月〜金）"),
    ("all", "毎日"),
    *((str(i), f"{label}曜日") for i, label in enumerate(WEEKDAY_LABELS)),
    (FILL_TARGET_DATES, "日付を選ぶ"),
)


def month_days(year: int, month: int) -> list[datetime.date]:
    """その月の日を並べて返す。"""
    last = calendar.monthrange(year, month)[1]
    return [datetime.date(year, month, d) for d in range(1, last + 1)]


def fill_days(
    year: int, month: int, target: str, picked: list[str] | None = None,
) -> list[datetime.date]:
    """まとめて記入の対象日を返す。

    「同じ曜日をまとめて」を扱うため、平日・毎日と並べて曜日そのものも
    指定できるようにしている（"0"=月曜 … "6"=日曜）。
    読めない指定は平日として扱う。

    target が "dates" のときは、カレンダーで選んだ日（picked、"YYYY-MM-DD"）だけを
    対象にする。曜日で決まらない飛び飛びの日（棚卸しの日、社内行事など）を
    1回で埋めるため。月の外の日や読めない値は捨て、重複は1つにする。
    何も残らなければ空リストを返す（呼び出し側でエラーにする）。
    """
    days = month_days(year, month)
    if target == FILL_TARGET_DATES:
        in_month = set(days)
        chosen = set()
        for value in picked or ():
            try:
                day = datetime.date.fromisoformat((value or "").strip())
            except ValueError:
                continue
            if day in in_month:
                chosen.add(day)
        return sorted(chosen)
    if target == "all":
        return days
    if target.isdigit() and 0 <= int(target) <= 6:
        return [d for d in days if d.weekday() == int(target)]
    return [d for d in days if d.weekday() < 5]


def parse_date(value: str) -> datetime.date:
    """"YYYY-MM-DD" を date にする。読めなければ今日。"""
    try:
        return datetime.date.fromisoformat((value or "").strip())
    except ValueError:
        return timezone.localdate()


def parse_month(value: str) -> tuple[int, int]:
    """"YYYY-MM" を (年, 月) にする。読めなければ今月。"""
    today = timezone.localdate()
    if not value:
        return today.year, today.month
    try:
        year, month = value.split("-")
        year, month = int(year), int(month)
        datetime.date(year, month, 1)
    except (ValueError, TypeError):
        return today.year, today.month
    return year, month


def shift_month(year: int, month: int, delta: int) -> str:
    """前月・翌月の "YYYY-MM" を返す。"""
    total = year * 12 + (month - 1) + delta
    return f"{total // 12}-{total % 12 + 1:02d}"


def _workers(company):
    """予定表に並べる作業員。在籍中のみ、社員番号→氏名の順。"""
    from apps.workers.models import Worker

    # unscoped: この関数はリクエスト外（管理コマンド・将来のAPI）からも呼べるよう、
    # company を引数で受けて明示的に絞る。apps/schedules/services.py と同じ方針。
    return Worker.unscoped.filter(company=company, is_active=True).order_by(
        "employee_code", "name",
    )


# 「場所・メモ」の候補に出す現場の状態（ADR-0037）。この順に並べる。
# 完工・請求済・中止の現場へ行く予定を立てることは無いので候補に出さない。
SUGGESTED_SITE_STATUSES = ("in_progress", "ordered", "estimating")


def site_name_suggestions(company) -> list[str]:
    """出社予定の「場所・メモ」に候補として出す現場名（ADR-0037）。

    施工中 → 受注済 → 見積中の順、同じ状態の中は現場名順。同じ名前は1つにまとめる。
    候補は入力の手助けで、候補にない行き先もそのまま保存できる（note は自由入力のまま）。
    候補から選ぶと現場名と一字一句同じになるので、ホームの現場カードの参加者
    （ADR-0036 の行き先と現場名の突き合わせ）にも確実に載る。
    """
    from apps.sites.models import Site

    rank = {status: i for i, status in enumerate(SUGGESTED_SITE_STATUSES)}
    # unscoped: _workers と同じく company を引数で受けて明示的に絞る。
    rows = Site.unscoped.filter(
        company=company, status__in=SUGGESTED_SITE_STATUSES,
    ).values_list("name", "status")

    names = []
    seen = set()
    for name, _status in sorted(rows, key=lambda row: (rank[row[1]], row[0])):
        name = name.strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def build_plan_board(company, year: int, month: int) -> dict:
    """月の出社予定表を組み立てる。

    Returns:
        {
          "days": [{"date", "day", "weekday", "is_weekend", "is_today"}, ...],
          "rows": [{"worker", "cells": [...], "working_days"}, ...],
          "daily_totals": [{"date", "count"}, ...],  # days と同じ並び
          "year", "month", "month_str", "prev_month", "next_month",
        }
    """
    days = month_days(year, month)
    today = timezone.localdate()

    day_info = [
        {
            "date": d,
            "day": d.day,
            "weekday": WEEKDAY_LABELS[d.weekday()],
            # 土日で色を変えるので、まとめて weekend にせず個別に持つ
            "is_saturday": d.weekday() == 5,
            "is_sunday": d.weekday() == 6,
            "is_weekend": d.weekday() >= 5,
            "is_today": d == today,
        }
        for d in days
    ]

    workers = list(_workers(company))
    # unscoped: 上と同じ理由。company で明示的に絞る。
    plans = AttendPlan.unscoped.filter(
        company=company,
        plan_date__gte=days[0],
        plan_date__lte=days[-1],
    )
    by_worker_date = {(p.worker_id, p.plan_date): p for p in plans}

    labels = dict(AttendPlan.Kind.choices)
    rows = []
    totals = [0] * len(days)

    for worker in workers:
        cells = []
        working_days = 0
        for index, info in enumerate(day_info):
            plan = by_worker_date.get((worker.pk, info["date"]))
            is_working = bool(plan and plan.is_working)
            if is_working:
                working_days += 1
                totals[index] += 1
            cells.append({
                "date": info["date"],
                "weekday": info["weekday"],
                "kind": plan.kind if plan else "",
                "label": labels.get(plan.kind, "") if plan else "",
                "short": plan.short_label if plan else "",
                "note": plan.note if plan else "",
                "start_time": plan.start_time if plan else None,
                "end_time": plan.end_time if plan else None,
                "time_label": (
                    format_time_range(plan.start_time, plan.end_time) if plan else ""
                ),
                "is_working": is_working,
                "is_saturday": info["is_saturday"],
                "is_sunday": info["is_sunday"],
                "is_weekend": info["is_weekend"],
                "is_today": info["is_today"],
            })
        rows.append({
            "worker": worker,
            "cells": cells,
            "working_days": working_days,
        })

    return {
        "days": day_info,
        "rows": rows,
        "daily_totals": [
            {"date": info["date"], "count": count}
            for info, count in zip(day_info, totals, strict=True)
        ],
        # まとめて記入のミニカレンダー用。月曜始まりで1日の前に空けるマスの数。
        "lead_blanks": range(days[0].weekday()),
        "year": year,
        "month": month,
        "month_str": f"{year}-{month:02d}",
        "prev_month": shift_month(year, month, -1),
        "next_month": shift_month(year, month, 1),
    }


def build_day_sheet(company, day: datetime.date) -> dict:
    """1日ぶんの予定シートを組み立てる。

    予定が無い作業員も行として並べる。月グリッドと違い、この画面は
    「その日の全員ぶんを埋める」ためのものなので、空欄も見えている必要がある。

    Returns:
        {
          "date", "weekday", "is_weekend", "is_today",
          "rows": [{"worker", "kind", "start_time", "end_time", "note",
                    "is_working"}, ...],
          "working_count", "prev_date", "next_date", "month_str",
        }
    """
    workers = list(_workers(company))
    # unscoped: build_plan_board と同じ理由。company で明示的に絞る。
    plans = {
        p.worker_id: p
        for p in AttendPlan.unscoped.filter(company=company, plan_date=day)
    }

    rows = []
    working_count = 0
    for worker in workers:
        plan = plans.get(worker.pk)
        is_working = bool(plan and plan.is_working)
        if is_working:
            working_count += 1
        rows.append({
            "worker": worker,
            "kind": plan.kind if plan else "",
            "start_time": plan.start_time if plan else None,
            "end_time": plan.end_time if plan else None,
            "note": plan.note if plan else "",
            "is_working": is_working,
        })

    return {
        "date": day,
        "weekday": WEEKDAY_LABELS[day.weekday()],
        "is_saturday": day.weekday() == 5,
        "is_sunday": day.weekday() == 6,
        "is_weekend": day.weekday() >= 5,
        "is_today": day == timezone.localdate(),
        "rows": rows,
        "working_count": working_count,
        "prev_date": day - datetime.timedelta(days=1),
        "next_date": day + datetime.timedelta(days=1),
        "month_str": f"{day.year}-{day.month:02d}",
    }


# 24時間タイムラインの目盛り。3時間おきにすると、
# 文字を12px以上にしてもラベルが重ならない。
TIMELINE_TICK_HOURS = 3
MINUTES_PER_DAY = 24 * 60


def _pct(minutes: float) -> str:
    """0:00 からの分を、24時間に対する割合（%）の文字列にする。

    テンプレートで数値をそのまま出すと、ロケールによっては小数点が
    カンマになって style が壊れる。ここで文字列にしておく。
    """
    return f"{minutes / MINUTES_PER_DAY * 100:.4f}"


def _minutes(value: datetime.time) -> int:
    return value.hour * 60 + value.minute


def parse_clock(value: str, fallback: datetime.time) -> datetime.time:
    """勤怠設定の "08:00" を time にする。読めなければ fallback。"""
    try:
        return datetime.time.fromisoformat((value or "").strip())
    except ValueError:
        return fallback


def build_day_timeline(
    company,
    day: datetime.date,
    standard_start: datetime.time,
    standard_end: datetime.time,
) -> dict:
    """1日を24時間の横軸にしたタイムラインを組み立てる。

    予定に時刻が入っていなければ所定時間で描く。「何時から何時まで」を
    毎回入れさせるのは現実的でないので、入っていない＝所定どおりとして扱う。

    休む区分（有休・休み）は帯を描かない。終日いないことが分かればよく、
    帯にすると「その時間そこにいる」と読めてしまう。

    終了が開始より早い予定（夜間工事）は 24:00 までの帯にし、
    翌日へ続く印を付ける。1日の枠に収める図なので折り返しては描かない。

    Returns:
        {
          "date", "weekday", "is_saturday", "is_sunday", "is_today",
          "rows": [{"worker", "kind", "label", "short", "note",
                    "time_label", "has_bar", "left_pct", "width_pct",
                    "crosses_midnight"}, ...],
          "hours": [{"hour", "label", "left_pct"}, ...],
          "now_pct": str | None,      # 今日なら現在時刻の縦線
          "idle": [Worker, ...],      # 予定が入っていない人
          "prev_date", "next_date",
        }
    """
    labels = dict(AttendPlan.Kind.choices)
    workers = list(_workers(company))
    # unscoped: build_plan_board と同じ理由。company で明示的に絞る。
    plans = {
        p.worker_id: p
        for p in AttendPlan.unscoped.filter(company=company, plan_date=day)
    }

    rows = []
    idle = []
    for worker in workers:
        plan = plans.get(worker.pk)
        if plan is None:
            idle.append(worker)
            continue

        spec = AttendPlan.KIND_FIELDS.get(plan.kind, {})
        row = {
            "worker": worker,
            "kind": plan.kind,
            "label": labels.get(plan.kind, ""),
            "short": plan.short_label,
            "note": plan.note,
            "time_label": plan.time_label,
            "has_bar": False,
            "left_pct": "0",
            "width_pct": "0",
            "crosses_midnight": False,
        }

        # 時刻を持たない区分（有休・休み・出張）は帯にしない。
        # 出張は行先が分かればよく、何時にどこ、までは決まっていない。
        if spec.get("time"):
            start = plan.start_time or standard_start
            end = plan.end_time or standard_end
            start_min = _minutes(start)
            end_min = _minutes(end)
            if end_min <= start_min:
                # 日をまたぐ勤務。24:00 で切って印を付ける
                end_min = MINUTES_PER_DAY
                row["crosses_midnight"] = True
            row["has_bar"] = True
            row["left_pct"] = _pct(start_min)
            row["width_pct"] = _pct(end_min - start_min)
            if not plan.time_label:
                row["time_label"] = format_time_range(start, end) + "（所定）"

        rows.append(row)

    now = timezone.localtime()
    is_today = day == now.date()

    return {
        "date": day,
        "weekday": WEEKDAY_LABELS[day.weekday()],
        "is_saturday": day.weekday() == 5,
        "is_sunday": day.weekday() == 6,
        "is_today": is_today,
        "rows": rows,
        "hours": [
            {
                "hour": h,
                "label": f"{h}",
                "left_pct": _pct(h * 60),
            }
            for h in range(0, 25, TIMELINE_TICK_HOURS)
        ],
        "now_pct": _pct(now.hour * 60 + now.minute) if is_today else None,
        "idle": idle,
        "prev_date": day - datetime.timedelta(days=1),
        "next_date": day + datetime.timedelta(days=1),
    }
