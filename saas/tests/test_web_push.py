"""スマホへのプッシュ通知（Web Push, ADR-0062）。

ここで固定すること:
1. 中身の暗号化は RFC 8291 の例と同じ結果になり、端末の鍵で解ける
2. VAPID の署名は公開鍵で確かめられ、送り先のオリジン・期限・連絡先が入っている
3. 送り先の登録は、主なプッシュサービスの https の URL と正しい形の鍵だけ受け付ける。
   同じ端末で別の人がオンにしたら付け替える。消せるのは自分の登録だけ
4. 1分ごとの送り出しは、まだ送っていない・未読の・端末でオンにした後の・6時間以内の知らせだけ送る。
   同じ知らせは二重に送らない。4件以上はまとめて1通。届かなくなった端末は消す
5. 通知を押すと既読になって知らせの画面へ移る（外のサイトへは移らない）
6. 鍵が無ければ何も送らず、画面には「まだ使えません」と出せる
7. 記録は会社ごとに分かれ、変更履歴と管理画面がある
"""

import io
import json
import os
from datetime import timedelta
from types import SimpleNamespace

import pytest
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings as django_settings
from django.contrib import admin
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from django.utils import timezone
from simple_history.admin import SimpleHistoryAdmin

from apps.core.tenant_context import set_current_company
from apps.notifications import push
from apps.notifications.models import Notification, PushSubscription
from apps.notifications.push import (
    b64url_decode,
    b64url_encode,
    encrypt,
    generate_vapid_keys,
    is_allowed_endpoint,
    load_private_key,
    push_enabled,
    send_pending_pushes,
    vapid_headers,
    vapid_public_key,
)

# RFC 8291 Section 5 の例
RFC_PLAINTEXT = b"When I grow up, I want to be a watermelon"
RFC_AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
RFC_UA_PRIVATE = "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"
RFC_UA_PUBLIC = (
    "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
)
RFC_AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
RFC_SALT = "DGv6ra1nlYgDCS1FRnbzlw"
RFC_BODY = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIg"
    "Dll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVB"
    "St2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
)

ENDPOINT = "https://fcm.googleapis.com/fcm/send/device-1"


def _hkdf(length, salt, info, key):
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(key)


def _decrypt(body, ua_private, ua_public, auth):
    """端末（ブラウザ）の側で中身を解く（RFC 8291）。"""
    salt = body[:16]
    key_length = body[20]
    as_public = body[21 : 21 + key_length]
    ciphertext = body[21 + key_length :]
    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
    ecdh_secret = ua_private.exchange(ec.ECDH(), peer)
    key_info = b"WebPush: info\x00" + b64url_decode(ua_public) + as_public
    ikm = _hkdf(32, b64url_decode(auth), key_info, ecdh_secret)
    cek = _hkdf(16, salt, b"Content-Encoding: aes128gcm\x00", ikm)
    nonce = _hkdf(12, salt, b"Content-Encoding: nonce\x00", ikm)
    record = AESGCM(cek).decrypt(nonce, ciphertext, None)
    assert record.endswith(b"\x02")
    return record[:-1]


def _device():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public = private_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return private_key, b64url_encode(public), b64url_encode(os.urandom(16))


def _subscription(user, endpoint=ENDPOINT, created_at=None, **extra):
    ua_private, ua_public, auth = _device()
    subscription = PushSubscription.unscoped.create(
        company=user.company,
        user=user,
        endpoint=endpoint,
        p256dh=ua_public,
        auth=auth,
        **extra,
    )
    if created_at is not None:
        PushSubscription.unscoped.filter(pk=subscription.pk).update(created_at=created_at)
        subscription.refresh_from_db()
    subscription.ua_private = ua_private
    return subscription


KY_TITLE = "【A社ビル新築】今日のKY用紙を記入してください"


def _notification(user, title=KY_TITLE, sent_at=None, **extra):
    notification = Notification.unscoped.create(
        company=user.company,
        recipient=user,
        title=title,
        module=Notification.Module.SAFETY,
        **extra,
    )
    if sent_at is not None:
        Notification.unscoped.filter(pk=notification.pk).update(sent_at=sent_at)
        notification.refresh_from_db()
    return notification


