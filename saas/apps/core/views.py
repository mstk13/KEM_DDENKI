from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from apps.permissions.decorators import module_permission_required
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import Worker


@login_required
def dashboard(request):
    today = timezone.now().date()
    context = {
        "active_sites": Site.objects.filter(status=Site.Status.IN_PROGRESS).count(),
        "today_reports": DailyReport.objects.filter(report_date=today).count(),
        "pending_reports": DailyReport.objects.filter(
            status=DailyReport.Status.SUBMITTED
        ).count(),
        "active_workers": Worker.objects.filter(is_active=True).count(),
        "recent_sites": Site.objects.filter(
            status=Site.Status.IN_PROGRESS
        ).select_related("customer")[:5],
        "recent_reports": DailyReport.objects.select_related(
            "worker", "site"
        ).order_by("-report_date", "-created_at")[:10],
    }
    return render(request, "dashboard.html", context)


@login_required
@module_permission_required("settings", "admin")
def audit_log(request):
    """全データの変更ログを閲覧する。simple_historyの全Historicalモデルを横断検索。"""
    # 検索パラメータ
    model_filter = request.GET.get("model", "")
    user_filter = request.GET.get("user", "")
    page = int(request.GET.get("page", 1))
    per_page = 50

    # Historical モデル一覧を取得
    historical_models = {}
    for model in apps.get_models():
        if model.__name__.startswith("Historical") and hasattr(model, "history_date"):
            label = model._meta.label.split(".")[-1].replace("Historical", "")
            historical_models[model._meta.label] = {
                "model": model,
                "display": label,
            }

    # 対象モデルの履歴を取得
    records = []
    if model_filter and model_filter in historical_models:
        # 特定モデルのみ
        target_models = {model_filter: historical_models[model_filter]}
    else:
        target_models = historical_models

    for label, info in target_models.items():
        qs = info["model"].objects.all()

        # テナント分離: company フィールドがある場合
        if hasattr(info["model"], "company_id"):
            qs = qs.filter(company=request.user.company)

        if user_filter:
            qs = qs.filter(history_user__username__icontains=user_filter)

        for rec in qs.order_by("-history_date")[:200]:
            records.append({
                "model_name": info["display"],
                "history_date": rec.history_date,
                "history_type": rec.get_history_type_display(),
                "history_user": getattr(rec, "history_user", None),
                "object_id": rec.pk,
                "object_str": str(rec),
            })

    # 日付順ソート
    records.sort(key=lambda x: x["history_date"], reverse=True)

    # ページネーション
    total = len(records)
    start = (page - 1) * per_page
    page_records = records[start:start + per_page]
    total_pages = (total + per_page - 1) // per_page

    model_choices = sorted(
        [(k, v["display"]) for k, v in historical_models.items()],
        key=lambda x: x[1],
    )

    return render(request, "core/audit_log.html", {
        "records": page_records,
        "model_choices": model_choices,
        "model_filter": model_filter,
        "user_filter": user_filter,
        "page": page,
        "total_pages": total_pages,
        "total": total,
    })
