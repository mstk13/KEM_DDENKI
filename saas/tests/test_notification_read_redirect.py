"""通知の「既読」を押したら通知の一覧に戻る。

これまでは JSON をそのまま返していたので、押すと画面に {"ok": true} だけが出ていた。
HTMX・fetch から呼ぶときは、これまでどおり JSON を返す。
"""

import pytest
from django.urls import reverse

from apps.notifications.models import Notification


def _notification(company, user, title="お知らせ"):
    return Notification.unscoped.create(
        company=company, recipient=user, title=title,
        module=Notification.Module.SYSTEM,
    )


@pytest.mark.django_db
class TestNotificationRead:
    def test_既読を押すと通知の一覧に戻る(self, client, company_a, user_a):
        notification = _notification(company_a, user_a)
        client.force_login(user_a)

        res = client.post(reverse("notification_read", args=[notification.pk]))

        assert res.status_code == 302
        assert res["Location"] == reverse("notification_list")
        notification.refresh_from_db()
        assert notification.is_read is True
        assert notification.read_at is not None

    def test_すべて既読にするも一覧に戻る(self, client, company_a, user_a):
        first = _notification(company_a, user_a, "1件目")
        second = _notification(company_a, user_a, "2件目")
        client.force_login(user_a)

        res = client.post(reverse("notification_read_all"))

        assert res.status_code == 302
        assert res["Location"] == reverse("notification_list")
        first.refresh_from_db()
        second.refresh_from_db()
        assert first.is_read and second.is_read

    def test_スクリプトからの呼び出しはJSONのまま(self, client, company_a, user_a):
        notification = _notification(company_a, user_a)
        client.force_login(user_a)

        res = client.post(
            reverse("notification_read", args=[notification.pk]), HTTP_HX_REQUEST="true",
        )

        assert res.status_code == 200
        assert res.json() == {"ok": True}
        notification.refresh_from_db()
        assert notification.is_read is True

    def test_他の人の通知は既読にならない(self, client, company_a, company_b, user_a, user_b):
        other = _notification(company_b, user_b)
        client.force_login(user_a)

        res = client.post(reverse("notification_read", args=[other.pk]))

        assert res.status_code == 302
        other.refresh_from_db()
        assert other.is_read is False
