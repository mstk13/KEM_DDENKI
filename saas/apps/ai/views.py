import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.ai.models import AIFeedback, AILog


@login_required
def ai_log_list(request):
    """AI実行ログ一覧。タスク種別・モデルでフィルタ可能。"""
    logs = AILog.objects.select_related("site", "requested_by").order_by(
        "-created_at"
    )

    task_type = request.GET.get("task_type")
    if task_type:
        logs = logs.filter(task_type=task_type)

    model_used = request.GET.get("model_used")
    if model_used:
        logs = logs.filter(model_used=model_used)

    logs = logs[:100]

    return render(request, "ai/log_list.html", {
        "logs": logs,
        "task_type_choices": AILog.TaskType.choices,
        "model_choices": AILog.ModelType.choices,
        "selected_task_type": task_type,
        "selected_model": model_used,
    })


@login_required
def ai_feedback_create(request, pk):
    """AI出力へのフィードバック登録。"""
    ai_log = get_object_or_404(AILog, pk=pk)

    if request.method == "POST":
        rating = int(request.POST.get("rating", 3))
        is_adopted = request.POST.get("is_adopted") == "on"
        comment = request.POST.get("comment", "")

        AIFeedback.objects.update_or_create(
            ai_log=ai_log,
            defaults={
                "company": ai_log.company,
                "rating": rating,
                "is_adopted": is_adopted,
                "comment": comment,
                "rated_by": request.user,
                "created_by": request.user,
            },
        )
        messages.success(request, "フィードバックを記録しました。")
        return redirect("ai:log_list")

    return render(request, "ai/feedback_form.html", {"ai_log": ai_log})


@login_required
def ai_dashboard(request):
    """AI利用状況ダッシュボード。月次コスト・利用頻度・評価を表示。"""
    # 月別利用統計
    monthly_stats = list(
        AILog.objects.annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(
            call_count=Count("id"),
            total_cost=Sum("cost_usd"),
            avg_latency=Avg("latency_ms"),
        )
        .order_by("-month")[:12]
    )

    # タスク種別ごとの統計
    task_stats = list(
        AILog.objects.values("task_type")
        .annotate(
            call_count=Count("id"),
            total_cost=Sum("cost_usd"),
            avg_latency=Avg("latency_ms"),
        )
        .order_by("-call_count")
    )

    # フィードバック統計
    feedback_stats = AIFeedback.objects.aggregate(
        avg_rating=Avg("rating"),
        total_feedbacks=Count("id"),
        adopted_count=Count("id", filter=Q(is_adopted=True)),
    )

    return render(request, "ai/dashboard.html", {
        "monthly_stats": monthly_stats,
        "task_stats": task_stats,
        "feedback_stats": feedback_stats,
    })