def _payload(call, subscription):
    body = _decrypt(call["data"], subscription.ua_private, subscription.p256dh, subscription.auth)
    return json.loads(body.decode("utf-8"))


def _subscribe_body(endpoint=ENDPOINT, p256dh=None, auth=None):
    _, ua_public, ua_auth = _device()
    return {
        "endpoint": endpoint,
        "expirationTime": None,
        "keys": {"p256dh": p256dh or ua_public, "auth": auth or ua_auth},
    }


@pytest.fixture
def vapid(settings):
    private_key, public_key = generate_vapid_keys()
    settings.WEBPUSH_VAPID_PRIVATE_KEY = private_key
    settings.WEBPUSH_VAPID_SUBJECT = "mailto:test@example.com"
    return public_key


@pytest.fixture
def push_service(monkeypatch):
    """プッシュサービスの代わり。送り先ごとに応答コード（または例外）を決められる。"""
    service = SimpleNamespace(calls=[], statuses={})

    def fake_post(url, data=None, headers=None, timeout=None, allow_redirects=True):
        service.calls.append(
            {"url": url, "data": data, "headers": headers, "allow_redirects": allow_redirects}
        )
        status = service.statuses.get(url, 201)
        if isinstance(status, Exception):
            raise status
        return SimpleNamespace(status_code=status)

    monkeypatch.setattr(push.requests, "post", fake_post)
    return service


@pytest.fixture
def logged_in(client, user_a):
    client.force_login(user_a)
    return client


# ---------------------------------------------------------------------------
# 暗号化と署名
# ---------------------------------------------------------------------------


class TestCrypto:
    def test_RFC8291の例と同じに暗号化する(self):
        body = encrypt(
            RFC_PLAINTEXT,
            RFC_UA_PUBLIC,
            RFC_AUTH,
            salt=b64url_decode(RFC_SALT),
            server_private_key=load_private_key(RFC_AS_PRIVATE),
        )

        assert b64url_encode(body) == RFC_BODY

    def test_RFC8291の例を端末の鍵で解ける(self):
        ua_private = load_private_key(RFC_UA_PRIVATE)

        assert _decrypt(b64url_decode(RFC_BODY), ua_private, RFC_UA_PUBLIC, RFC_AUTH) == (
            RFC_PLAINTEXT
        )

    def test_毎回ちがう鍵で暗号化し_端末の鍵で解ける(self):
        ua_private, ua_public, auth = _device()

        first = encrypt("朝のKY".encode(), ua_public, auth)
        second = encrypt("朝のKY".encode(), ua_public, auth)

        assert first != second
        assert _decrypt(first, ua_private, ua_public, auth).decode() == "朝のKY"

    def test_大きすぎる中身は送らない(self):
        _, ua_public, auth = _device()

        with pytest.raises(ValueError):
            encrypt(b"x" * 4096, ua_public, auth)

    def test_VAPIDの署名を公開鍵で確かめられる(self, vapid):
        headers = vapid_headers(ENDPOINT, now=1_800_000_000)

        token_part, key_part = headers["Authorization"].removeprefix("vapid ").split(", ")
        token = token_part.removeprefix("t=")
        public_key = key_part.removeprefix("k=")
        assert public_key == vapid == vapid_public_key()
        header_b64, claims_b64, signature_b64 = token.split(".")
        signature = b64url_decode(signature_b64)
        verifier = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), b64url_decode(public_key)
        )
        verifier.verify(
            encode_dss_signature(
                int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
            ),
            f"{header_b64}.{claims_b64}".encode(),
            ec.ECDSA(hashes.SHA256()),
        )
        assert json.loads(b64url_decode(header_b64)) == {"typ": "JWT", "alg": "ES256"}
        assert json.loads(b64url_decode(claims_b64)) == {
            "aud": "https://fcm.googleapis.com",
            "exp": 1_800_000_000 + 12 * 60 * 60,
            "sub": "mailto:test@example.com",
        }

    def test_鍵を作るコマンドの秘密鍵を置けば使える(self, settings):
        out = io.StringIO()

        call_command("generate_vapid_keys", stdout=out)

        lines = out.getvalue().splitlines()
        prefix = "WEBPUSH_VAPID_PRIVATE_KEY="
        private_line = next(line for line in lines if line.startswith(prefix))
        settings.WEBPUSH_VAPID_PRIVATE_KEY = private_line.removeprefix(prefix)
        assert push_enabled()
        assert len(b64url_decode(vapid_public_key())) == 65
        assert vapid_public_key() in out.getvalue()

    @pytest.mark.parametrize("key", ["", "abc", b64url_encode(b"\x00" * 32)])
    def test_鍵が無い_形が違うときは使わない(self, settings, key):
        settings.WEBPUSH_VAPID_PRIVATE_KEY = key

        assert not push_enabled()
        assert vapid_public_key() == ""

    @pytest.mark.parametrize(
        "endpoint",
        [
            "https://fcm.googleapis.com/fcm/send/abc",
            "https://web.push.apple.com/QGuQyavXutnMH",
            "https://updates.push.services.mozilla.com/wpush/v2/gAAAA",
            "https://wns2-par02p.notify.windows.com/w/?token=BQYAAA",
        ],
    )
    def test_主なプッシュサービスの送り先は受け付ける(self, endpoint):
        assert is_allowed_endpoint(endpoint)

    @pytest.mark.parametrize(
        "endpoint",
        [
            "http://fcm.googleapis.com/fcm/send/abc",
            "https://db:5432/",
            "https://127.0.0.1/push",
            "https://fcm.googleapis.com.evil.example/fcm/send/abc",
            "https://evilfcm.googleapis.com.example/abc",
            "https://user:pw@fcm.googleapis.com/fcm/send/abc",
            "https://fcm.googleapis.com:8443/fcm/send/abc",
            "https://fcm.googleapis.com:99999/abc",
            "",
        ],
    )
    def test_それ以外の送り先は受け付けない(self, endpoint):
        assert not is_allowed_endpoint(endpoint)


