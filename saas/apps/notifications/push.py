"""スマホへのプッシュ通知（Web Push）。ADR-0062。

ベルに届く通知（Notification）を、オンにしている端末へも送る。
新しい依存は足さず、すでに入っている cryptography と requests で送る。

- 中身の暗号化: RFC 8291（aes128gcm / RFC 8188）。端末の鍵で暗号化し、プッシュサービスには読めない
- 送り手の証明: RFC 8292（VAPID）。サーバーの秘密鍵で署名した JWT を付ける
- 暗号化が正しいことは RFC 8291 の例の値で確かめている（tests/test_web_push.py）

送り出しは cron コンテナの send_push_notifications が1分ごとに行う
（画面の操作を待たせないため。scripts/scheduler.sh）。
"""

import base64
import functools
import json
import os
import time
from collections import defaultdict
from datetime import timedelta
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.notifications.models import Notification, PushSubscription

# 暗号化した中身を1つのレコードに収める大きさ（RFC 8188）
RECORD_SIZE = 4096
# プッシュサービスが端末に届けるのを待つ長さ。朝の知らせが翌日に届いても意味が無いので半日
TTL_SECONDS = 12 * 60 * 60
# VAPID の署名の有効期限（RFC 8292 は24時間以内）
VAPID_EXPIRES_SECONDS = 12 * 60 * 60
REQUEST_TIMEOUT_SECONDS = 10
# 続けてこの回数失敗した送り先は消す（端末を替えた・ブラウザを消したなど）
MAX_FAILURES = 5
# これより古い知らせは送らない。
# cron が止まっていた後や、使い始めた日に、古い知らせが一度に届かないように
PUSH_MAX_AGE = timedelta(hours=6)
# 1人に一度にこれより多く溜まっていたら、1件ずつではなく「N件あります」の1通にまとめる
SUMMARY_THRESHOLD = 3
TITLE_LIMIT = 100
BODY_LIMIT = 200

# 送り先として受け付けるプッシュサービス。端末から届いた URL へサーバーが POST するので、
# 社内のアドレス（db:5432 など）へ送らされないよう、主なブラウザのサービスだけに限る。
ALLOWED_PUSH_HOSTS = (
    "fcm.googleapis.com",  # Chrome・Android・Edge（Chromium）
    "push.apple.com",  # Safari・iPhone（web.push.apple.com）
    "push.services.mozilla.com",  # Firefox
    "notify.windows.com",  # Windows の Edge（wns2-xxx.notify.windows.com）
)


class InvalidSubscription(ValueError):
    """端末から届いた送り先の形が正しくない。"""


# ---------------------------------------------------------------------------
# 鍵と暗号化
# ---------------------------------------------------------------------------


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    text = text.strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _public_bytes(public_key: ec.EllipticCurvePublicKey) -> bytes:
    return public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def generate_vapid_keys() -> tuple[str, str]:
    """(秘密鍵, 公開鍵) を base64url で返す。秘密鍵は32バイト、公開鍵は65バイト。"""
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_value = private_key.private_numbers().private_value.to_bytes(32, "big")
    return b64url_encode(private_value), b64url_encode(_public_bytes(private_key.public_key()))


def load_private_key(text: str) -> ec.EllipticCurvePrivateKey:
    """generate_vapid_keys で作った秘密鍵を読む。形が違えば ValueError。"""
    raw = b64url_decode(text)
    if len(raw) != 32:
        raise ValueError("VAPID の秘密鍵は32バイトを base64url で書いたものにしてください")
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


@functools.lru_cache(maxsize=4)
def _vapid_keys(private_text: str) -> tuple[ec.EllipticCurvePrivateKey, str] | None:
    try:
        private_key = load_private_key(private_text)
    except ValueError:
        return None
    return private_key, b64url_encode(_public_bytes(private_key.public_key()))


def push_enabled() -> bool:
    """サーバーに正しい通知用の鍵があるか。無ければプッシュ通知は出さない（ベルはそのまま）。"""
    return _vapid_keys(settings.WEBPUSH_VAPID_PRIVATE_KEY) is not None


def vapid_public_key() -> str:
    """端末に渡す公開鍵。秘密鍵から計算するので、.env には秘密鍵だけ置けばよい。"""
    keys = _vapid_keys(settings.WEBPUSH_VAPID_PRIVATE_KEY)
    return keys[1] if keys else ""


