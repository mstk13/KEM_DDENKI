import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.costs.forms import BudgetItemForm, ManualCostForm
from apps.costs.models import CostAccessGrant, CostTransaction
from apps.costs.services import get_monthly_cost_trend, get_site_cost_summary
from apps.permissions.decorators import module_permission_required
from apps.sites.models import Site


@login_required
@module_permission_required("costs", "read")
def cost_list(request):
    """原価一覧（現場ごとの概要）。"""
    sites = Site.objects.filter(
        status__in=[Site.Status.IN_PROGRESS, Site.Status.COMPLETED],
    )

    site_summaries = []
    for site in sites:
        summary = get_site_cost_summary(site)
        # アラートレベル判定
        pct = summary["consumption_pct"]
        if pct >= 100:
            alert_level = "error"
        elif pct >= 90:
            alert_level = "danger"
        elif pct >= 80:
            alert_level = "warning"
        elif pct >= 75:
            alert_level = "caution"
        else:
            alert_level = "normal"

        site_summaries.append({
            "site": site,
            "alert_level": alert_level,
            **summary,
        })

    return render(request, "costs/list.html", {
        "site_summaries": site_summaries,
    })


@login_required
@module_permission_required("costs", "read")
def cost_detail(request, site_id):
    """現場別の原価ダッシュボード。グラフ・区分別消化率を表示。"""
    site = get_object_or_404(Site, pk=site_id)
    summary = get_site_cost_summary(site)
    trend = get_monthly_cost_trend(site)

    transactions = CostTransaction.objects.filter(
        site=site,
    ).select_related(
        "work_type", "cost_category",
    ).order_by("-transaction_date")[:30]

    return render(request, "costs/detail.html", {
        "site": site,
        "summary": summary,
        "trend_json": json.dumps(trend, ensure_ascii=False),
        "transactions": transactions,
    })


@login_required
@module_permission_required("costs", "read")
def cost_chart_data(request, site_id):
    """Chart.js用のJSONデータを返す（HTMX/Ajax用）。"""
    site = get_object_or_404(Site, pk=site_id)
    trend = get_monthly_cost_trend(site)
    return JsonResponse(trend)


@login_required
@module_permission_required("costs", "write")
def budget_create(request, site_id):
    """予算項目の追加。"""
    site = get_object_or_404(Site, pk=site_id)
    if request.method == "POST":
        form = BudgetItemForm(request.POST, company=request.user.company)
        if form.is_valid():
            item = form.save(commit=False)
            item.site = site
            item.company = request.user.company
            item.created_by = request.user
            item.save()
            messages.success(request, "予算項目を追加しました。")
            return redirect("costs:detail", site_id=site.pk)
    else:
        form = BudgetItemForm(company=request.user.company)
    return render(request, "costs/budget_form.html", {"form": form, "site": site})


@login_required
@module_permission_required("costs", "write")
def manual_cost_create(request):
    """手動原価入力（外注費・経費）。"""
    if request.method == "POST":
        form = ManualCostForm(request.POST, company=request.user.company)
        if form.is_valid():
            tx = form.save(commit=False)
            tx.company = request.user.company
            tx.created_by = request.user
            tx.save()
            messages.success(request, "原価データを登録しました。")
            return redirect("costs:list")
    else:
        form = ManualCostForm(company=request.user.company)
    return render(request, "costs/manual_cost_form.html", {"form": form})


# ── 原価アクセス管理 ──


@login_required
@module_permission_required("costs", "admin")
def cost_access_list(request):
    """原価モジュールへのアクセス許可を管理する。"""
    User = __import__("django.contrib.auth", fromlist=["get_user_model"]).get_user_model()
    company = request.user.company

    grants = CostAccessGrant.unscoped.filter(
        company=company,
    ).select_related("user", "granted_by")

    # 社員番号Gで始まるユーザー一覧（自動アクセス対象）
    auto_access_users = User.objects.filter(
        company=company,
        employee_no__regex=r"^[Gg]",
    )

    # 追加可能なユーザー候補（まだ許可されておらず、自動対象でもない）
    granted_user_ids = grants.values_list("user_id", flat=True)
    auto_user_ids = auto_access_users.values_list("id", flat=True)
    exclude_ids = set(granted_user_ids) | set(auto_user_ids)
    available_users = User.objects.filter(
        company=company,
    ).exclude(id__in=exclude_ids).order_by("employee_no", "last_name")

    return render(request, "costs/access_list.html", {
        "grants": grants,
        "auto_access_users": auto_access_users,
        "available_users": available_users,
    })


@login_required
@module_permission_required("costs", "admin")
def cost_access_grant(request):
    """ユーザーに原価アクセスを付与する。"""
    if request.method == "POST":
        User = __import__("django.contrib.auth", fromlist=["get_user_model"]).get_user_model()
        user_id = request.POST.get("user_id")
        memo = request.POST.get("memo", "")
        try:
            target_user = User.objects.get(pk=user_id, company=request.user.company)
        except User.DoesNotExist:
            messages.error(request, "ユーザーが見つかりません。")
            return redirect("costs:access_list")

        CostAccessGrant.unscoped.get_or_create(
            company=request.user.company,
            user=target_user,
            defaults={
                "granted_by": request.user,
                "memo": memo,
                "created_by": request.user,
            },
        )
        messages.success(request, f"{target_user} にアクセス権を付与しました。")
    return redirect("costs:access_list")


@login_required
@module_permission_required("costs", "admin")
def cost_access_revoke(request, pk):
    """原価アクセス許可を取り消す。"""
    if request.method == "POST":
        grant = get_object_or_404(
            CostAccessGrant.unscoped, pk=pk, company=request.user.company,
        )
        user_name = str(grant.user)
        grant.delete()
        messages.success(request, f"{user_name} のアクセス権を取り消しました。")
    return redirect("costs:access_list")
