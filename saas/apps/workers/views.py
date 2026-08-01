from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.workers.forms import WorkerForm
from apps.workers.models import Worker, WorkerEvaluation


@login_required
def worker_list(request):
    qs = Worker.objects.select_related("job_title", "position").order_by("name")
    return render(request, "workers/list.html", {
        "active_workers": qs.filter(is_active=True),
        "inactive_workers": qs.filter(is_active=False),
    })


@login_required
def worker_detail(request, pk):
    worker = get_object_or_404(Worker, pk=pk)
    tags = worker.skill_tags or {}
    if isinstance(tags, list):
        qualifications = {"education": tags, "skill_courses": [], "licenses": []}
    else:
        qualifications = {
            "education": tags.get("education", []),
            "skill_courses": tags.get("skill_courses", []),
            "licenses": tags.get("licenses", []),
        }
    return render(request, "workers/detail.html", {
        "worker": worker,
        "qualifications": qualifications,
        "monthly_salary": worker.monthly_salary,
    })


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
    """3段階フロー:
    1. 評価者・期間を選択
    2. 被評価者一覧を表示（評価者自身を除く）
    3. 個別のアンケートフォーム → 保存
    """
    from apps.workers.eval_data import get_sections_for_worker

    if request.method == "POST":
        evaluator_id = request.POST.get("evaluator_id")
        worker_id = request.POST.get("worker_id")
        period = request.POST.get("period", "")

        # ステップ3: アンケート回答を保存
        if worker_id and "total_score" in request.POST:
            worker = get_object_or_404(Worker, pk=worker_id)
            responses = {}
            overall_responses = {}

            for key, val in request.POST.items():
                if key.startswith("score_") and val:
                    parts = key.replace("score_", "").rsplit("_", 1)
                    section, num = "_".join(parts[:-1]), parts[-1]
                    responses.setdefault(f"{section}_{num}", {})["score"] = int(val)
                elif key.startswith("q_") and val:
                    parts = key.replace("q_", "").rsplit("_", 1)
                    section_part, qnum = "_".join(parts[:-1]), parts[-1]
                    responses.setdefault(
                        section_part, {},
                    ).setdefault("questions", {})[qnum] = int(val)
                elif key.startswith("freetext_") and val:
                    parts = key.replace("freetext_", "").rsplit("_", 1)
                    section, num = "_".join(parts[:-1]), parts[-1]
                    responses.setdefault(f"{section}_{num}", {})["free_text"] = val
                elif key.startswith("overall_") and val:
                    qnum = key.replace("overall_", "")
                    overall_responses[qnum] = val

            total_score = request.POST.get("total_score")
            data = get_sections_for_worker(worker, company=request.user.company)

            ev = WorkerEvaluation.unscoped.create(
                company=request.user.company,
                worker=worker,
                evaluated_by=request.user,
                created_by=request.user,
                template=data.get("template"),
                period=period,
                score=int(total_score) if total_score else None,
                comment=request.POST.get("total_comment", ""),
                responses=responses,
                overall_responses=overall_responses,
            )
            return redirect("workers:eval_detail", pk=ev.pk)

        # ステップ2b: アンケートフォーム表示
        if worker_id and evaluator_id and period:
            worker = get_object_or_404(Worker, pk=worker_id)
            evaluator = get_object_or_404(Worker, pk=evaluator_id)
            data = get_sections_for_worker(worker)
            eval_items = _get_eval_items_with_max_score(data)
            return render(request, "workers/eval_form.html", {
                "worker": worker,
                "evaluator": evaluator,
                "period": period,
                "survey_items": eval_items,
                "scale": data["scale"],
                "overall": data["overall"],
                "sections": data["sections"],
            })

        # ステップ2a: 被評価者一覧
        if evaluator_id and period:
            evaluator = get_object_or_404(Worker, pk=evaluator_id)
            targets = list(
                Worker.objects.filter(is_active=True)
                .exclude(pk=evaluator.pk)
                .select_related("job_title", "position")
                .order_by("name")
            )
            # 既に評価済みかチェック
            existing = WorkerEvaluation.objects.filter(
                period=period,
                evaluated_by=request.user,
            ).values_list("worker_id", "pk")
            completed_map = {wid: epk for wid, epk in existing}
            completed_ids = set(completed_map.keys())
            for t in targets:
                t.eval_pk = completed_map.get(t.pk)

            return render(request, "workers/eval_targets.html", {
                "evaluator": evaluator,
                "period": period,
                "targets": targets,
                "completed_ids": completed_ids,
            })

    # ステップ1: 評価者・期間選択
    workers = Worker.objects.filter(is_active=True).select_related(
        "job_title",
    ).order_by("name")
    return render(request, "workers/eval_start.html", {"workers": workers})


def _get_eval_items_with_max_score(data):
    """survey_items に eval_items の max_score と description を付与。"""
    items_map = {}
    for item in data["items"]:
        items_map[(item["section"], item["num"])] = item

    result = []
    for si in data["survey_items"]:
        ei = items_map.get((si["section"], si["num"]), {})
        si["max_score"] = ei.get("max_score", "")
        si["description"] = si.get("anchor_5", "") or ei.get("description", "")
        result.append(si)
    return result
