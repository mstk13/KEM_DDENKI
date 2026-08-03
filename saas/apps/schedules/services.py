"""工期管理のビジネスロジック。

ガントチャートデータ生成、配置カレンダーデータ生成、
テンプレートからの工程一括作成を担う。
将来の DRF API 移行時にもそのまま使える。
"""

import json
from datetime import date, timedelta

from apps.schedules.models import Assignment, Milestone, Phase, PhaseTemplate


def get_gantt_data(company):
    """全現場のガントチャートデータを生成する（frappe-gantt用JSON）。

    Returns:
        [
            {"id": "site-1", "name": "A現場", "start": "2026-08-01", "end": "2026-10-31", "progress": 45, "custom_class": "bar-blue"},
            ...
        ]
    """
    from apps.sites.models import Site

    sites = Site.unscoped.filter(
        company=company,
        status__in=["in_progress", "ordered"],
    ).order_by("start_date")

    tasks = []
    for site in sites:
        if not site.start_date or not site.end_date:
            continue

        # 現場全体の平均進捗
        phases = Phase.unscoped.filter(site=site)
        avg_progress = 0
        if phases.exists():
            total = sum(p.progress for p in phases)
            avg_progress = total // phases.count()

        tasks.append({
            "id": f"site-{site.pk}",
            "name": site.name,
            "start": site.start_date.isoformat(),
            "end": site.end_date.isoformat(),
            "progress": avg_progress,
            "custom_class": "bar-blue",
        })

    return tasks


def get_site_gantt_data(site):
    """現場内の工程別ガントチャートデータ（frappe-gantt用JSON）。"""
    phases = Phase.unscoped.filter(site=site).order_by("sort_order")
    milestones = Milestone.unscoped.filter(site=site)

    tasks = []
    for phase in phases:
        if not phase.start_date or not phase.end_date:
            continue
        tasks.append({
            "id": f"phase-{phase.pk}",
            "name": phase.name,
            "start": phase.start_date.isoformat(),
            "end": phase.end_date.isoformat(),
            "progress": phase.progress,
            "custom_class": f"bar-custom",
        })

    for ms in milestones:
        if not ms.target_date:
            continue
        tasks.append({
            "id": f"ms-{ms.pk}",
            "name": f"◆ {ms.name}",
            "start": ms.target_date.isoformat(),
            "end": ms.target_date.isoformat(),
            "progress": 100 if ms.completed else 0,
            "custom_class": "bar-milestone",
        })

    return tasks


def get_calendar_data(company, start_date, end_date):
    """配置カレンダーデータを生成する（FullCalendar用JSON）。

    Returns:
        [
            {"title": "田中太郎", "start": "2026-08-01", "end": "2026-08-05", "color": "#3b82f6", "extendedProps": {"site": "A現場"}},
            ...
        ]
    """
    assignments = Assignment.unscoped.filter(
        company=company,
        start_date__lte=end_date,
    ).filter(
        # end_dateがNULL（無期限）or end_date >= start_date
        **{"end_date__gte": start_date}
    ).select_related("worker", "site") | Assignment.unscoped.filter(
        company=company,
        start_date__lte=end_date,
        end_date__isnull=True,
    ).select_related("worker", "site")

    colors = ["#3b82f6", "#ef4444", "#f59e0b", "#10b981", "#8b5cf6", "#ec4899", "#06b6d4"]
    site_colors = {}
    color_idx = 0

    events = []
    for a in assignments.distinct():
        if a.site_id not in site_colors:
            site_colors[a.site_id] = colors[color_idx % len(colors)]
            color_idx += 1

        events.append({
            "title": f"{a.worker.name} → {a.site.name}",
            "start": a.start_date.isoformat(),
            "end": (a.end_date + timedelta(days=1)).isoformat() if a.end_date else None,
            "color": site_colors[a.site_id],
            "extendedProps": {
                "worker": a.worker.name,
                "site": a.site.name,
            },
        })

    return events


def apply_template(site, template_id, base_date=None):
    """工程テンプレートを現場に適用して Phase を一括作成する。

    Args:
        site: Site インスタンス
        template_id: PhaseTemplate の PK
        base_date: 基準日（デフォルト: 今日）
    """
    template = PhaseTemplate.unscoped.get(pk=template_id)
    if base_date is None:
        base_date = date.today()

    created = []
    for item in template.items.order_by("sort_order"):
        phase = Phase.unscoped.create(
            company=site.company,
            site=site,
            name=item.name,
            start_date=base_date + timedelta(days=item.offset_days_start),
            end_date=base_date + timedelta(days=item.offset_days_end),
            sort_order=item.sort_order,
            color=item.color,
        )
        created.append(phase)

    return created
