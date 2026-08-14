"""通知基盤のテスト。"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.notifications.models import AlertLog, AlertRule, Notification
from apps.notifications.services import (
    get_unread_count,
    mark_all_as_read,
    mark_as_read,
    notify,
    notify_multiple,
)


@pytest.mark.django_db
class TestNotificationModel:
    def test_create_notification(self, company, user):
        n = Notification.unscoped.create(
            company=company,
            recipient=user,
            title="テスト通知",
            body="テスト本文",
            level=Notification.Level.INFO,
            module=Notification.Module.REPORTS,
        )
        assert n.pk is not None
        assert n.is_read is False
        assert str(n) == "[情報] テスト通知"

    def test_notification_ordering(self, company, user):
        n1 = Notification.unscoped.create(
            company=company,
            recipient=user,
            title="古い通知",
            module=Notification.Module.REPORTS,
        )
        n2 = Notification.unscoped.create(
            company=company,
            recipient=user,
            title="新しい通知",
            module=Notification.Module.REPORTS,
        )
        # sent_at は auto_now_add で、続けて作ると同じ時刻になり得る。
        # 同時刻だと並び順が不定になりテストが揺れるため、明示的に差をつける。
        base = timezone.now()
        Notification.unscoped.filter(pk=n1.pk).update(sent_at=base - timedelta(hours=1))
        Notification.unscoped.filter(pk=n2.pk).update(sent_at=base)

        notifications = list(
            Notification.unscoped.filter(recipient=user).order_by("-sent_at")
        )
        assert notifications[0].pk == n2.pk
        assert notifications[1].pk == n1.pk


@pytest.mark.django_db
class TestAlertRule:
    def test_create_alert_rule(self, company):
        rule = AlertRule.unscoped.create(
            company=company,
            name="原価75%警告",
            alert_type=AlertRule.AlertType.COST_THRESHOLD,
            threshold_value=75,
            notification_level=Notification.Level.WARNING,
            notify_channels=["in_app"],
            notify_roles=["president"],
        )
        assert rule.pk is not None
        assert str(rule) == "原価75%警告 (原価閾値)"


@pytest.mark.django_db
class TestNotifyService:
    def test_notify_creates_notification(self, company, user):
        n = notify(
            company=company,
            recipient=user,
            title="サービスからの通知",
            module=Notification.Module.COSTS,
        )
        assert n.pk is not None
        assert n.recipient == user

    def test_notify_multiple(self, company, user, user2):
        notifications = notify_multiple(
            company=company,
            recipients=[user, user2],
            title="一括通知",
            module=Notification.Module.BIDS,
        )
        assert len(notifications) == 2

    def test_mark_as_read(self, company, user):
        n = notify(
            company=company,
            recipient=user,
            title="既読テスト",
            module=Notification.Module.SYSTEM,
        )
        assert n.is_read is False
        mark_as_read(n.pk, user)
        n.refresh_from_db()
        assert n.is_read is True
        assert n.read_at is not None

    def test_mark_all_as_read(self, company, user):
        for i in range(3):
            notify(
                company=company,
                recipient=user,
                title=f"通知{i}",
                module=Notification.Module.SYSTEM,
            )
        assert get_unread_count(user) == 3
        mark_all_as_read(user)
        assert get_unread_count(user) == 0

    def test_unread_count(self, company, user):
        notify(
            company=company,
            recipient=user,
            title="未読1",
            module=Notification.Module.SYSTEM,
        )
        notify(
            company=company,
            recipient=user,
            title="未読2",
            module=Notification.Module.SYSTEM,
        )
        assert get_unread_count(user) == 2


@pytest.mark.django_db
class TestAlertLog:
    def test_duplicate_prevention(self, company):
        rule = AlertRule.unscoped.create(
            company=company,
            name="テストルール",
            alert_type=AlertRule.AlertType.COST_THRESHOLD,
            threshold_value=75,
        )
        AlertLog.unscoped.create(
            company=company,
            alert_rule=rule,
            reference_type="sites.Site",
            reference_id=1,
        )
        exists = AlertLog.unscoped.filter(
            alert_rule=rule,
            reference_type="sites.Site",
            reference_id=1,
        ).exists()
        assert exists is True
