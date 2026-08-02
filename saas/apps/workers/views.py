from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.workers.forms import WorkerForm
from apps.workers.models import EvaluationTemplate, Worker, WorkerEvaluation


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
            is_executive = _is_executive(evaluator)
            qs = Worker.objects.filter(is_active=True).select_related("job_title", "position")
            # 役員は自分を含む全員を評価する
            if not is_executive:
                qs = qs.exclude(pk=evaluator.pk)
            targets = list(qs.order_by("name"))
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
    return render(request, "workers/eval_start.html", {
        "workers": workers,
        "period_choices": _get_period_choices(),
    })


def _is_executive(worker):
    """役員・社長かどうかを判定する。"""
    job_name = str(worker.job_title) if worker.job_title else ""
    return job_name in ("役員", "社長")


@login_required
def eval_targets_api(request):
    """評価者IDと期間を受け取り、被評価者一覧をJSONで返す。"""
    evaluator_id = request.GET.get("evaluator_id")
    period = request.GET.get("period", "")

    if not evaluator_id:
        return JsonResponse({"targets": []})

    evaluator = get_object_or_404(Worker, pk=evaluator_id)
    is_exec = _is_executive(evaluator)

    qs = Worker.objects.filter(is_active=True).select_related("job_title", "position")
    if not is_exec:
        qs = qs.exclude(pk=evaluator.pk)

    # 既に評価済みかチェック
    completed_map = {}
    if period:
        existing = WorkerEvaluation.objects.filter(
            period=period,
            evaluated_by=request.user,
        ).values_list("worker_id", "pk")
        completed_map = {wid: epk for wid, epk in existing}

    targets = []
    for w in qs.order_by("name"):
        targets.append({
            "pk": w.pk,
            "name": w.name,
            "name_kana": w.name_kana or "",
            "job_title": str(w.job_title) if w.job_title else "-",
            "position": str(w.position) if w.position else "-",
            "completed": w.pk in completed_map,
            "eval_pk": completed_map.get(w.pk),
        })

    return JsonResponse({"targets": targets, "is_executive": is_exec})


def _get_period_choices():
    """評価期間の選択肢を生成する。年度ごとに上期・下期の2回。

    日本の年度: 4月〜9月=上期、10月〜3月=下期
    現在の年度と前後1年度の選択肢を返す。
    """
    today = date.today()
    # 年度を計算（1〜3月は前年度に属する）
    fiscal_year = today.year if today.month >= 4 else today.year - 1
    # 現在が上期(4-9)か下期(10-3)か
    if today.month >= 4 and today.month <= 9:
        current_half = "上期"
    else:
        current_half = "下期"

    choices = []
    for fy in [fiscal_year + 1, fiscal_year, fiscal_year - 1]:
        choices.append((f"{fy}年度 上期", f"{fy}年度 上期（{fy}年4月〜9月）"))
        choices.append((f"{fy}年度 下期", f"{fy}年度 下期（{fy}年10月〜{fy + 1}年3月）"))

    # 現在の期間をデフォルトにするため先頭に持ってくる
    current_val = f"{fiscal_year}年度 {current_half}"
    choices.sort(key=lambda c: (0 if c[0] == current_val else 1, c[0]), reverse=False)

    return choices


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


def _is_eval_admin(user):
    """評価テンプレート編集権限を持つか（admin グループ or superuser）。"""
    return user.is_superuser or user.groups.filter(name="admin").exists()


