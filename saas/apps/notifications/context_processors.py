"""通知まわりの値を、どの画面のテンプレートからも使えるようにする。"""

from apps.notifications.push import vapid_public_key


def web_push(request):
    """スマホへのプッシュ通知（ADR-0062）で端末に渡す公開鍵。

    サーバーに鍵が無ければ空。push.js が「まだ使えません」と出す。
    """
    return {"WEBPUSH_PUBLIC_KEY": vapid_public_key()}
