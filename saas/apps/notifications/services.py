"""
通知サービス。全モジュールから呼び出される共通ロジック。

使い方:
    from apps.notifications.services import notify, check_cost_alerts

    # 単発通知
    notify(
        company=site.company,
        recipient=user,
        title="A現場の外注費が予算の90%に到達",
        body="...",
        level=Notification.Level.WARNING,
        module=Notification.Module.COSTS,
        reference_url="/costs/1/",
    )

    # 定期チェック（Celeryタスクから呼ぶ）
    check_cost_alerts(company)
    check_qualification_expiry_alerts(company)
    check_schedule_delay_alerts(company)
    check_bid_deadline_alerts(company)
    check_safety_incomplete_alerts(company, date.today())
"""

from datetime import date

from django.db.models import Sum
from django.utils import timezone

from apps.notifications.models import AlertLog, AlertRule, Notification


def notify(
    *,
    company,
    recipient,
    title: str,
    body: str = "",
    level: str = Notification.Level.INFO,
    module: str = Notification.Module.SYSTEM,
    channel: str = Notification.Channel.IN_APP,
    reference_type: str = "",
    reference_id: int | None = None,
    reference_url: str = "",
):
    """単発通知を作成する。"""
    return Notification.unscoped.create(
        company=company,
        recipient=recipient,
        title=title,
        body=body,
        level=level,
        module=module,
        channel=channel,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_url=reference_url,
    )


def notify_multiple(
    *,
    company,
    recipients,
    title: str,
    body: str = "",
    level: str = Notification.Level.INFO,
    module: str = Notification.Module.SYSTEM,
    channel: str = Notification.Channel.IN_APP,
    reference_type: str = "",
    reference_id: int | None = None,
    reference_url: str = "",
):
    """複数ユーザーに同一通知を一括作成する。"""
    notifications = [
        Notification(
            company=company,
            recipient=user,
            title=title,
            body=body,
            level=level,
            module=module,
            channel=channel,
            reference_type=reference_type,
            reference_id=reference_id,
            reference_url=reference_url,
        )
        for user in recipients
    ]
    return Notification.unscoped.bulk_create(notifications)


def _already_alerted(alert_rule, reference_type, reference_id):
    """同一条件で既にアラート済みかチェック。"""
    return AlertLog.unscoped.filter(
        alert_rule=alert_rule,
        reference_type=reference_type,
        reference_id=reference_id,
    ).exists()


def _log_alert(alert_rule, reference_type, reference_id, detail=""):
    """アラート発火履歴を記録。"""
    return AlertLog.unscoped.create(
        company=alert_rule.company,
        alert_rule=alert_rule,
        reference_type=reference_type,
        reference_id=reference_id,
        detail=detail,
    )


def _get_alert_recipients(company, roles):
    """ロールに該当するユーザーを取得。"""
    from apps.accounts.models import User

    if not roles:
        return User.objects.filter(company=company, is_active=True)
    return User.objects.filter(
        company=company,
        is_active=True,
        groups__name__in=roles,
    ).distinct()


def check_cost_alerts(company):
    """原価アラートチェック。予算消化率が閾値を超えた現場を検出する。

    閾値: 75%, 80%, 90%, 100%超過
    """
    from apps.costs.models import BudgetItem, CostTransaction
    from apps.sites.models import Site

    rules = AlertRule.unscoped.filter(
        company=company,
        alert_type=AlertRule.AlertType.COST_THRESHOLD,
        is_active=True,
    ).order_by("threshold_value")

    if not rules.exists():
        return

    active_sites = Site.unscoped.filter(company=company, status="active")

    for site in active_sites:
        budget_total = (
            BudgetItem.unscoped.filter(company=company, site=site)
            .aggregate(total=Sum("amount"))
            .get("total")
            or 0
        )
        if budget_total == 0:
            continue

        cost_total = (
            CostTransaction.unscoped.filter(company=company, site=site)
            .aggregate(total=Sum("amount"))
            .get("total")
            or 0
        )
        consumption_pct = int((cost_total / budget_total) * 100)

        for rule in rules:
            threshold = rule.threshold_value or 0
            if consumption_pct < threshold:
                continue

            ref_type = "sites.Site"
            if _already_alerted(rule, ref_type, site.pk):
                continue

            level = (
                Notification.Level.ERROR
                if threshold >= 100
                else Notification.Level.WARNING
            )
            title = (
                f"{site.name} の原価が予算の{consumption_pct}%に到達"
                if threshold < 100
                else f"🔴 {site.name} の原価が予算を超過しました（{consumption_pct}%）"
            )
            recipients = _get_alert_recipients(company, rule.notify_roles)
            for channel in rule.notify_channels or ["in_app"]:
                notify_multiple(
                    company=company,
                    recipients=recipients,
                    title=title,
                    body=f"予算: ¥{budget_total:,.0f} / 実績: ¥{cost_total:,.0f}",
                    level=level,
                    module=Notification.Module.COSTS,
                    channel=channel,
                    reference_type=ref_type,
                    reference_id=site.pk,
                    reference_url=f"/costs/{site.pk}/",
                )
            _log_alert(rule, ref_type, site.pk, f"{consumption_pct}%")


