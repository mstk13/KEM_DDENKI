"""積算案件の日程をガントチャート用データにする（ADR-0070）。

現場管理（apps.schedules）と同じ frappe-gantt 0.6.1 に渡す形。
描画も操作も現場管理と揃えるので、見る側が覚え直すことがない。

現場のガントとの違いは、バーの色を工程ごとに持つこと。積算の日程は
公告から取り込んだ段階（参加申請・入札書提出・開札）が並ぶため、
どこまで来たかを色で追えるようにしている。
"""
from __future__ import annotations

import datetime

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
