"""通知センター画面。"""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from apps.notifications.models import Notification
from apps.notifications.services import get_unread_count, mark_all_as_read, mark_as_read


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


@login_required
def notification_read(request, pk):
    """通知を既読にする（HTMX対応）。"""
    if request.method == "POST":
        mark_as_read(pk, request.user)
        if request.headers.get("HX-Request"):
            return JsonResponse({"ok": True})
    return JsonResponse({"ok": True})


@login_required
def notification_read_all(request):
    """全通知を既読にする。"""
    if request.method == "POST":
        mark_all_as_read(request.user)
        if request.headers.get("HX-Request"):
            return JsonResponse({"ok": True})
    return JsonResponse({"ok": True})


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
    return render(request, "notifications/alert_rule_form.html", {"form": form, "title": "アラートルールを作成"})


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
    return render(request, "notifications/alert_rule_form.html", {"form": form, "title": "アラートルールを編集"})


@login_required
def alert_rule_delete(request, pk):
    """アラートルールの削除。"""
    from apps.notifications.models import AlertRule
    rule = get_object_or_404(AlertRule, pk=pk)
    if request.method == "POST":
        rule.delete()
        return redirect("alert_rule_list")
    return render(request, "notifications/alert_rule_confirm_delete.html", {"rule": rule})
