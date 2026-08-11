import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.schedules.forms import AssignmentForm, MilestoneForm, PhaseForm
from apps.schedules.models import Assignment, Milestone, Phase, PhaseTemplate
from apps.schedules.services import (
    apply_template,
    get_calendar_data,
    get_comparison_gantt_data,
    get_site_gantt_data,
)
from apps.sites.models import Site


@login_required
def schedule_detail(request, pk):
    site = get_object_or_404(Site, pk=pk)
    phases = site.phases.all()
    milestones = site.milestones.all()
    assignments = site.assignments.select_related("worker").all()
    templates = PhaseTemplate.objects.all()

    # 工程別ガントチャート
    gantt_data = get_site_gantt_data(site)
    gantt_json = json.dumps(gantt_data, ensure_ascii=False)

    return render(request, "schedules/detail.html", {
        "site": site,
        "phases": phases,
        "milestones": milestones,
        "assignments": assignments,
        "templates": templates,
        "gantt_json": gantt_json,
        "gantt_tasks_exist": len(gantt_data) > 0,
    })


@login_required
def schedule_compare(request):
    """複数現場の工期・工程を並べて比較するガントチャート。

    GET パラメータ:
        site … 比較対象の現場PK（複数指定可）。未指定なら施工中・受注済の全現場。
        mode … "site"（現場単位）または "phase"（工程単位）
    """
    mode = request.GET.get("mode", "site")
    if mode not in ("site", "phase"):
        mode = "site"

    selected_ids = [v for v in request.GET.getlist("site") if v.isdigit()]

    data = get_comparison_gantt_data(request.user.company, selected_ids, mode)

    # 選択UI用。工期の設定有無にかかわらず全現場を出す。
    all_sites = Site.objects.order_by("-start_date", "name")
    selected_set = {int(v) for v in selected_ids}

    return render(request, "schedules/compare.html", {
        "all_sites": all_sites,
        "selected_ids": selected_set,
        "mode": mode,
        "legend": data["legend"],
        "gantt_json": json.dumps(data["tasks"], ensure_ascii=False),
        "gantt_tasks_exist": len(data["tasks"]) > 0,
    })


@login_required
def calendar_view(request):
    """配置カレンダー画面。FullCalendarで作業員×現場の配置を表示。"""
    return render(request, "schedules/calendar.html")


@login_required
def calendar_events(request):
    """FullCalendar用のイベントJSONを返す。"""
    start = request.GET.get("start", "")
    end = request.GET.get("end", "")

    from datetime import date

    try:
        start_date = date.fromisoformat(start[:10]) if start else date.today()
        end_date = date.fromisoformat(end[:10]) if end else date.today()
    except ValueError:
        start_date = date.today()
        end_date = date.today()

    events = get_calendar_data(request.user.company, start_date, end_date)
    return JsonResponse(events, safe=False)


@login_required
def apply_template_view(request, site_pk):
    """工程テンプレートを現場に適用する。"""
    if request.method != "POST":
        return redirect("schedules:detail", pk=site_pk)

    site = get_object_or_404(Site, pk=site_pk)
    template_id = request.POST.get("template_id")
    base_date_str = request.POST.get("base_date")

    from datetime import date as date_cls
    base_date = date_cls.fromisoformat(base_date_str) if base_date_str else None

    created = apply_template(site, template_id, base_date)
    messages.success(request, f"テンプレートから{len(created)}件の工程を作成しました。")
    return redirect("schedules:detail", pk=site_pk)


# ─── Phase CRUD ───


@login_required
def phase_create(request, site_pk):
    site = get_object_or_404(Site, pk=site_pk)
    if request.method == "POST":
        form = PhaseForm(request.POST, company=request.user.company)
        if form.is_valid():
            phase = form.save(commit=False)
            phase.site = site
            phase.company = request.user.company
            phase.created_by = request.user
            phase.save()
            messages.success(request, "工程フェーズを作成しました。")
            return redirect("schedules:detail", pk=site.pk)
    else:
        form = PhaseForm(company=request.user.company)
    return render(request, "schedules/phase_form.html", {"form": form, "site": site})


