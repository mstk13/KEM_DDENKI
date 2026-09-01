
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.json_utils import json_for_script
from apps.devkanri.forms import DevCommentForm, DevProjectForm, DevTaskForm, MeyasubakoForm
from apps.devkanri.models import DevProject, DevTask, Meyasubako
from apps.devkanri.notifications import notify_task_assigned, notify_task_status_changed
from apps.devkanri.services import get_project_gantt_data

# 一覧の絞り込み。既定は動いているものだけを出す。
# 完了・中断まで並べるとガントが埋まって「いま何が動いているか」が読めなくなる。
PROJECT_SCOPES = {
    "active": "稼働中",
    "mine": "自分の担当",
    "all": "すべて",
}
ACTIVE_STATUSES = ["planning", "in_progress"]


@login_required
def project_list(request):
    """プロジェクト一覧。1ページ目はガントチャートで全体像を見せる。"""
    scope = request.GET.get("scope", "active")
    if scope not in PROJECT_SCOPES:
        scope = "active"

    projects = DevProject.objects.annotate(
        task_count=Count("tasks"),
        done_count=Count("tasks", filter=Q(tasks__status__in=["done", "closed"])),
        bug_count=Count(
            "tasks",
            filter=Q(tasks__category="bug") & ~Q(tasks__status__in=["done", "closed"]),
        ),
    ).select_related("assignee").prefetch_related("tasks")

    if scope == "active":
        projects = projects.filter(status__in=ACTIVE_STATUSES)
    elif scope == "mine":
        projects = projects.filter(assignee=request.user)

    projects = projects.order_by("-created_at")

    gantt_rows = get_project_gantt_data(projects)

    # 表にも同じ期間を出せるよう、行をプロジェクトに持たせる。
    # 並びもガント（期間の早い順）に合わせて、目で追えるようにする。
    row_by_id = {row["id"]: row for row in gantt_rows}
    ordered = []
    for project in projects:
        project.period = row_by_id.get(f"project-{project.pk}")
        ordered.append(project)
    ordered.sort(key=lambda p: (p.period["start"], p.period["end"]) if p.period else ("", ""))

    return render(request, "devkanri/project_list.html", {
        "projects": ordered,
        "gantt_json": json_for_script(gantt_rows),
        "gantt_tasks_exist": len(gantt_rows) > 0,
        "scope": scope,
        "scopes": PROJECT_SCOPES,
        "inferred_count": sum(1 for row in gantt_rows if row["inferred"]),
    })


@login_required
def project_detail(request, pk):
    project = get_object_or_404(DevProject, pk=pk)
    tasks = project.tasks.select_related("assignee").all()

    # Stats
    total = tasks.count()
    done = tasks.filter(status__in=["done", "closed"]).count()
    in_progress = tasks.filter(status="in_progress").count()
    open_count = tasks.filter(status="open").count()
    review_count = tasks.filter(status="review").count()
    open_bugs = tasks.filter(category="bug").exclude(status__in=["done", "closed"]).count()
    hours = tasks.aggregate(
        est=Sum("estimate_hours"),
        act=Sum("actual_hours"),
    )

    # Group by status for kanban
    kanban = {
        "open": tasks.filter(status="open"),
        "in_progress": tasks.filter(status="in_progress"),
        "review": tasks.filter(status="review"),
        "done": tasks.filter(status="done"),
    }

    # Filter for list tab
    status_filter = request.GET.get("status")
    filtered_tasks = tasks.filter(status=status_filter) if status_filter else tasks

    return render(request, "devkanri/project_detail.html", {
        "project": project,
        "tasks": filtered_tasks,
        "kanban": kanban,
        "total": total,
        "done": done,
        "in_progress": in_progress,
        "open_count": open_count,
        "review_count": review_count,
        "open_bugs": open_bugs,
        "estimate_total": hours["est"] or 0,
        "actual_total": hours["act"] or 0,
        "progress_pct": int(done / total * 100) if total > 0 else 0,
        "status_choices": DevTask.Status.choices,
    })


@login_required
def project_create(request):
    if request.method == "POST":
        form = DevProjectForm(request.POST, company=request.user.company)
        if form.is_valid():
            project = form.save(commit=False)
            project.company = request.user.company
            project.created_by = request.user
            project.save()
            messages.success(request, "プロジェクトを作成しました。")
            return redirect("devkanri:project_detail", pk=project.pk)
    else:
        form = DevProjectForm(company=request.user.company)
    return render(request, "devkanri/project_form.html", {"form": form})


@login_required
def project_edit(request, pk):
    project = get_object_or_404(DevProject, pk=pk)
    if request.method == "POST":
        form = DevProjectForm(request.POST, instance=project, company=request.user.company)
        if form.is_valid():
            form.save()
            messages.success(request, "プロジェクトを更新しました。")
            return redirect("devkanri:project_detail", pk=project.pk)
    else:
        form = DevProjectForm(instance=project, company=request.user.company)
    return render(request, "devkanri/project_form.html", {"form": form})


@login_required
def project_delete(request, pk):
    project = get_object_or_404(DevProject, pk=pk)
    if request.method == "POST":
        project.delete()
        messages.success(request, "プロジェクトを削除しました。")
        return redirect("devkanri:project_list")
    return render(request, "devkanri/project_confirm_delete.html", {"project": project})