# ---------------------------------------------------------------------------
# 送り先の登録
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSubscribe:
    def _post(self, client, name, body):
        return client.post(
            reverse(name),
            data=json.dumps(body) if not isinstance(body, str) else body,
            content_type="application/json",
            HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X)",
        )

    def test_送り先を登録する(self, logged_in, user_a, company_a, vapid):
        body = _subscribe_body()

        res = self._post(logged_in, "push_subscribe", body)

        assert res.status_code == 200
        assert res.json() == {"ok": True}
        subscription = PushSubscription.unscoped.get()
        assert subscription.user == user_a
        assert subscription.company == company_a
        assert subscription.endpoint == ENDPOINT
        assert subscription.p256dh == body["keys"]["p256dh"]
        assert "iPhone" in subscription.user_agent

    @pytest.mark.parametrize(
        "endpoint",
        ["http://fcm.googleapis.com/fcm/send/x", "https://db:5432/", "https://example.com/push"],
    )
    def test_プッシュサービス以外の送り先は受け付けない(self, logged_in, vapid, endpoint):
        res = self._post(logged_in, "push_subscribe", _subscribe_body(endpoint=endpoint))

        assert res.status_code == 400
        assert res.json()["ok"] is False
        assert not PushSubscription.unscoped.exists()

    @pytest.mark.parametrize(
        "body",
        [
            _subscribe_body(p256dh="abc"),
            _subscribe_body(auth=b64url_encode(b"short")),
            _subscribe_body(p256dh=b64url_encode(b"\x04" + b"\x00" * 64)),
            {"endpoint": ENDPOINT},
            "これは JSON ではない",
            [],
        ],
    )
    def test_鍵の形が違えば受け付けない(self, logged_in, vapid, body):
        res = self._post(logged_in, "push_subscribe", body)

        assert res.status_code == 400
        assert not PushSubscription.unscoped.exists()

    def test_同じ端末で別の人がオンにしたら付け替える(self, logged_in, user_a, user_b, vapid):
        _subscription(user_b)

        res = self._post(logged_in, "push_subscribe", _subscribe_body())

        assert res.status_code == 200
        subscription = PushSubscription.unscoped.get()
        assert subscription.user == user_a
        assert subscription.company == user_a.company

    def test_同じ人がもう一度登録したら鍵を新しくする(self, logged_in, user_a, vapid):
        old = _subscription(user_a, failure_count=3)
        body = _subscribe_body()

        self._post(logged_in, "push_subscribe", body)

        subscription = PushSubscription.unscoped.get()
        assert subscription.pk == old.pk
        assert subscription.p256dh == body["keys"]["p256dh"]
        assert subscription.failure_count == 0

    def test_消せるのは自分の登録だけ(self, logged_in, user_a, user2, vapid):
        mine = _subscription(user_a, endpoint=ENDPOINT)
        other = _subscription(user2, endpoint="https://fcm.googleapis.com/fcm/send/device-2")

        self._post(logged_in, "push_unsubscribe", {"endpoint": other.endpoint})
        assert PushSubscription.unscoped.filter(pk=other.pk).exists()

        res = self._post(logged_in, "push_unsubscribe", {"endpoint": mine.endpoint})
        assert res.json() == {"ok": True}
        assert not PushSubscription.unscoped.filter(pk=mine.pk).exists()

    def test_ログインしていなければ登録できない(self, client, vapid):
        res = self._post(client, "push_subscribe", _subscribe_body())

        assert res.status_code == 302
        assert not PushSubscription.unscoped.exists()

    def test_GETでは登録しない(self, logged_in, vapid):
        assert logged_in.get(reverse("push_subscribe")).status_code == 405

    def test_鍵が無ければ登録しない(self, logged_in, settings):
        settings.WEBPUSH_VAPID_PRIVATE_KEY = ""

        res = self._post(logged_in, "push_subscribe", _subscribe_body())

        assert res.status_code == 400
        assert "鍵" in res.json()["message"]
        assert not PushSubscription.unscoped.exists()


