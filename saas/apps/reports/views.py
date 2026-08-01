from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.costs.services import create_labor_cost_from_report
from apps.reports.forms import DailyReportForm
from apps.reports.models import DailyReport


@login_required
def report_list(request):
    reports = DailyReport.objects.select_related(
        "worker", "site", "work_type"
    ).order_by("-report_date", "-created_at")
    return render(request, "reports/list.html", {"reports": reports})


@login_required
def report_create(request):
    if request.method == "POST":
        form = DailyReportForm(request.POST, company=request.user.company)
        if form.is_valid():
            report = form.save(commit=False)
            report.company = request.user.company
            report.created_by = request.user
            if request.POST.get("action") == "submit":
                report.status = DailyReport.Status.SUBMITTED
            report.save()
            messages.success(request, "日報を保存しました。")
            return redirect("reports:list")
    else:
        form = DailyReportForm(company=request.user.company)
    return render(request, "reports/form.html", {"form": form})


@login_required
def report_edit(request, pk):
    report = get_object_or_404(DailyReport, pk=pk)
    if request.method == "POST":
        form = DailyReportForm(
            request.POST, instance=report, company=request.user.company,
        )
        if form.is_valid():
            report = form.save(commit=False)
            if request.POST.get("action") == "submit":
                report.status = DailyReport.Status.SUBMITTED
            report.save()
            messages.success(request, "日報を更新しました。")
            return redirect("reports:list")
    else:
        form = DailyReportForm(instance=report, company=request.user.company)
    return render(request, "reports/form.html", {"form": form})


@login_required
def report_approve(request, pk):
    report = get_object_or_404(DailyReport, pk=pk)
    if report.status == DailyReport.Status.SUBMITTED:
        report.status = DailyReport.Status.APPROVED
        report.save()
        create_labor_cost_from_report(report)
        messages.success(
            request,
            f"{report.worker} の日報を承認し、労務費を計上しました。",
        )
    return redirect("reports:list")