@login_required
def eval_template_edit(request):
    """評価テンプレートの編集。admin グループのユーザーのみ。"""
    if not _is_eval_admin(request.user):
        return HttpResponseForbidden("この操作にはadmin権限が必要です。")

    company = request.user.company
    template = EvaluationTemplate.unscoped.filter(
        company=company, is_active=True,
    ).order_by("-created_at").first()

    if not template:
        messages.error(request, "評価テンプレートが未作成です。管理者に連絡してください。")
        return redirect("workers:evaluations")

    if request.method == "POST":
        # スケール
        scale = []
        i = 0
        while f"scale_value_{i}" in request.POST:
            val = request.POST.get(f"scale_value_{i}", "").strip()
            label = request.POST.get(f"scale_label_{i}", "").strip()
            if val and label:
                scale.append({"value": int(val), "label": label})
            i += 1

        # 評価項目
        survey_items = []
        sections_data = []
        item_idx = 0
        while f"item_name_{item_idx}" in request.POST:
            name = request.POST.get(f"item_name_{item_idx}", "").strip()
            section = request.POST.get(f"item_section_{item_idx}", "共通")
            num = int(request.POST.get(f"item_num_{item_idx}", 0) or 0)
            max_score = request.POST.get(f"item_max_score_{item_idx}", "")

            anchor_5 = request.POST.get(f"item_anchor5_{item_idx}", "")
            anchor_3 = request.POST.get(f"item_anchor3_{item_idx}", "")
            anchor_1 = request.POST.get(f"item_anchor1_{item_idx}", "")
            free_text = request.POST.get(f"item_freetext_{item_idx}", "")

            questions = []
            qi = 0
            while f"q_text_{item_idx}_{qi}" in request.POST:
                qnum = request.POST.get(f"q_num_{item_idx}_{qi}", "").strip()
                qtext = request.POST.get(f"q_text_{item_idx}_{qi}", "").strip()
                if qtext:
                    questions.append({"qnum": qnum, "text": qtext})
                qi += 1

            if name:
                item = {
                    "section": section,
                    "num": num,
                    "name": name,
                    "anchor_5": anchor_5,
                    "anchor_3": anchor_3,
                    "anchor_1": anchor_1,
                    "free_text": free_text,
                    "questions": questions,
                    "max_score": int(max_score) if max_score else 0,
                }
                survey_items.append(item)
                sections_data.append({
                    "section": section,
                    "num": num,
                    "name": name,
                    "description": anchor_5 or "",
                    "max_score": int(max_score) if max_score else 0,
                    "choice_group": None,
                    "sort_order": item_idx,
                })
            item_idx += 1

        # 総合所見
        overall = []
        oi = 0
        while f"overall_text_{oi}" in request.POST:
            qnum = request.POST.get(f"overall_qnum_{oi}", "").strip()
            text = request.POST.get(f"overall_text_{oi}", "").strip()
            by_self = f"overall_byself_{oi}" in request.POST
            if text:
                overall.append({"qnum": qnum, "text": text, "by_self": by_self})
            oi += 1

        template.scale = scale
        template.survey_items = survey_items
        template.sections = sections_data
        template.overall = overall
        template.save()

        messages.success(request, "評価テンプレートを保存しました。")
        return redirect("workers:eval_template_edit")

    return render(request, "workers/eval_template_edit.html", {
        "template": template,
    })


@login_required
def eval_template_pdf(request):
    """評価テンプレートの質問項目をPDFでダウンロード。"""
    from apps.workers.pdf_template import generate_template_pdf

    company = request.user.company
    template = EvaluationTemplate.unscoped.filter(
        company=company, is_active=True,
    ).order_by("-created_at").first()

    if not template:
        messages.error(request, "評価テンプレートが未作成です。")
        return redirect("workers:evaluations")

    pdf_bytes = generate_template_pdf(template)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="eval_template.pdf"'
    return response


@login_required
def eval_comparison_pdf(request):
    """役員用: 被評価者を横に並べた比較評価シートPDF。

    職種ごとにグループ化し、各質問に対して全員分の記入欄を横に並べる。
    """
    from apps.workers.pdf_template import generate_comparison_pdf

    company = request.user.company
    template = EvaluationTemplate.unscoped.filter(
        company=company, is_active=True,
    ).order_by("-created_at").first()

    if not template:
        messages.error(request, "評価テンプレートが未作成です。")
        return redirect("workers:evaluations")

    workers = list(
        Worker.objects.filter(is_active=True)
        .select_related("job_title", "position")
        .order_by("name")
    )

    period = request.GET.get("period", "")

    pdf_bytes = generate_comparison_pdf(template, workers, period)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="eval_comparison.pdf"'
    return response