# ---------------------------------------------------------------------------
# 送り出し
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSendPending:
    def test_まだ送っていない知らせを端末に届ける(self, user_a, vapid, push_service):
        subscription = _subscription(user_a)
        notification = _notification(
            user_a,
            body="この現場の安全作業確認書がまだです。",
            reference_url="/safety/sites/1/ky/2026-09-15/",
        )

        assert send_pending_pushes() == 1

        [call] = push_service.calls
        assert call["url"] == ENDPOINT
        assert call["allow_redirects"] is False
        assert call["headers"]["Content-Encoding"] == "aes128gcm"
        assert call["headers"]["TTL"] == str(12 * 60 * 60)
        assert call["headers"]["Urgency"] == "normal"
        assert call["headers"]["Authorization"].startswith("vapid t=")
        assert _payload(call, subscription) == {
            "title": "【A社ビル新築】今日のKY用紙を記入してください",
            "body": "この現場の安全作業確認書がまだです。",
            "url": reverse("notification_open", args=[notification.pk]),
            "tag": f"kec-notification-{notification.pk}",
        }
        notification.refresh_from_db()
        subscription.refresh_from_db()
        assert notification.pushed_at is not None
        assert subscription.last_success_at is not None

    def test_同じ知らせは二重に送らない(self, user_a, vapid, push_service):
        _subscription(user_a)
        _notification(user_a)

        assert send_pending_pushes() == 1
        assert send_pending_pushes() == 0
        assert len(push_service.calls) == 1

    def test_既読_古い_オンにする前の知らせは送らない(self, user_a, vapid, push_service):
        now = timezone.now()
        old_device = _subscription(user_a, created_at=now - timedelta(hours=8))
        new_device = _subscription(
            user_a, endpoint="https://fcm.googleapis.com/fcm/send/device-new", created_at=now
        )
        read = _notification(user_a, title="既読", is_read=True)
        old = _notification(user_a, title="古い", sent_at=now - timedelta(hours=7))
        before = _notification(user_a, title="1時間前", sent_at=now - timedelta(hours=1))

        send_pending_pushes(now=now)

        # 1時間前の知らせは、8時間前にオンにした端末にだけ届く（今オンにした端末には送らない）
        [call] = push_service.calls
        assert call["url"] == old_device.endpoint != new_device.endpoint
        assert _payload(call, old_device)["title"] == "1時間前"
        read.refresh_from_db()
        old.refresh_from_db()
        before.refresh_from_db()
        assert read.pushed_at is not None
        assert old.pushed_at is None
        assert before.pushed_at is not None

    def test_他の人あての知らせは届けない(self, user_a, user2, vapid, push_service):
        _subscription(user_a)
        _notification(user2)

        assert send_pending_pushes() == 0
        assert push_service.calls == []

    def test_3件までは1件ずつ送る(self, user_a, vapid, push_service):
        subscription = _subscription(user_a)
        first = _notification(user_a, title="1件目")
        second = _notification(user_a, title="2件目", level=Notification.Level.ERROR)

        assert send_pending_pushes() == 2

        payloads = [_payload(call, subscription) for call in push_service.calls]
        assert [p["url"] for p in payloads] == [
            reverse("notification_open", args=[first.pk]),
            reverse("notification_open", args=[second.pk]),
        ]
        assert [call["headers"]["Urgency"] for call in push_service.calls] == ["normal", "high"]

    def test_4件以上はまとめて1通にする(self, user_a, vapid, push_service):
        subscription = _subscription(user_a)
        for i in range(3):
            _notification(user_a, title=f"{i + 1}件目")
        _notification(user_a, title="資格の期限切れ", level=Notification.Level.ERROR)

        assert send_pending_pushes() == 1

        [call] = push_service.calls
        assert _payload(call, subscription) == {
            "title": "新しい通知が4件あります",
            "body": "資格の期限切れ",
            "url": reverse("notification_list"),
            "tag": "kec-notifications",
        }
        assert call["headers"]["Urgency"] == "high"

    @pytest.mark.parametrize("status", [404, 410])
    def test_届かなくなった端末は消す(self, user_a, vapid, push_service, status):
        subscription = _subscription(user_a)
        _notification(user_a)
        _notification(user_a, title="2件目")
        push_service.statuses[ENDPOINT] = status

        assert send_pending_pushes() == 0

        assert not PushSubscription.unscoped.filter(pk=subscription.pk).exists()
        assert len(push_service.calls) == 1

    def test_失敗は数え_続いたら消す(self, user_a, vapid, push_service):
        push_service.statuses[ENDPOINT] = 500
        subscription = _subscription(user_a)
        _notification(user_a)

        send_pending_pushes()
        subscription.refresh_from_db()
        assert subscription.failure_count == 1

        PushSubscription.unscoped.filter(pk=subscription.pk).update(failure_count=4)
        push_service.statuses[ENDPOINT] = requests.ConnectionError("圏外")
        _notification(user_a, title="次の知らせ")
        send_pending_pushes()
        assert not PushSubscription.unscoped.filter(pk=subscription.pk).exists()

    def test_鍵が無ければ何も送らない(self, settings, user_a, push_service):
        settings.WEBPUSH_VAPID_PRIVATE_KEY = ""
        _subscription(user_a)
        notification = _notification(user_a)

        assert send_pending_pushes() == 0

        assert push_service.calls == []
        notification.refresh_from_db()
        assert notification.pushed_at is None

    def test_コマンドで送る(self, user_a, vapid, push_service):
        _subscription(user_a)
        _notification(user_a)
        out = io.StringIO()

        call_command("send_push_notifications", stdout=out)

        assert "1 件" in out.getvalue()
        assert len(push_service.calls) == 1

    def test_送るものが無ければコマンドは何も出さない(self, vapid, push_service):
        out = io.StringIO()

        call_command("send_push_notifications", stdout=out)

        assert out.getvalue() == ""

    def test_鍵の形が違えばコマンドは失敗する(self, settings):
        settings.WEBPUSH_VAPID_PRIVATE_KEY = "abc"

        with pytest.raises(CommandError):
            call_command("send_push_notifications")


