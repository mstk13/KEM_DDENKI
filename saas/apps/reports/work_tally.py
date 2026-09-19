"""作業日報集計（ADR-0104）。

紙の「作業日報集計フォーマット」（Excel の 1 枚目）と同じ形で、作業員ごと・月ごとに
1 日 1 行を並べる。列は 作業者名・年月日・曜日・始業・終業・所定・早出・残業・深夜・
作業内容・使用材料・車両・現場名。

- 行は承認済の日報から作る（月次サマリと同じく承認済だけ）。1 日に現場が複数あれば 1 行にまとめる
  （始業は一番早い開始、終業は一番遅い終了。作業内容・材料・現場名は並べる）
- 人が直した日は WorkTallyEntry を使い、日報をあとから直しても書き換えない
- 所定・早出・残業・深夜は Excel の数式と同じ計算。区切りの時刻は会社の設定（WorkTallySettings）
- 直せるのは社長・管理者（社員番号 Y）と、管理者が付けた人（WorkTallyEditor）

データは unscoped に会社を明示して引く。全員分の PDF などで作業員をまたいで呼ぶため、
テナントの文脈（リクエスト）に頼らず、渡された company だけに絞る。
"""

from dataclasses import dataclass, field
from datetime import date, time, timedelta

from apps.reports.models import DailyReport, WorkTallyEditor, WorkTallyEntry, WorkTallySettings

WEEKDAYS = ("月", "火", "水", "木", "金", "土", "日")
DAY_MINUTES = 24 * 60


# ---------------------------------------------------------------------------
# 設定・計算
# ---------------------------------------------------------------------------


def get_tally_settings(company):
    """会社の設定。まだ保存していなければ初期値（Excel の「設定」シートと同じ）を返す。"""
    found = WorkTallySettings.unscoped.filter(company=company).first()
    return found or WorkTallySettings(company=company)


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _overlap(start, end, lower, upper):
    """[start, end] のうち [lower, upper] と重なる分数。重ならなければ 0。"""
    return max(0, min(end, upper) - max(start, lower))


def split_minutes(start: time, end: time, settings) -> dict:
    """始業・終業から所定・早出・残業・深夜の分数を出す。Excel の数式と同じ計算。

    - 終業が始業より早ければ翌日にまたがる勤務とみなす（同じ時刻なら 0 分）
    - 所定: 所定開始～所定終了の中で働いた時間から、働いた時間と重なった休憩だけを引く
    - 早出: 所定開始より前。残業: 所定終了～深夜開始。深夜: 深夜開始より後
    """
    begin = _minutes(start)
    finish = _minutes(end)
    if finish < begin:
        finish += DAY_MINUTES
    regular_start = _minutes(settings.regular_start)
    regular_end = _minutes(settings.regular_end)
    night_start = _minutes(settings.night_start)

    breaks = sum(
        # Excel と同じく、休憩は所定の枠で切らずに勤務時間と重なった分を引く
        max(0, min(finish, _minutes(b_end)) - max(begin, _minutes(b_start)))
        for b_start, b_end in settings.breaks()
    )
    return {
        "regular": max(0, min(finish, regular_end) - max(begin, regular_start) - breaks),
        "early": max(0, min(finish, regular_start) - begin),
        "overtime": _overlap(begin, finish, regular_end, night_start),
        "night": max(0, finish - max(begin, night_start)),
    }


def format_hm(minutes) -> str:
    """分を「7:00」「12:30」の形にする（Excel の [h]:mm）。値が無ければ空。"""
    if minutes is None:
        return ""
    return f"{minutes // 60}:{minutes % 60:02d}"


def _hour_label(value: time) -> str:
    """見出し用の「8」「8:30」。"""
    return f"{value.hour}" if value.minute == 0 else f"{value.hour}:{value.minute:02d}"


def column_labels(settings) -> dict:
    """所定・早出・残業・深夜の見出し。Excel の「所定（8-17）」などを設定の時刻で作る。"""
    start = _hour_label(settings.regular_start)
    end = _hour_label(settings.regular_end)
    night = _hour_label(settings.night_start)
    return {
        "regular": f"所定（{start}-{end}）",
        "early": f"早出（～{start}時）",
        "overtime": f"残業（～{night}時）",
        "night": f"深夜（{night}時～）",
    }


# ---------------------------------------------------------------------------
# 1 日 1 行を作る
# ---------------------------------------------------------------------------


@dataclass
class TallyRow:
    day: date
    start: time | None = None
    end: time | None = None
    work_description: str = ""
    materials: str = ""
    vehicle: str = ""
    site_names: str = ""
    edited: bool = False  # 人が直した日（WorkTallyEntry がある）
    excluded: bool = False
    hours: dict = field(default_factory=dict)

    @property
    def weekday(self):
        return WEEKDAYS[self.day.weekday()]

    @property
    def has_times(self):
        return self.start is not None and self.end is not None

    def hm(self, key):
        return format_hm(self.hours.get(key))

    # テンプレートから引数なしで読めるように
    @property
    def regular_hm(self):
        return self.hm("regular")

    @property
    def early_hm(self):
        return self.hm("early")

    @property
    def overtime_hm(self):
        return self.hm("overtime")

    @property
    def night_hm(self):
        return self.hm("night")


def _distinct(values):
    seen = []
    for value in values:
        value = (value or "").strip()
        if value and value not in seen:
            seen.append(value)
    return seen


def _material_text(item):
    name = item.material_name or (item.material.name if item.material_id else "")
    if not name:
        return ""
    if item.quantity_used is None:
        return name
    quantity = f"{item.quantity_used.normalize():f}"
    return f"{name} {quantity}{item.unit or ''}"


