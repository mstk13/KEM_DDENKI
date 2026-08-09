import datetime
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render

from apps.attendance.forms import (
    AttendEntryFormSet,
    AttendReportForm,
    AttendSettingsForm,
)
from apps.attendance.models import AttendEntry, AttendReport, AttendSettings
from apps.attendance.utils import calc_attendance


@login_required
def report_list(request):
    qs = AttendReport.objects.order_by("-report_date")

    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    site = request.GET.get("site", "").strip()
    status = request.GET.get("status", "").strip()

    if date_from:
        qs = qs.filter(report_date__gte=date_from)
    if date_to:
        qs = qs.filter(report_date__lte=date_to)
    if site:
        qs = qs.filter(site_name__icontains=site)
    if status:
        qs = qs.filter(status=status)

    return render(request, "attendance/report_list.html", {
        "reports": qs,
        "date_from": date_from,
        "date_to": date_to,
        "site": site,
        "status": status,
        "status_choices": AttendReport.Status.choices,
    })


@login_required
def report_create(request):
    settings_dict = AttendSettings.get_settings_dict(request.user.company)
    if request.method == "POST":
        form = AttendReportForm(request.POST)
        formset = AttendEntryFormSet(request.POST, prefix="entries")
        if form.is_valid() and formset.is_valid():
            report = form.save(commit=False)
            report.company = request.user.company
            report.created_by = request.user
            report.save()
            entries = formset.save(commit=False)
            for entry in entries:
                entry.report = report
                entry.company = request.user.company
                entry.created_by = request.user
                # 時間計算
                result = calc_attendance(
                    entry.start_time, entry.end_time,
                    entry.break_minutes, settings_dict,
                )
                entry.early_minutes = result["early"]
                entry.normal_minutes = result["normal"]
                entry.overtime_minutes = result["overtime"]
                entry.total_minutes = result["total"]
                entry.save()
            messages.success(request, "勤怠日報を登録しました。")
            return redirect("attendance:report_detail", pk=report.pk)
    else:
        form = AttendReportForm(initial={"report_date": datetime.date.today()})
        formset = AttendEntryFormSet(prefix="entries")
    return render(request, "attendance/report_form.html", {
        "form": form,
        "formset": formset,
        "is_edit": False,
    })


@login_required
def report_detail(request, pk):
    report = get_object_or_404(AttendReport, pk=pk)
    entries = report.entries.all()
    return render(request, "attendance/report_detail.html", {
        "report": report,
        "entries": entries,
    })


@login_required
def report_edit(request, pk):
    report = get_object_or_404(AttendReport, pk=pk)
    settings_dict = AttendSettings.get_settings_dict(request.user.company)
    if request.method == "POST":
        form = AttendReportForm(request.POST, instance=report)
        formset = AttendEntryFormSet(request.POST, prefix="entries", instance=report)
        if form.is_valid() and formset.is_valid():
            form.save()
            entries = formset.save(commit=False)
            for entry in entries:
                entry.report = report
                entry.company = request.user.company
                if not entry.pk:
                    entry.created_by = request.user
                result = calc_attendance(
                    entry.start_time, entry.end_time,
                    entry.break_minutes, settings_dict,
                )
                entry.early_minutes = result["early"]
                entry.normal_minutes = result["normal"]
                entry.overtime_minutes = result["overtime"]
                entry.total_minutes = result["total"]
                entry.save()
            for entry in formset.deleted_objects:
                entry.delete()
            messages.success(request, "勤怠日報を更新しました。")
            return redirect("attendance:report_detail", pk=report.pk)
    else:
        form = AttendReportForm(instance=report)
        formset = AttendEntryFormSet(prefix="entries", instance=report)
    return render(request, "attendance/report_form.html", {
        "form": form,
        "formset": formset,
        "is_edit": True,
    })


@login_required
def report_delete(request, pk):
    report = get_object_or_404(AttendReport, pk=pk)
    if request.method == "POST":
        report.delete()
        messages.success(request, "勤怠日報を削除しました。")
        return redirect("attendance:report_list")
    return render(request, "attendance/report_detail.html", {
        "report": report,
        "entries": report.entries.all(),
        "confirm_delete": True,
    })