@login_required
def phase_edit(request, pk):
    phase = get_object_or_404(Phase.objects.select_related("site"), pk=pk)
    if request.method == "POST":
        form = PhaseForm(request.POST, instance=phase, company=request.user.company)
        if form.is_valid():
            form.save()
            messages.success(request, "工程フェーズを更新しました。")
            return redirect("schedules:detail", pk=phase.site.pk)
    else:
        form = PhaseForm(instance=phase, company=request.user.company)
    return render(request, "schedules/phase_form.html", {"form": form, "site": phase.site})


@login_required
def phase_delete(request, pk):
    phase = get_object_or_404(Phase.objects.select_related("site"), pk=pk)
    site_pk = phase.site.pk
    if request.method == "POST":
        phase.delete()
        messages.success(request, "工程フェーズを削除しました。")
        return redirect("schedules:detail", pk=site_pk)
    return render(request, "schedules/detail.html", {
        "site": phase.site,
        "phases": phase.site.phases.all(),
        "milestones": phase.site.milestones.all(),
        "assignments": phase.site.assignments.select_related("worker").all(),
        "confirm_delete_phase": phase,
    })


# ─── Milestone CRUD ───


@login_required
def milestone_create(request, site_pk):
    site = get_object_or_404(Site, pk=site_pk)
    if request.method == "POST":
        form = MilestoneForm(request.POST, company=request.user.company)
        if form.is_valid():
            milestone = form.save(commit=False)
            milestone.site = site
            milestone.company = request.user.company
            milestone.created_by = request.user
            milestone.save()
            messages.success(request, "マイルストーンを作成しました。")
            return redirect("schedules:detail", pk=site.pk)
    else:
        form = MilestoneForm(company=request.user.company)
    return render(request, "schedules/milestone_form.html", {"form": form, "site": site})


@login_required
def milestone_edit(request, pk):
    milestone = get_object_or_404(Milestone.objects.select_related("site"), pk=pk)
    if request.method == "POST":
        form = MilestoneForm(request.POST, instance=milestone, company=request.user.company)
        if form.is_valid():
            form.save()
            messages.success(request, "マイルストーンを更新しました。")
            return redirect("schedules:detail", pk=milestone.site.pk)
    else:
        form = MilestoneForm(instance=milestone, company=request.user.company)
    return render(request, "schedules/milestone_form.html", {"form": form, "site": milestone.site})


@login_required
def milestone_delete(request, pk):
    milestone = get_object_or_404(Milestone.objects.select_related("site"), pk=pk)
    site_pk = milestone.site.pk
    if request.method == "POST":
        milestone.delete()
        messages.success(request, "マイルストーンを削除しました。")
        return redirect("schedules:detail", pk=site_pk)
    return render(request, "schedules/detail.html", {
        "site": milestone.site,
        "phases": milestone.site.phases.all(),
        "milestones": milestone.site.milestones.all(),
        "assignments": milestone.site.assignments.select_related("worker").all(),
        "confirm_delete_milestone": milestone,
    })


# ─── Assignment CRUD ───


@login_required
def assignment_create(request, site_pk):
    site = get_object_or_404(Site, pk=site_pk)
    if request.method == "POST":
        form = AssignmentForm(request.POST, company=request.user.company)
        if form.is_valid():
            assignment = form.save(commit=False)
            assignment.site = site
            assignment.company = request.user.company
            assignment.created_by = request.user
            assignment.save()
            messages.success(request, "配置を作成しました。")
            return redirect("schedules:detail", pk=site.pk)
    else:
        form = AssignmentForm(company=request.user.company)
    return render(request, "schedules/assignment_form.html", {"form": form, "site": site})


@login_required
def assignment_delete(request, pk):
    assignment = get_object_or_404(Assignment.objects.select_related("site"), pk=pk)
    site_pk = assignment.site.pk
    if request.method == "POST":
        assignment.delete()
        messages.success(request, "配置を削除しました。")
        return redirect("schedules:detail", pk=site_pk)
    return render(request, "schedules/detail.html", {
        "site": assignment.site,
        "phases": assignment.site.phases.all(),
        "milestones": assignment.site.milestones.all(),
        "assignments": assignment.site.assignments.select_related("worker").all(),
        "confirm_delete_assignment": assignment,
    })