def row_from_reports(day, reports) -> TallyRow:
    """その日の承認済の日報（現場ごとに複数あることがある）を 1 行にまとめる。"""
    periods = [p for p in (r.work_period() for r in reports) if p]
    row = TallyRow(day=day)
    if periods:
        first = min(start for start, _ in periods)
        last = max(end for _, end in periods)
        # 24 時間以上にまたがる記録は始業・終業の 2 つで表せないので、時刻は空けて人に直してもらう
        if last - first < timedelta(days=1):
            row.start, row.end = first.time(), last.time()
    row.work_description = " / ".join(_distinct(r.work_description for r in reports))
    row.site_names = "、".join(_distinct(r.site.name for r in reports))
    row.materials = "、".join(_distinct(
        _material_text(item) for r in reports for item in r.materials_used.all()
    ))
    return row


def row_from_entry(entry) -> TallyRow:
    return TallyRow(
        day=entry.work_date,
        start=entry.start_time,
        end=entry.end_time,
        work_description=entry.work_description,
        materials=entry.materials,
        vehicle=entry.vehicle,
        site_names=entry.site_names,
        edited=True,
        excluded=entry.excluded,
    )


def month_range(year, month):
    first = date(year, month, 1)
    after = date(year + (month == 12), month % 12 + 1, 1)
    return first, after


def _approved_reports(company, worker, first, after):
    return (
        DailyReport.unscoped.filter(
            company=company, worker=worker, status=DailyReport.Status.APPROVED,
            report_date__gte=first, report_date__lt=after,
        )
        .select_related("site")
        .prefetch_related("materials_used__material")
        .order_by("report_date", "start_time", "pk")
    )


def report_row(company, worker, day) -> TallyRow:
    """その日の日報から作った行（人の直しを入れる前）。編集画面の初期値と「戻す」に使う。"""
    reports = list(_approved_reports(company, worker, day, day + timedelta(days=1)))
    return row_from_reports(day, reports)


def build_sheet(company, worker, year, month, settings=None):
    """作業員 1 人・1 か月分の集計表。

    返す辞書:
      rows      … 1 日 1 行（集計から外した日も含む。表示で薄くする）
      totals    … 所定・早出・残業・深夜の合計（分）。外した日は数えない
      total_all … 4 つの合計（実労働時間 計）
    """
    settings = settings or get_tally_settings(company)
    first, after = month_range(year, month)

    by_day = {}
    for report in _approved_reports(company, worker, first, after):
        by_day.setdefault(report.report_date, []).append(report)
    rows = {day: row_from_reports(day, reports) for day, reports in by_day.items()}

    entries = WorkTallyEntry.unscoped.filter(
        company=company, worker=worker, work_date__gte=first, work_date__lt=after,
    )
    for entry in entries:
        rows[entry.work_date] = row_from_entry(entry)

    ordered = [rows[day] for day in sorted(rows)]
    totals = {"regular": 0, "early": 0, "overtime": 0, "night": 0}
    for row in ordered:
        if row.has_times:
            row.hours = split_minutes(row.start, row.end, settings)
        if row.excluded:
            continue
        for key in totals:
            totals[key] += row.hours.get(key, 0)
    return {
        "worker": worker,
        "year": year,
        "month": month,
        "rows": ordered,
        "totals": totals,
        "totals_hm": {key: format_hm(value) for key, value in totals.items()},
        "total_all": sum(totals.values()),
        "total_all_hm": format_hm(sum(totals.values())),
        "labels": column_labels(settings),
    }


def workers_with_tally(company, year, month):
    """その月に集計表の行がある作業員（承認済の日報か手直しがある人）を社員番号順で返す。"""
    from apps.workers.models import Worker, sort_workers_by_code

    first, after = month_range(year, month)
    report_ids = DailyReport.unscoped.filter(
        company=company, status=DailyReport.Status.APPROVED,
        report_date__gte=first, report_date__lt=after,
    ).values_list("worker_id", flat=True)
    entry_ids = WorkTallyEntry.unscoped.filter(
        company=company, work_date__gte=first, work_date__lt=after,
    ).values_list("worker_id", flat=True)
    workers = Worker.unscoped.filter(company=company, pk__in={*report_ids, *entry_ids})
    return sort_workers_by_code(workers)


def vehicle_candidates(company, limit=30):
    """これまでに入れた車両。入力欄の候補に出す（よく使うものから）。"""
    from django.db.models import Count

    return list(
        WorkTallyEntry.unscoped.filter(company=company).exclude(vehicle="")
        .values("vehicle").annotate(n=Count("pk")).order_by("-n", "vehicle")
        .values_list("vehicle", flat=True)[:limit]
    )


# ---------------------------------------------------------------------------
# 権限
# ---------------------------------------------------------------------------


def can_manage_tally_editors(user) -> bool:
    """「集計表を直せる人」を付け外しできるか。社長と管理者（社員番号 Y）。"""
    from apps.permissions.services import is_president

    if not user.is_authenticated:
        return False
    if is_president(user):
        return True
    profile = getattr(user, "worker_profile", None)
    return bool(profile and (profile.employee_code or "").startswith("Y"))


def can_edit_tally(user) -> bool:
    """作業日報集計を直せるか。社長・管理者と、管理者が付けた人（全員分を直せる）。"""
    if can_manage_tally_editors(user):
        return True
    profile = getattr(user, "worker_profile", None)
    if profile is None:
        return False
    return WorkTallyEditor.unscoped.filter(company_id=profile.company_id, worker=profile).exists()

