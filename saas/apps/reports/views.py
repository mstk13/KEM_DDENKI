from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.reports.forms import DailyReportForm
from apps.reports.models import DailyReport, SafetyRecord, SafetyTemplate
from apps.reports.services import (
    alert_safety_incomplete,
    approve_report,
    check_safety_completion,
    get_monthly_summary,
)


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
        approve_report(report, approved_by=request.user)
        messages.success(
            request,
            f"{report.worker} の日報を承認し、労務費を計上しました。",
        )
    return redirect("reports:list")


@login_required
def safety_check(request):
    """安全書類チェック画面。"""
    from datetime import date

    from apps.sites.models import Site

    sites = Site.objects.filter(status="active")
    selected_site_id = request.GET.get("site")
    check_date = request.GET.get("date", str(date.today()))

    result = None
    selected_site = None
    if selected_site_id:
        selected_site = get_object_or_404(Site, pk=selected_site_id)
        result = check_safety_completion(selected_site, check_date)

    # 一括アラート送信
    if request.method == "POST" and selected_site:
        alert_safety_incomplete(
            request.user.company, selected_site, check_date,
        )
        messages.success(request, "未記入者にアラートを送信しました。")
        return redirect(f"/reports/safety/?site={selected_site_id}&date={check_date}")

    return render(request, "reports/safety_check.html", {
        "sites": sites,
        "selected_site": selected_site,
        "check_date": check_date,
        "result": result,
    })


@login_required
def safety_complete(request, pk):
    """安全書類を記入済みにする。"""
    from django.utils import timezone

    record = get_object_or_404(SafetyRecord, pk=pk)
    record.completed = True
    record.completed_at = timezone.now()
    record.save()
    messages.success(request, f"{record.worker.name}の{record.template.name}を記入済みにしました。")

    return redirect(
        f"/reports/safety/?site={record.template.site_id}&date={record.record_date}"
    )


@login_required
def monthly_summary(request):
    """月別集計画面。"""
    from datetime import date

    year = int(request.GET.get("year", date.today().year))
    month = int(request.GET.get("month", date.today().month))

    summary = get_monthly_summary(request.user.company, year, month)

    return render(request, "reports/monthly_summary.html", {
        "summary": summary,
        "year": year,
        "month": month,
    })
