"""日報管理のビジネスロジック。

views.py からはこのモジュールの関数を呼ぶだけにし、
将来の DRF API 移行時にもロジックを再利用可能にする。
"""

from datetime import date

from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.services import notify
from apps.reports.models import DailyReport, SafetyRecord, SafetyTemplate


def approve_report(report: DailyReport, approved_by) -> DailyReport:
    """日報を承認し、労務費を計上する。"""
    from apps.costs.services import create_labor_cost_from_report

    report.status = DailyReport.Status.APPROVED
    report.approved_by = approved_by
    report.approved_at = timezone.now()
    report.save()
    create_labor_cost_from_report(report)
    return report


def check_safety_completion(site, check_date: date) -> dict:
    """指定現場・日付のKY記入状況をチェックする。

    Returns:
        {
            "total": 作業員数,
            "completed": 記入済み数,
            "incomplete": [未記入の SafetyRecord],
            "rate": 記入率 (0-100),
        }
    """
    templates = SafetyTemplate.unscoped.filter(
        site=site,
        is_daily_required=True,
    )

    total = 0
    completed = 0
    incomplete = []

    for template in templates:
        records = SafetyRecord.unscoped.filter(
            template=template,
            record_date=check_date,
        )
        for record in records:
            total += 1
            if record.completed:
                completed += 1
            else:
                incomplete.append(record)

    rate = int(completed / total * 100) if total > 0 else 0
    return {
        "total": total,
        "completed": completed,
        "incomplete": incomplete,
        "rate": rate,
    }


def alert_safety_incomplete(company, site, check_date: date):
    """KY未記入者にアラートを送信する。"""
    result = check_safety_completion(site, check_date)

    for record in result["incomplete"]:
        if record.alerted:
            continue

        worker = record.worker
        # 本人に通知
        if worker.user:
            notify(
                company=company,
                recipient=worker.user,
                title=f"⚠ {record.template.name}が未記入です",
                body=f"現場: {site.name} / 日付: {check_date}",
                level=Notification.Level.WARNING,
                module=Notification.Module.REPORTS,
                reference_url=f"/reports/safety/?site={site.pk}&date={check_date}",
            )

        record.alerted = True
        record.save(update_fields=["alerted"])

    return result


def create_safety_records_for_date(site, check_date: date, workers):
    """指定現場・日付・作業員リストに対してSafetyRecordを一括作成する。

    日報入力時に自動で呼ぶ想定。
    """
    templates = SafetyTemplate.unscoped.filter(
        site=site,
        is_daily_required=True,
    )

    created = []
    for template in templates:
        for worker in workers:
            record, was_created = SafetyRecord.unscoped.get_or_create(
                company=site.company,
                template=template,
                worker=worker,
                record_date=check_date,
                defaults={"completed": False},
            )
            if was_created:
                created.append(record)
    return created


def get_monthly_summary(company, year: int, month: int):
    """月別集計データを取得する。

    - 作業員別の作業時間（通常・残業）
    - 出勤日数
    """
    from django.db.models import Count, Sum

    reports = DailyReport.unscoped.filter(
        company=company,
        report_date__year=year,
        report_date__month=month,
        status=DailyReport.Status.APPROVED,
    )

    summary = (
        reports.values("worker__name", "worker__pk")
        .annotate(
            work_days=Count("report_date", distinct=True),
            total_regular=Sum("regular_hours"),
            total_overtime=Sum("overtime_hours"),
            total_hours=Sum("work_hours"),
        )
        .order_by("worker__name")
    )

    return list(summary)
