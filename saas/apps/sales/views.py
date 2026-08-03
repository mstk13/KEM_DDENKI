"""営業管理画面。"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.sales.forms import SalesVisitForm
from apps.sales.models import SalesAttachment, SalesVisit
from apps.sales.services import (
    get_companies_by_industry,
    get_dashboard_stats,
    search_visits,
)


@login_required
def sales_dashboard(request):
    """営業ダッシュボード。"""
    stats = get_dashboard_stats(request.user.company)
    return render(request, "sales/dashboard.html", {"stats": stats})


@login_required
def sales_list(request):
    """営業一覧（検索・フィルタ）。"""
    q = request.GET.get("q", "")
    industry = request.GET.get("industry", "")
    status = request.GET.get("status", "")

    visits = search_visits(request.user.company, q=q, industry=industry, status=status)

    return render(request, "sales/list.html", {
        "visits": visits[:100],
        "q": q,
        "industry": industry,
        "status": status,
        "industry_choices": SalesVisit.INDUSTRY_CHOICES,
        "status_choices": SalesVisit.Status.choices,
    })


@login_required
def sales_by_industry(request):
    """業界から探す。"""
    industry = request.GET.get("industry", "")
    companies = []
    if industry:
        companies = get_companies_by_industry(request.user.company, industry)

    return render(request, "sales/by_industry.html", {
        "industry_choices": SalesVisit.INDUSTRY_CHOICES,
        "selected_industry": industry,
        "companies": companies,
    })


@login_required
def sales_create(request):
    """営業記録の作成。"""
    if request.method == "POST":
        form = SalesVisitForm(request.POST)
        if form.is_valid():
            visit = form.save(commit=False)
            visit.company = request.user.company
            visit.created_by = request.user
            visit.save()

            # ファイル添付
            for f in request.FILES.getlist("attachments"):
                SalesAttachment.unscoped.create(
                    company=request.user.company,
                    visit=visit,
                    file=f,
                    original_name=f.name,
                    file_type=_detect_file_type(f.name),
                )

            messages.success(request, "営業記録を登録しました。")
            return redirect("sales:detail", pk=visit.pk)
    else:
        form = SalesVisitForm()
    return render(request, "sales/form.html", {"form": form, "title": "営業記録を作成"})


@login_required
def sales_detail(request, pk):
    """営業記録の詳細。"""
    visit = get_object_or_404(SalesVisit, pk=pk)
    attachments = visit.attachments.all()
    return render(request, "sales/detail.html", {
        "visit": visit,
        "attachments": attachments,
    })


@login_required
def sales_edit(request, pk):
    """営業記録の編集。"""
    visit = get_object_or_404(SalesVisit, pk=pk)
    if request.method == "POST":
        form = SalesVisitForm(request.POST, instance=visit)
        if form.is_valid():
            form.save()

            for f in request.FILES.getlist("attachments"):
                SalesAttachment.unscoped.create(
                    company=request.user.company,
                    visit=visit,
                    file=f,
                    original_name=f.name,
                    file_type=_detect_file_type(f.name),
                )

            messages.success(request, "営業記録を更新しました。")
            return redirect("sales:detail", pk=visit.pk)
    else:
        form = SalesVisitForm(instance=visit)
    return render(request, "sales/form.html", {"form": form, "title": "営業記録を編集"})


def _detect_file_type(filename):
    """ファイル名から種別を推定する。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf":
        return "pdf"
    if ext in ("png", "jpg", "jpeg", "webp", "gif"):
        return "image"
    return "other"
