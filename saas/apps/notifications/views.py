"""通知センター画面。"""

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.notifications.models import Notification, PushSubscription
from apps.notifications.push import (
    InvalidSubscription,
    clean_subscription,
    push_enabled,
    save_subscription,
    send_pending_pushes,
)
from apps.notifications.services import (
    get_unread_count,
    mark_all_as_read,
    mark_as_read,
    notify,
)

NO_KEY_MESSAGE = "サーバーに通知用の鍵が設定されていないため、スマホへの通知はまだ使えません。"


@login_required
def notification_list(request):
    """通知一覧ページ。フィルタ: module, level, is_read。"""
    qs = Notification.unscoped.filter(recipient=request.user).order_by("-sent_at")

    # フィルタ
    module = request.GET.get("module")
    if module:
        qs = qs.filter(module=module)

    level = request.GET.get("level")
    if level:
        qs = qs.filter(level=level)

    is_read = request.GET.get("is_read")
    if is_read == "false":
        qs = qs.filter(is_read=False)
    elif is_read == "true":
        qs = qs.filter(is_read=True)

    notifications = qs[:100]
    unread_count = get_unread_count(request.user)

    return render(
        request,
        "notifications/list.html",
        {
            "notifications": notifications,
            "unread_count": unread_count,
            "current_module": module,
            "current_level": level,
            "modules": Notification.Module.choices,
        },
    )


def _wants_json(request):
    """画面のボタンではなく、スクリプトからの呼び出しか。"""
    return (
        bool(request.headers.get("HX-Request"))
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )


@login_required
def notification_read(request, pk):
    """通知を既読にする。

    画面の「既読」ボタン（ふつうのフォーム送信）で押したときは通知の一覧に戻す。
    これまでは JSON をそのまま返していたので、画面に {"ok": true} だけが出ていた。
    HTMX・fetch など JSON を期待する呼び出しには、これまでどおり JSON を返す。
    """
    if request.method == "POST":
        mark_as_read(pk, request.user)
    if _wants_json(request):
        return JsonResponse({"ok": True})
    return redirect("notification_list")


@login_required
def notification_open(request, pk):
    """通知を開く（スマホのプッシュ通知を押したとき）。既読にして、知らせの画面へ移る。

    自分あての通知だけ（recipient で絞る）。会社の文脈に関係なく本人のものなので unscoped。
    移り先はこのサイトの中だけ（外のサイトへ飛ばさない）。
    """
    notification = get_object_or_404(Notification.unscoped, pk=pk, recipient=request.user)
    mark_as_read(notification.pk, request.user)
    url = notification.reference_url
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(url)
    return redirect("notification_list")


def _json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return None


@login_required
@require_POST
def push_subscribe(request):
    """この端末の送り先を登録する（ADR-0062。push.js が JSON で送る）。"""
    if not push_enabled():
        return JsonResponse({"ok": False, "message": NO_KEY_MESSAGE}, status=400)
    try:
        endpoint, p256dh, auth = clean_subscription(_json_body(request))
    except InvalidSubscription as exc:
        return JsonResponse({"ok": False, "message": str(exc)}, status=400)
    save_subscription(
        request.user, endpoint, p256dh, auth, request.headers.get("User-Agent", "")
    )
    return JsonResponse({"ok": True})


@login_required
@require_POST
def push_unsubscribe(request):
    """この端末の送り先を消す（「受け取らない」とログアウトのとき）。自分の登録だけ消せる。"""
    data = _json_body(request)
    endpoint = data.get("endpoint") if isinstance(data, dict) else None
    if not isinstance(endpoint, str) or not endpoint:
        return JsonResponse({"ok": False, "message": "送り先がありません。"}, status=400)
    # 1件ずつ消して変更履歴に残す。送り先は会社をまたいで一意なので unscoped（本人で絞る）
    for subscription in PushSubscription.unscoped.filter(user=request.user, endpoint=endpoint):
        subscription.delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def push_test(request):
    """自分にテスト通知を出し、その場でスマホへ送る。届くかを確かめるため。"""
    if not push_enabled():
        return JsonResponse({"ok": False, "message": NO_KEY_MESSAGE}, status=400)
    if not PushSubscription.unscoped.filter(user=request.user).exists():
        return JsonResponse(
            {
                "ok": False,
                "message": "送り先がまだ登録されていません。"
                "「この端末で通知を受け取る」を押してください。",
            },
            status=400,
        )
    notify(
        company=request.user.company,
        recipient=request.user,
        title="テスト通知",
        body="スマホに通知が届くことを確かめるための通知です。",
        module=Notification.Module.SYSTEM,
        reference_url=reverse("notification_list"),
    )
    delivered = send_pending_pushes(recipient=request.user)
    if not delivered:
        return JsonResponse(
            {
                "ok": False,
                "message": "送れませんでした。しばらくしてから、もう一度お試しください。",
            },
            status=502,
        )
    return JsonResponse(
        {"ok": True, "delivered": delivered, "message": "テスト通知を送りました。数秒で届きます。"}
    )


@login_required
def notification_read_all(request):
    """全通知を既読にする。画面から押したときは通知の一覧に戻す。"""
    if request.method == "POST":
        mark_all_as_read(request.user)
    if _wants_json(request):
        return JsonResponse({"ok": True})
    return redirect("notification_list")


@login_required
def notification_badge(request):
    """未読件数バッジ（HTMX polling用）。"""
    count = get_unread_count(request.user)
    return render(
        request,
        "notifications/badge.html",
        {"unread_count": count},
    )


@login_required
def alert_rule_list(request):
    """アラートルール一覧。"""
    from apps.notifications.models import AlertRule
    rules = AlertRule.objects.order_by("alert_type", "threshold_value")
    return render(request, "notifications/alert_rules.html", {"rules": rules})


@login_required
def alert_rule_create(request):
    """アラートルールの作成。"""
    from apps.notifications.forms import AlertRuleForm
    if request.method == "POST":
        form = AlertRuleForm(request.POST)
        if form.is_valid():
            rule = form.save(commit=False)
            rule.company = request.user.company
            rule.created_by = request.user
            rule.save()
            return redirect("alert_rule_list")
    else:
        form = AlertRuleForm()
    return render(request, "notifications/alert_rule_form.html", {
        "form": form, "title": "アラートルールを作成",
    })


@login_required
def alert_rule_edit(request, pk):
    """アラートルールの編集。"""
    from apps.notifications.forms import AlertRuleForm
    from apps.notifications.models import AlertRule
    rule = get_object_or_404(AlertRule, pk=pk)
    if request.method == "POST":
        form = AlertRuleForm(request.POST, instance=rule)
        if form.is_valid():
            form.save()
            return redirect("alert_rule_list")
    else:
        form = AlertRuleForm(instance=rule)
    return render(request, "notifications/alert_rule_form.html", {
        "form": form, "title": "アラートルールを編集",
    })


@login_required
def alert_rule_delete(request, pk):
    """アラートルールの削除。"""
    from apps.notifications.models import AlertRule
    rule = get_object_or_404(AlertRule, pk=pk)
    if request.method == "POST":
        rule.delete()
        return redirect("alert_rule_list")
    return render(request, "notifications/alert_rule_confirm_delete.html", {"rule": rule})
