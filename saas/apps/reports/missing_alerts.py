"""日報を書いていない人に知らせる（ADR-0077）。

「その日に稼働する予定（出社予定の 出社・現場・直行直帰・出張）があるのに、
その日の日報が1件も無い作業員」を未提出とみなす。予定が入っていない日は
休みか未定なので対象にしない。今日はまだ書いている途中なので対象にしない。

知らせ先は本人（ログインできる人）と、まとめた1件を管理者に送る。
同じ人の同じ日について二重に送らないよう、送った通知そのものを目印に使う
（reference_type に日付を入れているので、その日ぶんが既にあれば送らない）。
"""

import datetime

from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.services import notify

# 何日前までさかのぼって調べるか。月末にまとめて書く人がいるので少し長めに取る。
LOOKBACK_DAYS = 14

REFERENCE_PREFIX = "reports.missing"
ADMIN_ROLES = ("president", "executive", "manager")


def _reference_type(day):
    return f"{REFERENCE_PREFIX}:{day.isoformat()}"


def target_days(today=None):
    """調べる日の並び。古い日から。今日は入れない。"""
    today = today or timezone.localdate()
    return [
        today - datetime.timedelta(days=n)
        for n in range(LOOKBACK_DAYS, 0, -1)
    ]


def missing_reports(company, *, today=None, workers=None):
    """日報が無い（作業員, 日）の組を返す。

    Args:
        company: 会社
        today: 今日の日付（テスト用）
        workers: 調べる作業員を絞る場合に渡す

    Returns:
        [(Worker, date), ...] 日付の古い順、同じ日は作業員の名前順。
    """
    from apps.attendance.models import AttendPlan
    from apps.reports.models import DailyReport

    days = target_days(today)
    if not days:
        return []
    first, last = days[0], days[-1]

    # unscoped: 会社を明示して絞る。コマンドからも呼ぶため。
    plans = AttendPlan.unscoped.filter(
        company=company,
        plan_date__range=(first, last),
        kind__in=AttendPlan.WORKING_KINDS,
    ).select_related("worker")
    if workers is not None:
        plans = plans.filter(worker__in=workers)

    planned = {}
    for plan in plans:
        if not plan.worker.is_active:
            continue
        planned.setdefault(plan.plan_date, {})[plan.worker.pk] = plan.worker

    if not planned:
        return []

    written = set(
        DailyReport.unscoped.filter(
            company=company, report_date__range=(first, last),
        ).values_list("report_date", "worker_id")
    )

    found = []
    for day in days:
        for worker in sorted(planned.get(day, {}).values(), key=lambda w: w.name or ""):
            if (day, worker.pk) not in written:
                found.append((worker, day))
    return found


def missing_days_for_worker(worker, *, today=None):
    """その人が日報を書いていない日。画面の赤字に使う。新しい日が先。"""
    if worker is None:
        return []
    found = missing_reports(worker.company, today=today, workers=[worker])
    return [day for _w, day in reversed(found)]


def _already_sent(company, recipient, day, worker_pk):
    return Notification.unscoped.filter(
        company=company,
        recipient=recipient,
        reference_type=_reference_type(day),
        reference_id=worker_pk,
    ).exists()


def _admins(company):
    from apps.notifications.services import _get_alert_recipients

    return list(_get_alert_recipients(company, list(ADMIN_ROLES)))


def check_daily_report_missing_alerts(company, *, today=None):
    """日報の未提出を知らせる。送った件数を返す。"""
    found = missing_reports(company, today=today)
    if not found:
        return 0

    sent = 0
    by_day = {}
    for worker, day in found:
        by_day.setdefault(day, []).append(worker)

        user = worker.user
        if user is None or _already_sent(company, user, day, worker.pk):
            continue
        notify(
            company=company,
            recipient=user,
            title=f"{day.month}月{day.day}日の日報が未提出です",
            body="出社予定が入っている日の日報がまだありません。日報を書いてください。",
            level=Notification.Level.WARNING,
            module=Notification.Module.REPORTS,
            reference_type=_reference_type(day),
            reference_id=worker.pk,
            reference_url="/reports/new/",
        )
        sent += 1

    # 管理者には日ごとに1件だけまとめて送る
    admins = _admins(company)
    for day, workers in sorted(by_day.items()):
        names = "、".join(w.name for w in workers)
        for admin in admins:
            if _already_sent(company, admin, day, 0):
                continue
            notify(
                company=company,
                recipient=admin,
                title=f"{day.month}月{day.day}日の日報が未提出: {len(workers)}名",
                body=names,
                level=Notification.Level.WARNING,
                module=Notification.Module.REPORTS,
                reference_type=_reference_type(day),
                reference_id=0,
                reference_url="/reports/",
            )
            sent += 1
    return sent
