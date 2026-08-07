from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from apps.evaluation.forms import (
    EvalItemForm,
    EvaluationCreateForm,
    EvaluatorTargetForm,
)
from apps.evaluation.models import (
    EvalAnswer,
    EvalItem,
    EvalOverall,
    EvalScore,
    Evaluation,
    EvaluatorTarget,
    SurveyQuestion,
)


@login_required
def eval_list(request):
    """評価一覧。"""
    qs = Evaluation.objects.order_by("-created_at")

    q = request.GET.get("q", "").strip()
    role = request.GET.get("role", "").strip()
    period = request.GET.get("period", "").strip()

    if q:
        qs = qs.filter(
            Q(employee_name__icontains=q) | Q(evaluator_name__icontains=q)
        )
    if role:
        qs = qs.filter(role__icontains=role)
    if period:
        qs = qs.filter(period__icontains=period)

    # 期間の選択肢を取得
    periods = (
        Evaluation.objects.values_list("period", flat=True)
        .distinct()
        .order_by("period")
    )

    return render(request, "evaluation/list.html", {
        "evaluations": qs,
        "q": q,
        "role": role,
        "period": period,
        "periods": periods,
    })


@login_required
def eval_create(request):
    """新規評価作成。"""
    if request.method == "POST":
        form = EvaluationCreateForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.company = request.user.company
            obj.created_by = request.user
            # 該当職種の評価項目から最大合計点を算出
            items = EvalItem.objects.filter(
                Q(section="共通") | Q(section=obj.role)
            )
            obj.max_total = items.aggregate(total=Sum("max_score"))["total"] or 0
            obj.save()

            # 評価項目に基づいてスコアレコードを事前作成
            for item in items:
                EvalScore.objects.create(
                    company=request.user.company,
                    created_by=request.user,
                    evaluation=obj,
                    item_num=item.num,
                    item_name=item.name,
                    score=0,
                )
                # 質問レコードを事前作成
                for sq in item.questions.all():
                    EvalAnswer.objects.create(
                        company=request.user.company,
                        created_by=request.user,
                        evaluation=obj,
                        item=item,
                        item_name=item.name,
                        qnum=sq.qnum,
                        question_text=sq.text,
                    )

            messages.success(request, "評価を作成しました。")
            return redirect("evaluation:eval_detail", pk=obj.pk)
    else:
        form = EvaluationCreateForm()
    return render(request, "evaluation/form.html", {"form": form})


@login_required
def eval_detail(request, pk):
    """評価詳細。"""
    evaluation = get_object_or_404(Evaluation, pk=pk)
    scores = evaluation.scores.all()
    answers = evaluation.answers.all()
    overalls = evaluation.overalls.all()
    return render(request, "evaluation/detail.html", {
        "evaluation": evaluation,
        "scores": scores,
        "answers": answers,
        "overalls": overalls,
    })


@login_required
def eval_input(request, pk):
    """アンケート入力フォーム。"""
    evaluation = get_object_or_404(Evaluation, pk=pk)
    answers = evaluation.answers.all()
    scores = evaluation.scores.all()
    overalls = evaluation.overalls.all()

    if request.method == "POST":
        # 回答を保存
        for answer in answers:
            val = request.POST.get(f"answer_{answer.pk}")
            if val:
                answer.answer = int(val)
                answer.save()

        # スコア・コメントを保存
        for score in scores:
            score_val = request.POST.get(f"score_{score.pk}")
            comment_val = request.POST.get(f"comment_{score.pk}", "")
            if score_val:
                score.score = int(score_val)
            score.comment = comment_val
            score.save()

        # 総合回答を保存
        for overall in overalls:
            text_val = request.POST.get(f"overall_{overall.pk}", "")
            overall.answer_text = text_val
            overall.save()

        messages.success(request, "回答を保存しました。")
        return redirect("evaluation:eval_detail", pk=evaluation.pk)

    return render(request, "evaluation/input.html", {
        "evaluation": evaluation,
        "answers": answers,
        "scores": scores,
        "overalls": overalls,
    })


@login_required
def criteria_list(request):
    """評価基準一覧。"""
    role = request.GET.get("role", "").strip()
    qs = EvalItem.objects.all()
    if role:
        qs = qs.filter(Q(section="共通") | Q(section=role))

    sections = (
        EvalItem.objects.values_list("section", flat=True)
        .distinct()
        .order_by("section")
    )

    return render(request, "evaluation/criteria_list.html", {
        "items": qs,
        "role": role,
        "sections": sections,
    })


@login_required
def criteria_create(request):
    """評価基準の新規作成。"""
    if request.method == "POST":
        form = EvalItemForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.company = request.user.company
            obj.created_by = request.user
            obj.save()
            messages.success(request, "評価項目を作成しました。")
            return redirect("evaluation:criteria_list")
    else:
        form = EvalItemForm()
    return render(request, "evaluation/criteria_form.html", {"form": form})


@login_required
def criteria_edit(request, pk):
    """評価基準の編集。"""
    obj = get_object_or_404(EvalItem, pk=pk)
    if request.method == "POST":
        form = EvalItemForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "評価項目を更新しました。")
            return redirect("evaluation:criteria_list")
    else:
        form = EvalItemForm(instance=obj)
    return render(request, "evaluation/criteria_form.html", {"form": form})


@login_required
def assignment_list(request):
    """評価者割当一覧。"""
    qs = EvaluatorTarget.objects.all()

    if request.method == "POST":
        form = EvaluatorTargetForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.company = request.user.company
            obj.created_by = request.user
            obj.save()
            messages.success(request, "割当を追加しました。")
            return redirect("evaluation:assignment_list")
    else:
        form = EvaluatorTargetForm()

    return render(request, "evaluation/assignment_list.html", {
        "assignments": qs,
        "form": form,
    })


@login_required
def assignment_delete(request, pk):
    """評価者割当の削除。"""
    obj = get_object_or_404(EvaluatorTarget, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "割当を削除しました。")
    return redirect("evaluation:assignment_list")


@login_required
def employee_summary(request, pk):
    """従業員別の評価サマリ。"""
    from apps.workers.models import Worker

    worker = get_object_or_404(Worker, pk=pk)
    evaluations = Evaluation.objects.filter(
        Q(employee=worker) | Q(employee_name=worker.name)
    ).order_by("period")

    # トレンドデータ
    trend_data = []
    for ev in evaluations:
        trend_data.append({
            "period": ev.period,
            "total_score": ev.total_score,
            "max_total": ev.max_total,
            "percent": ev.score_percent,
            "evaluator": ev.evaluator_name or "-",
        })

    # カテゴリ別平均スコア（最新の評価から）
    category_scores = []
    if evaluations.exists():
        latest = evaluations.last()
        for score in latest.scores.all():
            category_scores.append({
                "item_name": score.item_name,
                "score": score.score,
            })

    return render(request, "evaluation/employee_summary.html", {
        "worker": worker,
        "evaluations": evaluations,
        "trend_data": trend_data,
        "category_scores": category_scores,
    })