def check_qualification_expiry_alerts(company):
    """資格期限アラートチェック。

    通知タイミング: 1年前, 6ヶ月前, 3ヶ月前, 1ヶ月前, 1週間前, 期限切れ
    """
    from apps.workers.models import WorkerQualification

    rules = AlertRule.unscoped.filter(
        company=company,
        alert_type=AlertRule.AlertType.QUALIFICATION_EXPIRY,
        is_active=True,
    ).order_by("threshold_value")

    if not rules.exists():
        return

    today = date.today()

    qualifications = WorkerQualification.unscoped.filter(
        company=company,
        expiry_date__isnull=False,
    ).select_related("worker", "worker__user")

    for qual in qualifications:
        days_remaining = (qual.expiry_date - today).days

        for rule in rules:
            threshold_days = rule.threshold_value or 0
            if days_remaining > threshold_days:
                continue

            ref_type = "workers.WorkerQualification"
            if _already_alerted(rule, ref_type, qual.pk):
                continue

            worker_name = qual.worker.name
            if days_remaining <= 0:
                title = f"🔴 {worker_name}の{qual.name}が期限切れです"
                level = Notification.Level.ERROR
            else:
                title = f"{worker_name}の{qual.name}の期限まで残り{days_remaining}日"
                level = rule.notification_level

            # 本人に通知
            if qual.worker.user:
                notify(
                    company=company,
                    recipient=qual.worker.user,
                    title=title,
                    body=f"資格: {qual.name} / 期限: {qual.expiry_date}",
                    level=level,
                    module=Notification.Module.WORKERS,
                    reference_type=ref_type,
                    reference_id=qual.pk,
                )

            # 社長・役員に通知
            recipients = _get_alert_recipients(company, rule.notify_roles)
            for channel in rule.notify_channels or ["in_app"]:
                notify_multiple(
                    company=company,
                    recipients=recipients,
                    title=title,
                    body=f"資格: {qual.name} / 期限: {qual.expiry_date}",
                    level=level,
                    module=Notification.Module.WORKERS,
                    channel=channel,
                    reference_type=ref_type,
                    reference_id=qual.pk,
                )
            _log_alert(rule, ref_type, qual.pk, f"残り{days_remaining}日")


def check_schedule_delay_alerts(company):
    """工期遅延アラートチェック。終了予定日の2週間前から警告。"""
    from apps.sites.models import Site

    rules = AlertRule.unscoped.filter(
        company=company,
        alert_type=AlertRule.AlertType.SCHEDULE_DELAY,
        is_active=True,
    )

    if not rules.exists():
        return

    today = date.today()

    sites = Site.unscoped.filter(
        company=company,
        status="active",
        end_date__isnull=False,
    )

    for site in sites:
        days_remaining = (site.end_date - today).days

        for rule in rules:
            threshold_days = rule.threshold_value or 14
            if days_remaining > threshold_days:
                continue

            ref_type = "sites.Site"
            if _already_alerted(rule, ref_type, site.pk):
                continue

            title = f"{site.name} の工期終了まで残り{days_remaining}日"
            recipients = _get_alert_recipients(company, rule.notify_roles)
            for channel in rule.notify_channels or ["in_app"]:
                notify_multiple(
                    company=company,
                    recipients=recipients,
                    title=title,
                    body=f"予定終了日: {site.end_date}",
                    level=Notification.Level.WARNING,
                    module=Notification.Module.SCHEDULES,
                    channel=channel,
                    reference_type=ref_type,
                    reference_id=site.pk,
                    reference_url=f"/schedules/{site.pk}/",
                )
            _log_alert(rule, ref_type, site.pk, f"残り{days_remaining}日")


def check_bid_deadline_alerts(company):
    """入札期限アラートチェック。期限が近い案件を通知。"""
    from apps.bids.models import BidProject

    rules = AlertRule.unscoped.filter(
        company=company,
        alert_type=AlertRule.AlertType.BID_DEADLINE,
        is_active=True,
    )

    if not rules.exists():
        return

    today = timezone.now()

    active_bids = BidProject.unscoped.filter(
        company=company,
        status__in=["NEW", "CONSIDERING", "BID"],
        deadline__isnull=False,
    )

    for bid in active_bids:
        days_remaining = (bid.deadline.date() - today.date()).days

        for rule in rules:
            threshold_days = rule.threshold_value or 7
            if days_remaining > threshold_days:
                continue

            ref_type = "bids.BidProject"
            if _already_alerted(rule, ref_type, bid.pk):
                continue

            title = f"入札期限まで残り{days_remaining}日: {bid.title}"
            recipients = _get_alert_recipients(company, rule.notify_roles)
            for channel in rule.notify_channels or ["in_app"]:
                notify_multiple(
                    company=company,
                    recipients=recipients,
                    title=title,
                    body=f"案件: {bid.title} / 期限: {bid.deadline}",
                    level=Notification.Level.WARNING,
                    module=Notification.Module.BIDS,
                    channel=channel,
                    reference_type=ref_type,
                    reference_id=bid.pk,
                    reference_url=f"/bids/{bid.pk}/",
                )
            _log_alert(rule, ref_type, bid.pk, f"残り{days_remaining}日")


def mark_as_read(notification_id, user):
    """通知を既読にする。"""
    Notification.unscoped.filter(
        pk=notification_id,
        recipient=user,
    ).update(is_read=True, read_at=timezone.now())


def mark_all_as_read(user):
    """全通知を既読にする。"""
    Notification.unscoped.filter(
        recipient=user,
        is_read=False,
    ).update(is_read=True, read_at=timezone.now())


def get_unread_count(user):
    """未読通知件数を取得する。"""
    return Notification.unscoped.filter(
        recipient=user,
        is_read=False,
    ).count()