def encrypt(
    payload: bytes,
    user_public_key: str,
    auth_secret: str,
    *,
    salt: bytes | None = None,
    server_private_key: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    """端末だけが読めるように中身を暗号化する（RFC 8291 の aes128gcm）。

    salt と server_private_key は毎回新しく作る。引数はテストで RFC の例の値を入れるためにある。
    """
    ua_public = b64url_decode(user_public_key)
    auth = b64url_decode(auth_secret)
    server_private_key = server_private_key or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    as_public = _public_bytes(server_private_key.public_key())

    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    ecdh_secret = server_private_key.exchange(ec.ECDH(), peer)
    key_info = b"WebPush: info\x00" + ua_public + as_public
    ikm = HKDF(algorithm=hashes.SHA256(), length=32, salt=auth, info=key_info).derive(
        ecdh_secret
    )
    cek = HKDF(
        algorithm=hashes.SHA256(), length=16, salt=salt, info=b"Content-Encoding: aes128gcm\x00"
    ).derive(ikm)
    nonce = HKDF(
        algorithm=hashes.SHA256(), length=12, salt=salt, info=b"Content-Encoding: nonce\x00"
    ).derive(ikm)

    # 1つのレコードに収める。0x02 は「最後のレコード」の印（RFC 8188）
    record = payload + b"\x02"
    if len(record) + 16 > RECORD_SIZE:
        raise ValueError("通知の中身が大きすぎます")
    ciphertext = AESGCM(cek).encrypt(nonce, record, None)
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + ciphertext


def vapid_headers(endpoint: str, *, now: int | None = None) -> dict[str, str]:
    """送り手を証明する Authorization ヘッダ（RFC 8292）。"""
    keys = _vapid_keys(settings.WEBPUSH_VAPID_PRIVATE_KEY)
    if keys is None:
        raise ValueError("通知用の鍵（WEBPUSH_VAPID_PRIVATE_KEY）が設定されていません")
    private_key, public_key = keys
    parts = urlsplit(endpoint)
    issued = int(time.time()) if now is None else now
    header = {"typ": "JWT", "alg": "ES256"}
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": issued + VAPID_EXPIRES_SECONDS,
        "sub": settings.WEBPUSH_VAPID_SUBJECT,
    }
    signing_input = ".".join(
        b64url_encode(json.dumps(part, separators=(",", ":")).encode())
        for part in (header, claims)
    )
    der = private_key.sign(signing_input.encode("ascii"), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = b64url_encode(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return {"Authorization": f"vapid t={signing_input}.{signature}, k={public_key}"}


# ---------------------------------------------------------------------------
# 送り先の登録
# ---------------------------------------------------------------------------


def is_allowed_endpoint(endpoint: str) -> bool:
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or port not in (None, 443):
        return False
    if parts.username or parts.password:
        return False
    return any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_PUSH_HOSTS)


def clean_subscription(data) -> tuple[str, str, str]:
    """ブラウザの PushSubscription.toJSON() の形を確かめ、(endpoint, p256dh, auth) を返す。"""
    if not isinstance(data, dict):
        raise InvalidSubscription("送り先の形が正しくありません")
    endpoint = data.get("endpoint")
    keys = data.get("keys")
    if not isinstance(endpoint, str) or not isinstance(keys, dict):
        raise InvalidSubscription("送り先の形が正しくありません")
    if len(endpoint) > 1000 or not is_allowed_endpoint(endpoint):
        raise InvalidSubscription("このブラウザの送り先には対応していません")
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")
    if not isinstance(p256dh, str) or not isinstance(auth, str):
        raise InvalidSubscription("端末の鍵がありません")
    try:
        ua_public = b64url_decode(p256dh)
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
        auth_bytes = b64url_decode(auth)
    except ValueError as exc:
        raise InvalidSubscription("端末の鍵の形が正しくありません") from exc
    if len(ua_public) != 65 or len(auth_bytes) != 16:
        raise InvalidSubscription("端末の鍵の形が正しくありません")
    return endpoint, p256dh, auth


def save_subscription(user, endpoint: str, p256dh: str, auth: str, user_agent: str = ""):
    """この端末の送り先を user に登録する。

    送り先は会社をまたいで一意なので unscoped で探す。前に別の人（別の会社の人も）が
    この端末でオンにしていたら、その人の登録を消して付け替える
    （その人あての知らせがこの端末に届かないように）。
    """
    existing = PushSubscription.unscoped.filter(endpoint=endpoint).first()
    if existing is not None and existing.user_id != user.pk:
        existing.delete()
        existing = None
    if existing is not None:
        existing.p256dh = p256dh
        existing.auth = auth
        existing.user_agent = user_agent[:300]
        existing.failure_count = 0
        existing.save(
            update_fields=["p256dh", "auth", "user_agent", "failure_count", "updated_at"]
        )
        return existing
    return PushSubscription.unscoped.create(
        company=user.company,
        user=user,
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        user_agent=user_agent[:300],
        created_by=user,
    )


# ---------------------------------------------------------------------------
# 送る
# ---------------------------------------------------------------------------


def _truncate(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_payloads(notifications) -> list[tuple[dict, str]]:
    """端末に送る中身と急ぎ具合（Urgency）の組。多ければ1通にまとめる。"""
    items = list(notifications)
    if not items:
        return []
    if len(items) > SUMMARY_THRESHOLD:
        urgent = any(n.level == Notification.Level.ERROR for n in items)
        payload = {
            "title": f"新しい通知が{len(items)}件あります",
            "body": _truncate(items[-1].title, BODY_LIMIT),
            "url": reverse("notification_list"),
            "tag": "kec-notifications",
        }
        return [(payload, "high" if urgent else "normal")]
    return [
        (
            {
                "title": _truncate(n.title, TITLE_LIMIT),
                "body": _truncate(n.body, BODY_LIMIT),
                "url": reverse("notification_open", args=[n.pk]),
                "tag": f"kec-notification-{n.pk}",
            },
            "high" if n.level == Notification.Level.ERROR else "normal",
        )
        for n in items
    ]


def send(subscription, payload: dict, *, urgency: str = "normal") -> int | None:
    """1つの端末へ送る。プッシュサービスの応答コードを返す（通信できなければ None）。"""
    body = encrypt(
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        subscription.p256dh,
        subscription.auth,
    )
    headers = {
        **vapid_headers(subscription.endpoint),
        "TTL": str(TTL_SECONDS),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "Urgency": urgency,
    }
    try:
        response = requests.post(
            subscription.endpoint,
            data=body,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except requests.RequestException:
        return None
    return response.status_code


def deliver(subscription, payload: dict, *, urgency: str = "normal") -> bool:
    """送って、結果を送り先に残す。届かなくなった送り先は消す。

    成功・失敗の回数は update() で書く。届けるたびに変更履歴を増やさないため。
    """
    if not is_allowed_endpoint(subscription.endpoint):
        subscription.delete()
        return False
    try:
        status = send(subscription, payload, urgency=urgency)
    except ValueError:
        # 端末の鍵が壊れている。直らないので消す
        subscription.delete()
        return False
    records = PushSubscription.unscoped.filter(pk=subscription.pk)
    if status is not None and 200 <= status < 300:
        records.update(last_success_at=timezone.now(), failure_count=0)
        return True
    if status in (404, 410):
        # 端末で通知をやめた・アプリを消した（プッシュサービスが「もう無い」と返す）
        subscription.delete()
        return False
    failures = subscription.failure_count + 1
    if failures >= MAX_FAILURES:
        subscription.delete()
    else:
        records.update(failure_count=failures)
        subscription.failure_count = failures
    return False


def send_pending_pushes(*, now=None, recipient=None) -> int:
    """まだ送っていない知らせを、オンにしている端末へ送る。届けた数を返す。

    cron から全社をまとめて呼ぶ（テナントの文脈が無い）ので unscoped で探す。
    先に「送った」印（この回だけの時刻）を付けてから送る。途中で落ちても、
    次の回に同じ知らせを二重に送らない。
    """
    if not push_enabled():
        return 0
    now = now or timezone.now()
    pending = Notification.unscoped.filter(
        pushed_at__isnull=True, sent_at__gte=now - PUSH_MAX_AGE
    )
    if recipient is not None:
        pending = pending.filter(recipient=recipient)
    ids = list(pending.values_list("pk", flat=True))
    if not ids:
        return 0
    Notification.unscoped.filter(pk__in=ids, pushed_at__isnull=True).update(pushed_at=now)

    by_user = defaultdict(list)
    claimed = Notification.unscoped.filter(pk__in=ids, pushed_at=now, is_read=False)
    for notification in claimed.order_by("sent_at", "pk"):
        by_user[notification.recipient_id].append(notification)

    delivered = 0
    for subscription in PushSubscription.unscoped.filter(user_id__in=list(by_user)):
        # 端末でオンにする前の知らせは送らない
        items = [n for n in by_user[subscription.user_id] if n.sent_at >= subscription.created_at]
        for payload, urgency in build_payloads(items):
            if deliver(subscription, payload, urgency=urgency):
                delivered += 1
            elif not PushSubscription.unscoped.filter(pk=subscription.pk).exists():
                break
    return delivered
