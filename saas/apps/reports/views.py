from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from apps.permissions.services import can_approve_report, can_delete_report
from apps.reports.forms import (
    DailyReportForm,
    OfficeDailyReportForm,
    is_office_reporter,
)
from apps.reports.models import DailyReport, SafetyRecord
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

    selected_status = request.GET.get("status", "")
    if selected_status:
        reports = reports.filter(status=selected_status)

    # 削除ボタンを出すかどうかを行ごとに決める（承認済には出さない）。
    reports = list(reports)
    for r in reports:
        r.can_delete = can_delete_report(request.user, r)

    return render(request, "reports/list.html", {
        "reports": reports,
        "status_choices": DailyReport.Status.choices,
        "selected_status": selected_status,
        "can_approve": can_approve_report(request.user),
        "submitted_count": DailyReport.objects.filter(
            status=DailyReport.Status.SUBMITTED
        ).count(),
    })


def _report_form_context(company):
    """日報フォームの候補一覧と、現場→発注先の対応表を返す。"""
    from apps.core.json_utils import json_for_script
    from apps.masters.models import WorkType
    from apps.sites.models import Process, Site

    sites = list(
        Site.unscoped.filter(company=company)
        .select_related("customer")
        .order_by("name")
    )
    return {
        "site_names": [s.name for s in sites],
        "weather_choices": [label for _v, label in DailyReport.Weather.choices],
        "process_names": sorted({
            p.name for p in Process.unscoped.filter(company=company)
        }),
        "worktype_names": list(
            WorkType.unscoped.filter(company=company, is_active=True)
            .order_by("name")
            .values_list("name", flat=True)
        ),
        # 現場名を入れたら発注先を自動で埋めるための対応表
        "site_orderer_json": json_for_script(
            {s.name: (str(s.customer) if s.customer else "") for s in sites}
        ),
    }


def _office_report_create(request):
    """事務の日報。1日ぶんの時間＋現場ごとの作業内容を書く。"""
    worker = getattr(request.user, "worker_profile", None)

    if request.method == "POST":
        form = OfficeDailyReportForm(
            request.POST, company=request.user.company, worker=worker,
        )
        if form.is_valid():
            status = (
                DailyReport.Status.SUBMITTED
                if request.POST.get("action") == "submit"
                else None
            )
            saved, skipped = form.save_reports(user=request.user, status=status)
            messages.success(request, f"{len(saved)}件の日報を保存しました。")
            if skipped:
                messages.warning(
                    request,
                    "、".join(skipped)
                    + " は同じ日付の日報が既にあるため作成しませんでした。",
                )
            return redirect("reports:list")
    else:
        form = OfficeDailyReportForm(company=request.user.company, worker=worker)

    # 保存に失敗して画面に戻ったとき、入力済みの現場を復元するために渡す
    from apps.core.json_utils import json_for_script

    previous = [
        {"site": e["site_name"], "work": e["work_description"]}
        for e in getattr(form, "entries", [])
    ]

    ctx = {
        "form": form,
        "worker": worker,
        "previous_entries_json": json_for_script(previous),
        **_report_form_context(request.user.company),
    }
    return render(request, "reports/office_form.html", ctx)


@login_required
def report_create(request):
    # 社員番号が G/S/A/P の人は、1日に複数現場ぶんの事務内容を書く形式にする
    if is_office_reporter(request.user):
        return _office_report_create(request)

    if request.method == "POST":
        form = DailyReportForm(request.POST, company=request.user.company)
        if form.is_valid():
            status = (
                DailyReport.Status.SUBMITTED
                if request.POST.get("action") == "submit"
                else None
            )
            saved, skipped = form.save_reports(
                company=request.user.company, user=request.user, status=status,
            )
            messages.success(request, f"{len(saved)}件の日報を保存しました。")
            if skipped:
                names = "、".join(str(w) for w in skipped)
                messages.warning(
                    request,
                    f"{names} は同じ現場・日付・工種の日報が既にあるため作成しませんでした。",
                )
            return redirect("reports:list")
    else:
        form = DailyReportForm(company=request.user.company)
    ctx = {"form": form, **_report_form_context(request.user.company)}
    return render(request, "reports/form.html", ctx)