@login_required
def task_create(request, project_pk):
    project = get_object_or_404(DevProject, pk=project_pk)
    if request.method == "POST":
        form = DevTaskForm(request.POST, company=request.user.company)
        if form.is_valid():
            task = form.save(commit=False)
            task.project = project
            task.company = request.user.company
            task.created_by = request.user
            # sort_order: append to end
            max_order = project.tasks.aggregate(m=Count("id"))["m"] or 0
            task.sort_order = max_order
            task.save()
            if task.assignee:
                notify_task_assigned(task, request.user)
            messages.success(request, "タスクを作成しました。")
            return redirect("devkanri:project_detail", pk=project.pk)
    else:
        form = DevTaskForm(company=request.user.company)
    return render(request, "devkanri/task_form.html", {"form": form, "project": project})


@login_required
def task_edit(request, pk):
    task = get_object_or_404(DevTask.objects.select_related("project"), pk=pk)
    old_assignee_id = task.assignee_id
    old_status = task.status
    if request.method == "POST":
        form = DevTaskForm(request.POST, instance=task, company=request.user.company)
        if form.is_valid():
            task = form.save()
            if task.assignee_id and task.assignee_id != old_assignee_id:
                notify_task_assigned(task, request.user)
            if task.status != old_status:
                notify_task_status_changed(task, request.user, old_status)
            messages.success(request, "タスクを更新しました。")
            return redirect("devkanri:project_detail", pk=task.project.pk)
    else:
        form = DevTaskForm(instance=task, company=request.user.company)
    return render(request, "devkanri/task_form.html", {"form": form, "project": task.project})


@login_required
def task_detail(request, pk):
    task = get_object_or_404(
        DevTask.objects.select_related("project", "assignee", "created_by"),
        pk=pk,
    )
    comments = task.comments.select_related("author").all()

    if request.method == "POST":
        comment_form = DevCommentForm(request.POST)
        if comment_form.is_valid():
            comment = comment_form.save(commit=False)
            comment.task = task
            comment.company = request.user.company
            comment.author = request.user
            comment.created_by = request.user
            comment.save()
            messages.success(request, "コメントを投稿しました。")
            return redirect("devkanri:task_detail", pk=task.pk)
    else:
        comment_form = DevCommentForm()

    return render(request, "devkanri/task_detail.html", {
        "task": task,
        "project": task.project,
        "comments": comments,
        "comment_form": comment_form,
    })


@login_required
def task_delete(request, pk):
    task = get_object_or_404(DevTask.objects.select_related("project"), pk=pk)
    project_pk = task.project.pk
    if request.method == "POST":
        task.delete()
        messages.success(request, "タスクを削除しました。")
        return redirect("devkanri:project_detail", pk=project_pk)
    return render(request, "devkanri/task_confirm_delete.html", {"task": task})


@login_required
def task_move(request, pk):
    """タスクのステータスを変更する（カンバンからの移動用）。"""
    task = get_object_or_404(DevTask.objects.select_related("project"), pk=pk)
    new_status = request.POST.get("status")
    if new_status and new_status in dict(DevTask.Status.choices):
        old_status = task.status
        task.status = new_status
        task.save(update_fields=["status", "updated_at"])
        notify_task_status_changed(task, request.user, old_status)
    return redirect("devkanri:project_detail", pk=task.project.pk)


# ── 目安箱 ──────────────────────────────────────────────


def _get_reporter_name(user):
    """ログインユーザーから報告者名を取得。Worker名 → User名 → username の順。"""
    try:
        if user.worker_profile and user.worker_profile.name:
            return user.worker_profile.name
    except Exception:
        pass
    return user.get_full_name() or user.username


@login_required
def meyasubako_list(request):
    posts = Meyasubako.objects.select_related("reporter").all()
    return render(request, "devkanri/meyasubako_list.html", {"posts": posts})


@login_required
def meyasubako_create(request):
    company = request.user.company
    if request.method == "POST":
        form = MeyasubakoForm(request.POST, request.FILES, company=company)
        if form.is_valid():
            post = form.save(commit=False)
            post.company = company
            worker = form.cleaned_data["reporter_worker"]
            post.reporter = worker.user
            post.reporter_name = worker.name
            post.created_by = request.user
            post.save()
            messages.success(request, "ご意見を投稿しました。ありがとうございます！")
            return redirect("devkanri:meyasubako_list")
    else:
        # ログインユーザーに紐づくWorkerがあれば初期選択
        initial = {}
        try:
            if request.user.worker_profile:
                initial["reporter_worker"] = request.user.worker_profile.pk
        except Exception:
            pass
        form = MeyasubakoForm(company=company, initial=initial)
    return render(request, "devkanri/meyasubako_form.html", {
        "form": form,
    })


@login_required
def meyasubako_detail(request, pk):
    post = get_object_or_404(Meyasubako, pk=pk)
    return render(request, "devkanri/meyasubako_detail.html", {"post": post})


@login_required
def meyasubako_resolve(request, pk):
    post = get_object_or_404(Meyasubako, pk=pk)
    if request.method == "POST":
        post.resolved = not post.resolved
        post.save(update_fields=["resolved", "updated_at"])
    return redirect("devkanri:meyasubako_detail", pk=pk)
