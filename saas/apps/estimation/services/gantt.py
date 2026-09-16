"""積算案件の日程をガントチャートにする。

見る場所が2つあり、読みたいことが違うので作りも分けている。

**詳細画面（ADR-0076）** … `get_project_gantt_data`
    1案件の中を工程ごとに1本ずつ並べる。現場管理と同じ frappe-gantt 0.6.1。
    描画も操作も現場管理と揃うので、見る側が覚え直すことがない。

**一覧の上（ADR-0078）** … `get_projects_gantt_data`
    **1案件1本**にし、その1本の中を工程ごとの色で塗り分ける。
    案件が何件も並ぶ場所で工程を1本ずつ出すと縦に伸びて、
    「どの案件がいつ終わるか」が一目で読めなくなるため。
"""
from __future__ import annotations

import datetime

from django.utils import timezone

from apps.estimation.models import EstimationPhase


def get_project_gantt_data(project) -> list[dict]:
    """積算案件の工程を frappe-gantt 用のタスクにする。

    日付が片方でも空の工程は描けないので飛ばす。工程一覧には出るので、
    「ガントに出ていない ＝ 日付が入っていない」と読める。
    """
    # unscoped: project から辿るので会社は絞り込み済み
    phases = EstimationPhase.unscoped.filter(project=project).order_by(
        "sort_order", "start_date",
    )

    tasks = []
    for phase in phases:
        if not phase.start_date or not phase.end_date:
            continue
        # frappe-gantt は日単位。同日開始・終了だと幅0でバーが見えないため
        # 1日分に広げる。入札側の bids.gantt と同じ扱い。
        end = max(phase.end_date, phase.start_date + datetime.timedelta(days=1))
        tasks.append({
            "id": f"estphase-{phase.pk}",
            "name": phase.name,
            "start": phase.start_date.isoformat(),
            "end": end.isoformat(),
            "progress": phase.progress,
            "custom_class": "bar-custom",
            "_color": phase.color,
            "_memo": phase.memo,
            "_from_bid": bool(phase.source_label),
        })
    return tasks


# ---------------------------------------------------------------------------
# 積算案件の一覧に出す、案件を並べたガント（ADR-0078）
# ---------------------------------------------------------------------------
#
# 詳細画面のガント（上の get_project_gantt_data）は1案件の中を工程ごとに
# 1本ずつ並べる。一覧では案件が何件も並ぶので、同じ描き方だと縦に伸びて
# 「どの案件がいつ終わるか」が一目で読めない。
#
# そこで**1案件1本**にし、その1本の中を工程ごとの色で塗り分ける。
# 段階（参加申請→入札書提出→開札）が色の帯として並ぶので、
# 案件どうしの前後関係と、各案件がいまどの段階かが同時に読める。
#
# frappe-gantt は1タスク1バーで、1本を塗り分けられない。ここだけは
# 帯を並べた自前の描画にし、位置は全体の期間に対する％で持たせる。


def _span_of(phases):
    """工程の集まりが覆う期間。日付が揃っていない工程は数えない。"""
    starts = [p.start_date for p in phases if p.start_date and p.end_date]
    ends = [p.end_date for p in phases if p.start_date and p.end_date]
    if not starts:
        return None, None
    return min(starts), max(ends)


def _pct(day, origin, total_days):
    """期間の左端からの位置を％で返す。"""
    if total_days <= 0:
        return 0.0
    return round((day - origin).days * 100 / total_days, 4)


def _month_ticks(origin, goal, total_days):
    """目盛り。月の1日に線を引く。期間が長いときは間引く。"""
    ticks = []
    # 期間が長いほど月ラベルが詰まるので、何か月かおきにする
    step = 1 if total_days <= 200 else (2 if total_days <= 400 else 3)
    year, month = origin.year, origin.month
    index = 0
    while True:
        day = datetime.date(year, month, 1)
        if day > goal:
            break
        if day >= origin and index % step == 0:
            ticks.append({
                "label": f"{day.year}/{day.month:02d}",
                "left_pct": _pct(day, origin, total_days),
            })
        index += 1
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return ticks


def get_projects_gantt_data(company, statuses=None, today=None):
    """積算案件を1案件1本で並べたガントのデータ（ADR-0078）。

    Args:
        company: 対象テナント
        statuses: 対象の状態。既定は積算中のみ
        today: 「今日」の線を引く日。テストから差し替える

    Returns:
        {
          "rows": [{"project", "start", "end", "days", "segments": [...]}, ...],
          "ticks": [{"label", "left_pct"}, ...],
          "legend": [{"name", "color"}, ...],
          "start", "end", "today_pct",
        }
        日付の入った工程が1件も無ければ rows は空。
    """
    from apps.estimation.models import EstimationPhase, EstimationProject

    statuses = statuses or [EstimationProject.Status.ESTIMATING]
    today = today or timezone.localdate()

    # unscoped: company を引数で受けて明示的に絞る（services の他と同じ方針）
    projects = list(
        EstimationProject.unscoped
        .filter(company=company, status__in=statuses)
        .select_related("orderer")
        .order_by("pk")
    )
    if not projects:
        return _empty_projects_gantt()

    phases_by_project = {}
    for phase in EstimationPhase.unscoped.filter(
        project__in=projects,
    ).order_by("sort_order", "start_date"):
        phases_by_project.setdefault(phase.project_id, []).append(phase)

    # --- 1. 全体の期間を決める ---
    spans = {}
    for project in projects:
        start, end = _span_of(phases_by_project.get(project.pk, []))
        if start and end:
            spans[project.pk] = (start, end)
    if not spans:
        return _empty_projects_gantt()

    origin = min(start for start, _ in spans.values())
    goal = max(end for _, end in spans.values())
    # 終了日の当日も帯に含めたいので1日足す（1日だけの工程が幅0にならない）
    total_days = (goal - origin).days + 1

    # --- 2. 案件ごとに1本、その中を工程の色で塗り分ける ---
    rows = []
    legend = {}
    for project in projects:
        if project.pk not in spans:
            continue
        start, end = spans[project.pk]
        segments = []
        for phase in phases_by_project[project.pk]:
            if not (phase.start_date and phase.end_date):
                continue
            left = _pct(phase.start_date, origin, total_days)
            width = _pct(phase.end_date, origin, total_days) - left
            segments.append({
                "name": phase.name,
                "color": phase.color,
                "left_pct": left,
                # 同日開始・終了でも帯が見えるように最低幅を持たせる
                "width_pct": max(width, 100 / total_days),
                "start": phase.start_date,
                "end": phase.end_date,
                "progress": phase.progress,
            })
            legend.setdefault(phase.name, phase.color)

        rows.append({
            "project": project,
            "start": start,
            "end": end,
            # 工期日数は両端を含めて数える（1日なら1日）
            "days": (end - start).days + 1,
            "segments": segments,
        })

    # 終わりが近い案件から上に出す。一覧の並び（更新順）とは別に、
    # 「次に開札が来るのはどれか」を上から読めるようにする
    rows.sort(key=lambda row: (row["end"], row["start"]))

    today_pct = _pct(today, origin, total_days) if origin <= today <= goal else None

    return {
        "rows": rows,
        "ticks": _month_ticks(origin, goal, total_days),
        "legend": [{"name": name, "color": color} for name, color in legend.items()],
        "start": origin,
        "end": goal,
        "today_pct": today_pct,
    }


def _empty_projects_gantt():
    return {"rows": [], "ticks": [], "legend": [],
            "start": None, "end": None, "today_pct": None}
