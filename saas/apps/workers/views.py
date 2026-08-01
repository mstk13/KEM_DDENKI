from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.workers.forms import EvaluationForm, WorkerForm
from apps.workers.models import Worker, WorkerEvaluation


@login_required
def worker_list(request):
    workers = Worker.objects.select_related(
        "job_title", "position"
    ).order_by("name")
    return render(request, "workers/list.html", {"workers": workers})


@login_required
def worker_detail(request, pk):
    worker = get_object_or_404(Worker, pk=pk)
    return render(request, "workers/detail.html", {"worker": worker})


@login_required
def worker_create(request):
    if request.method == "POST":
        form = WorkerForm(request.POST, company=request.user.company)
        if form.is_valid():
            worker = form.save(commit=False)
            worker.company = request.user.company
            worker.created_by = request.user
            worker.save()
            return redirect("workers:detail", pk=worker.pk)
    else:
        form = WorkerForm(company=request.user.company)
    return render(request, "workers/form.html", {"form": form})


@login_required
def worker_edit(request, pk):
    worker = get_object_or_404(Worker, pk=pk)
    if request.method == "POST":
        form = WorkerForm(request.POST, instance=worker, company=request.user.company)
        if form.is_valid():
            form.save()
            return redirect("workers:detail", pk=worker.pk)
    else:
        form = WorkerForm(instance=worker, company=request.user.company)
    return render(request, "workers/form.html", {"form": form})


@login_required
def evaluation_list(request):
    evaluations = WorkerEvaluation.objects.select_related(
        "worker", "worker__job_title", "worker__position", "evaluated_by",
    ).order_by("-period", "worker__name")
    return render(request, "workers/evaluations.html", {"evaluations": evaluations})


@login_required
def evaluation_detail(request, pk):
    evaluation = get_object_or_404(
        WorkerEvaluation.objects.select_related(
            "worker", "worker__job_title", "worker__position", "evaluated_by",
        ),
        pk=pk,
    )
    return render(request, "workers/eval_detail.html", {"evaluation": evaluation})


@login_required
def evaluation_create(request):
    if request.method == "POST":
        form = EvaluationForm(request.POST, company=request.user.company)
        if form.is_valid():
            ev = form.save(commit=False)
            ev.company = request.user.company
            ev.evaluated_by = request.user
            ev.created_by = request.user
            ev.save()
            return redirect("workers:eval_detail", pk=ev.pk)
    else:
        form = EvaluationForm(company=request.user.company)
    return render(request, "workers/eval_form.html", {"form": form})