# ---------------------------------------------------------------------------
# 画面
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestViews:
    def test_通知を押すと既読にして知らせの画面へ移る(self, logged_in, user_a):
        notification = _notification(user_a, reference_url="/safety/sites/1/ky/2026-09-15/")

        res = logged_in.get(reverse("notification_open", args=[notification.pk]))

        assert res.status_code == 302
        assert res["Location"] == "/safety/sites/1/ky/2026-09-15/"
        notification.refresh_from_db()
        assert notification.is_read

    @pytest.mark.parametrize("url", ["https://evil.example/x", "//evil.example/x", ""])
    def test_外のサイトへは移らない(self, logged_in, user_a, url):
        notification = _notification(user_a, reference_url=url)

        res = logged_in.get(reverse("notification_open", args=[notification.pk]))

        assert res["Location"] == reverse("notification_list")

    def test_他の人の通知は開けない(self, logged_in, user2):
        notification = _notification(user2)

        res = logged_in.get(reverse("notification_open", args=[notification.pk]))

        assert res.status_code == 404
        notification.refresh_from_db()
        assert not notification.is_read

    def test_テスト通知をその場で送る(self, logged_in, user_a, vapid, push_service):
        subscription = _subscription(user_a)

        res = logged_in.post(reverse("push_test"))

        assert res.status_code == 200
        assert res.json()["ok"] is True
        [call] = push_service.calls
        assert _payload(call, subscription)["title"] == "テスト通知"

    def test_送り先が無ければテスト通知を出さない(self, logged_in, vapid, push_service):
        res = logged_in.post(reverse("push_test"))

        assert res.status_code == 400
        assert not Notification.unscoped.filter(title="テスト通知").exists()

    def test_ホームと通知の画面に受け取りの欄が出る(self, logged_in, vapid):
        home = logged_in.get(reverse("dashboard")).content.decode()
        page = logged_in.get(reverse("notification_list")).content.decode()

        assert f'data-public-key="{vapid}"' in home
        assert "data-push-banner" in home
        assert "data-push-panel" in page
        assert "この端末で通知を受け取る" in page

    def test_鍵が無ければ公開鍵は空(self, logged_in, settings):
        settings.WEBPUSH_VAPID_PRIVATE_KEY = ""

        page = logged_in.get(reverse("notification_list")).content.decode()

        assert 'data-public-key=""' in page

    def test_ServiceWorkerが通知を出し_押したら画面を開く(self, client):
        body = client.get("/sw.js").content.decode()

        assert 'addEventListener("push"' in body
        assert "showNotification" in body
        assert 'addEventListener("notificationclick"' in body
        assert f'NOTIFICATIONS_URL = "{reverse("notification_list")}"' in body

    def test_鍵はwebとcronの両方のコンテナに渡す(self):
        compose = (django_settings.BASE_DIR / "docker-compose.yml").read_text(encoding="utf-8")

        assert compose.count("WEBPUSH_VAPID_PRIVATE_KEY: ${WEBPUSH_VAPID_PRIVATE_KEY:-}") == 2


# ---------------------------------------------------------------------------
# モデル
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestModel:
    def test_他社の送り先は見えない(self, company_a, user_a, user_b):
        mine = _subscription(user_a)
        _subscription(user_b, endpoint="https://web.push.apple.com/device-b")

        set_current_company(company_a)
        try:
            assert list(PushSubscription.objects.all()) == [mine]
        finally:
            set_current_company(None)

    def test_変更履歴が残り管理画面に出る(self, user_a):
        subscription = _subscription(user_a)
        subscription.delete()

        assert PushSubscription.history.filter(endpoint=ENDPOINT).count() == 2
        assert isinstance(admin.site._registry[PushSubscription], SimpleHistoryAdmin)