@login_required
def report_edit(request, pk):
    report = get_object_or_404(DailyReport, pk=pk)
    if request.method == "POST":
        form = DailyReportForm(
            request.POST, instance=report, company=request.user.company,
        )
        if form.is_valid():
            status = (
                DailyReport.Status.SUBMITTED
                if request.POST.get("action") == "submit"
                else None
            )
            form.save_reports(
                company=request.user.company, user=request.user, status=status,
            )
            messages.success(request, "日報を更新しました。")
            return redirect("reports:list")
    else:
        form = DailyReportForm(instance=report, company=request.user.company)
    ctx = {
        "form": form,
        "can_delete": can_delete_report(request.user, report),
        **_report_form_context(request.user.company),
    }
    return render(request, "reports/form.html", ctx)


@login_required
def report_delete(request, pk):
    """日報を削除する。GET は確認画面、POST で削除する。

    ログインしていれば誰でも削除できる。
    承認済の日報は労務費を計上済みのため削除できない。
    """
    report = get_object_or_404(
        DailyReport.objects.select_related("worker", "site", "work_type"), pk=pk,
    )
    if not can_delete_report(request.user, report):
        raise PermissionDenied("承認済の日報は削除できません。")

    if request.method == "POST":
        label = f"{report.report_date} {report.worker} の日報"
        report.delete()
        messages.success(request, f"{label}を削除しました。")
        return redirect("reports:list")

    return render(request, "reports/delete_confirm.html", {"report": report})


@login_required
def report_approve(request, pk):
    if not can_approve_report(request.user):
        raise PermissionDenied("日報を承認できるのは社長とITのみです。")

    report = get_object_or_404(DailyReport, pk=pk)
    if report.status == DailyReport.Status.SUBMITTED:
        approve_report(report, approved_by=request.user)
        messages.success(
            request,
            f"{report.worker} の日報を承認し、労務費を計上しました。",
        )
    else:
        messages.info(request, "提出済の日報のみ承認できます。")
    return redirect("reports:list")


@login_required
def report_approve_bulk(request):
    """提出済の日報をまとめて承認する。"""
    if not can_approve_report(request.user):
        raise PermissionDenied("日報を承認できるのは社長とITのみです。")

    if request.method != "POST":
        return redirect("reports:list")

    pks = request.POST.getlist("report_ids")
    reports = DailyReport.objects.filter(
        pk__in=pks, status=DailyReport.Status.SUBMITTED,
    )

    approved = 0
    for report in reports:
        approve_report(report, approved_by=request.user)
        approved += 1

    if approved:
        messages.success(request, f"{approved}件の日報を承認し、労務費を計上しました。")
    else:
        messages.info(request, "承認できる日報が選択されていません。")
    return redirect("reports:list")


@login_required
def safety_check(request):
    """安全書類チェック画面。"""
    from datetime import date

    from apps.sites.models import Site

    # "active" という状態は Site.Status に存在せず、常に空になっていた。
    # 稼働中とみなせる状態（受注済・施工中）を対象にする。
    sites = Site.objects.filter(
        status__in=[Site.Status.ORDERED, Site.Status.IN_PROGRESS]
    ).order_by("name")
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
    messages.success(
        request, f"{record.worker.name}の{record.template.name}を記入済みにしました。"
    )

    return redirect(
        f"/reports/safety/?site={record.template.site_id}&date={record.record_date}"
    )


@login_required
def monthly_summary(request):
    """月次サマリ画面。

    作業員一覧と同じ社員番号順で作業員ごとの勤怠集計を出し、
    氏名をタップするとその月の承認済の日報一覧が開く（各行から日報の画面へ）。
    """
    from datetime import date

    year = int(request.GET.get("year", date.today().year))
    month = int(request.GET.get("month", date.today().month))

    summary = get_monthly_summary(request.user.company, year, month)

    return render(request, "reports/monthly_summary.html", {
        "summary": summary,
        "year": year,
        "month": month,
    })
