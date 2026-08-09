import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.costs.forms import BudgetItemForm, ManualCostForm
from apps.costs.models import CostTransaction
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
