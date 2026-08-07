import datetime

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.sales.forms import SalesVisitForm
from apps.sales.models import SalesVisit


@login_required
def visit_list(request):
    qs = SalesVisit.objects.order_by("-created_at")

    q = request.GET.get("q", "").strip()
    industry = request.GET.get("industry", "").strip()
    status = request.GET.get("status", "").strip()

    if q:
        qs = qs.filter(
            Q(company_name__icontains=q)
            | Q(rep_name__icontains=q)
            | Q(business_overview__icontains=q)
        )
    if industry:
        qs = qs.filter(industry=industry)
    if status:
        qs = qs.filter(status=status)

    return render(request, "sales/list.html", {
        "visits": qs,
        "q": q,
        "industry": industry,
        "status": status,
        "industry_choices": SalesVisit.Industry.choices,
        "status_choices": SalesVisit.Status.choices,
    })


@login_required
def visit_create(request):
    if request.method == "POST":
        form = SalesVisitForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.company = request.user.company
            obj.created_by = request.user
            obj.save()
            return redirect("sales:visit_detail", pk=obj.pk)
    else:
        form = SalesVisitForm()
    return render(request, "sales/form.html", {"form": form})


@login_required
def visit_detail(request, pk):
    visit = get_object_or_404(SalesVisit, pk=pk)
    return render(request, "sales/detail.html", {"visit": visit})


@login_required
def visit_edit(request, pk):
    visit = get_object_or_404(SalesVisit, pk=pk)
    if request.method == "POST":
        form = SalesVisitForm(request.POST, instance=visit)
        if form.is_valid():
            form.save()
            return redirect("sales:visit_detail", pk=visit.pk)
    else:
        form = SalesVisitForm(instance=visit)
    return render(request, "sales/form.html", {"form": form})


@login_required
def visit_delete(request, pk):
    visit = get_object_or_404(SalesVisit, pk=pk)
    if request.method == "POST":
        visit.delete()
        return redirect("sales:visit_list")
    return render(request, "sales/detail.html", {"visit": visit, "confirm_delete": True})


@login_required
def dashboard(request):
    qs = SalesVisit.objects.all()
    today = datetime.date.today()
    first_of_month = today.replace(day=1)

    total = qs.count()
    this_month = qs.filter(created_at__date__gte=first_of_month).count()
    action_required = qs.filter(status__in=["下書き", "対応中"]).count()

    # Industry distribution
    industry_data = (
        qs.values("industry")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    # Status distribution
    status_data = (
        qs.values("status")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    # Recent visits
    recent = qs.order_by("-created_at")[:10]

    return render(request, "sales/dashboard.html", {
        "total": total,
        "this_month": this_month,
        "action_required": action_required,
        "industry_data": list(industry_data),
        "status_data": list(status_data),
        "recent": recent,
        "industry_choices": dict(SalesVisit.Industry.choices),
        "status_choices": dict(SalesVisit.Status.choices),
    })


@login_required
def industry_browse(request):
    selected_industry = request.GET.get("industry", "").strip()
    selected_company = request.GET.get("company", "").strip()

    # Get all industries with counts
    industry_data = (
        SalesVisit.objects.values("industry")
        .annotate(count=Count("id"))
        .order_by("industry")
    )

    companies = []
    records = []

    if selected_industry:
        # Get companies within selected industry
        companies = (
            SalesVisit.objects.filter(industry=selected_industry)
            .values("company_name")
            .annotate(count=Count("id"))
            .order_by("company_name")
        )

    if selected_company:
        # Get records for selected company in selected industry
        records = SalesVisit.objects.filter(
            industry=selected_industry,
            company_name=selected_company,
        ).order_by("-visit_date")

    return render(request, "sales/industry_browse.html", {
        "industry_data": industry_data,
        "companies": companies,
        "records": records,
        "selected_industry": selected_industry,
        "selected_company": selected_company,
        "industry_choices": dict(SalesVisit.Industry.choices),
    })