@login_required
def entry_list(request):
    qs = AttendEntry.objects.select_related("report").order_by("-report__report_date")

    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    name = request.GET.get("name", "").strip()
    site = request.GET.get("site", "").strip()

    if date_from:
        qs = qs.filter(report__report_date__gte=date_from)
    if date_to:
        qs = qs.filter(report__report_date__lte=date_to)
    if name:
        qs = qs.filter(employee_name__icontains=name)
    if site:
        qs = qs.filter(report__site_name__icontains=site)

    return render(request, "attendance/entry_list.html", {
        "entries": qs,
        "date_from": date_from,
        "date_to": date_to,
        "name": name,
        "site": site,
    })


@login_required
def employee_record(request, pk):
    """個人別の勤怠集計。"""
    from apps.workers.models import Worker

    worker = get_object_or_404(Worker, pk=pk)
    month_str = request.GET.get("month", "").strip()
    if month_str:
        try:
            year, month = month_str.split("-")
            year, month = int(year), int(month)
        except (ValueError, TypeError):
            year, month = datetime.date.today().year, datetime.date.today().month
    else:
        year, month = datetime.date.today().year, datetime.date.today().month

    entries = AttendEntry.objects.filter(
        worker=worker,
        report__report_date__year=year,
        report__report_date__month=month,
    ).select_related("report").order_by("report__report_date")

    totals = entries.aggregate(
        total_early=Sum("early_minutes"),
        total_normal=Sum("normal_minutes"),
        total_overtime=Sum("overtime_minutes"),
        total_total=Sum("total_minutes"),
    )
    work_days = entries.count()

    # 日別データ(チャート用)
    daily_data = []
    for e in entries:
        daily_data.append({
            "date": e.report.report_date.strftime("%m/%d"),
            "normal": e.normal_minutes / 60,
            "overtime": e.overtime_minutes / 60,
            "early": e.early_minutes / 60,
        })

    return render(request, "attendance/employee_record.html", {
        "worker": worker,
        "entries": entries,
        "totals": totals,
        "work_days": work_days,
        "year": year,
        "month": month,
        "month_str": f"{year}-{month:02d}",
        "daily_data": daily_data,
    })


@login_required
def summary(request):
    """会社全体の勤怠サマリ。"""
    month_str = request.GET.get("month", "").strip()
    if month_str:
        try:
            year, month = month_str.split("-")
            year, month = int(year), int(month)
        except (ValueError, TypeError):
            year, month = datetime.date.today().year, datetime.date.today().month
    else:
        year, month = datetime.date.today().year, datetime.date.today().month

    entries = AttendEntry.objects.filter(
        report__report_date__year=year,
        report__report_date__month=month,
    ).select_related("report", "worker")

    # 従業員別集計
    emp_data = defaultdict(lambda: {
        "name": "",
        "worker_pk": None,
        "days": 0,
        "early": 0,
        "normal": 0,
        "overtime": 0,
        "total": 0,
    })

    for e in entries:
        key = e.employee_name
        emp_data[key]["name"] = e.employee_name
        if e.worker_id:
            emp_data[key]["worker_pk"] = e.worker_id
        emp_data[key]["days"] += 1
        emp_data[key]["early"] += e.early_minutes
        emp_data[key]["normal"] += e.normal_minutes
        emp_data[key]["overtime"] += e.overtime_minutes
        emp_data[key]["total"] += e.total_minutes

    employee_summary = sorted(emp_data.values(), key=lambda x: x["name"])

    # 全体合計
    grand_total = {
        "days": sum(e["days"] for e in employee_summary),
        "early": sum(e["early"] for e in employee_summary),
        "normal": sum(e["normal"] for e in employee_summary),
        "overtime": sum(e["overtime"] for e in employee_summary),
        "total": sum(e["total"] for e in employee_summary),
    }

    return render(request, "attendance/summary.html", {
        "employee_summary": employee_summary,
        "grand_total": grand_total,
        "year": year,
        "month": month,
        "month_str": f"{year}-{month:02d}",
    })


@login_required
def settings_view(request):
    company = request.user.company
    current = AttendSettings.get_settings_dict(company)

    if request.method == "POST":
        form = AttendSettingsForm(request.POST)
        if form.is_valid():
            for key in AttendSettings.DEFAULTS:
                val = form.cleaned_data.get(key, "")
                obj, created = AttendSettings.unscoped.update_or_create(
                    company=company,
                    key=key,
                    defaults={"value": val},
                )
                if created:
                    obj.created_by = request.user
                    obj.save()
            messages.success(request, "勤怠設定を更新しました。")
            return redirect("attendance:settings")
    else:
        form = AttendSettingsForm(initial=current)

    return render(request, "attendance/settings.html", {
        "form": form,
    })
