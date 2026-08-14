from collections import defaultdict
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import models
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.workers.forms import (
    AppPermissionForm,
    HealthCheckupForm,
    WorkerForm,
    WorkerQualificationForm,
)
from apps.workers.models import (
    EvaluationTemplate,
    HealthCheckup,
    JobTitle,
    Worker,
    WorkerEvaluation,
    WorkerQualification,
)


def _is_president(user):
    """ログインユーザーが社長かどうかを判定。"""
    if user.is_superuser:
        return True
    profile = getattr(user, "worker_profile", None)
    return profile and profile.position and profile.position.name == "社長"


def _is_admin(user):
    """社員番号がYで始まる管理者かどうかを判定。"""
    if user.is_superuser:
        return True
    profile = getattr(user, "worker_profile", None)
    return profile and profile.employee_code and profile.employee_code.startswith("Y")


def _has_role(user, role_code):
    """UserRole経由でロールコードを確認。"""
    from apps.permissions.models import UserRole

    return UserRole.unscoped.filter(user=user, role__code=role_code).exists()


@login_required
def document_alert_dashboard(request):
    """事務員向け: 証明書・健診書類の未添付一覧。"""
    from dateutil.relativedelta import relativedelta

    if not (_is_admin(request.user) or _has_role(request.user, "office_staff")):
        raise PermissionDenied("この画面は事務員・管理者のみ閲覧できます。")

    today = date.today()
    due_threshold = today + relativedelta(months=2)

    # 証明書未添付の資格
    missing_certs = (
        WorkerQualification.objects.filter(certificate_image="")
        .select_related("worker")
        .order_by("worker__name", "name")
    )

    # 健診報告書未添付
    missing_health_reports = (
        HealthCheckup.objects.filter(report_file="")
        .select_related("worker")
        .order_by("worker__name", "-checkup_date")
    )

    # 健診期限が2ヶ月以内のワーカー
    latest_dates = (
        HealthCheckup.objects.values("worker", "worker__name", "worker__is_active")
        .annotate(latest=models.Max("checkup_date"))
    )
    checkup_due_workers = []
    for row in latest_dates:
        if not row["worker__is_active"]:
            continue
        next_due = row["latest"] + relativedelta(years=1)
        if next_due <= due_threshold:
            worker = Worker.objects.filter(pk=row["worker"]).first()
            if worker:
                checkup_due_workers.append({
                    "worker": worker,
                    "next_due": next_due,
                    "days_remaining": (next_due - today).days,
                })
    checkup_due_workers.sort(key=lambda x: x["days_remaining"])

    # ワーカー別にグルーピング
    grouped = defaultdict(lambda: {"missing_certs": [], "missing_health_reports": []})
    for q in missing_certs:
        grouped[q.worker]["missing_certs"].append(q)
    for h in missing_health_reports:
        grouped[h.worker]["missing_health_reports"].append(h)

    workers_with_issues = [
        {"worker": w, **data}
        for w, data in sorted(grouped.items(), key=lambda x: x[0].name)
    ]

    return render(request, "workers/document_alert_dashboard.html", {
        "workers_with_issues": workers_with_issues,
        "checkup_due_workers": checkup_due_workers,
        "today": today,
    })


@login_required
def worker_list(request):
    qs = Worker.objects.select_related("job_title", "position")

    # 検索フィルタ
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            models.Q(name__icontains=q)
            | models.Q(name_kana__icontains=q)
            | models.Q(employee_code__icontains=q)
        )

    job_filter = request.GET.get("job", "")
    if job_filter:
        qs = qs.filter(job_title__name=job_filter)

    show_inactive = request.GET.get("inactive") == "1"

    # ソート: フリガナ優先
    qs = qs.order_by(models.functions.Coalesce("name_kana", "name"), "name")

    job_titles = JobTitle.objects.filter(is_active=True).order_by("name")

    return render(request, "workers/list.html", {
        "active_workers": qs.filter(is_active=True),
        "inactive_workers": qs.filter(is_active=False) if show_inactive else [],
        "show_inactive": show_inactive,
        "q": q,
        "job_filter": job_filter,
        "job_titles": job_titles,
        "is_president": _is_president(request.user),
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
    cert_qualifications = worker.qualifications.all()
    health_checkups = worker.health_checkups.all()
    return render(request, "workers/detail.html", {
        "worker": worker,
        "qualifications": qualifications,
        "monthly_salary": worker.monthly_salary,
        "cert_qualifications": cert_qualifications,
        "health_checkups": health_checkups,
        "is_president": _is_president(request.user),
    })


@login_required
def worker_excel(request):
    """社員名簿をExcelでダウンロード。"""
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    qs = Worker.objects.select_related("job_title", "position").order_by(
        models.functions.Coalesce("name_kana", "name"), "name",
    )
    if request.GET.get("active_only") != "0":
        qs = qs.filter(is_active=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "社員名簿"

    headers = [
        "社員番号", "氏名", "よみがな", "部署", "役職", "職種区分", "電話番号", "在籍", "備考",
    ]
    widths = [12, 18, 22, 16, 16, 14, 18, 10, 40]
    header_font = Font(bold=True, size=11, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    alt_fill = PatternFill(start_color="D9E2F3", end_color="D9E2F3", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    for col_idx, (header, width) in enumerate(zip(headers, widths, strict=True), 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border
        ws.column_dimensions[cell.column_letter].width = width

    for row_idx, w in enumerate(qs, 2):
        vals = [
            w.employee_code,
            w.name,
            w.name_kana,
            str(w.position) if w.position else "",
            str(w.position) if w.position else "",
            str(w.job_title) if w.job_title else "",
            w.phone,
            "在籍" if w.is_active else "退職",
            w.note,
        ]
        # Fix: department is position's parent concept - use job_title for 部署 mapping
        # 旧システムでは部署が自由入力だったが、Django 版の Worker は部署を持たない
        # Map: 部署 = position, 役職 = position, 職種 = job_title
        vals[3] = ""  # department - not available in current model
        vals[4] = str(w.position) if w.position else ""
        for col_idx, val in enumerate(vals, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.border = thin_border
            if row_idx % 2 == 0:
                cell.fill = alt_fill

    ws.freeze_panes = "A2"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    from urllib.parse import quote
    today = date.today().strftime("%Y%m%d")
    filename = f"社員名簿_{today}.xlsx"
    response["Content-Disposition"] = (
        f'attachment; filename="workers_{today}.xlsx"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return response


@login_required
def worker_create(request):
    from apps.workers.services import is_developer_worker, setup_developer_worker

    if request.method == "POST":
        form = WorkerForm(request.POST, company=request.user.company)
        if form.is_valid():
            worker = form.save(commit=False)
            worker.company = request.user.company
            worker.created_by = request.user
            worker.save()

            # 職種=ITインフラ, 役職=Developer の場合、自動でユーザーアカウント+権限を設定
            if is_developer_worker(worker):
                user = setup_developer_worker(worker, created_by=request.user)
                messages.success(
                    request,
                    f"開発者「{worker.name}」を登録しました。"
                    f"ログインID: {user.username} / 初期パスワード: {user.username}",
                )
            else:
                messages.success(request, f"作業員「{worker.name}」を登録しました。")

            return redirect("workers:detail", pk=worker.pk)
    else:
        form = WorkerForm(company=request.user.company)
    return render(request, "workers/form.html", {"form": form})


@login_required
def worker_edit(request, pk):
    worker = get_object_or_404(Worker, pk=pk)
    is_admin = _is_admin(request.user)

    if request.method == "POST":
        form = WorkerForm(request.POST, instance=worker, company=request.user.company)
        perm_form = AppPermissionForm(request.POST) if is_admin else None
        if form.is_valid():
            worker = form.save()
            if perm_form and perm_form.is_valid():
                worker.allowed_apps = perm_form.cleaned_data["apps"]
                worker.save(update_fields=["allowed_apps"])
            messages.success(request, "作業員情報を更新しました。")
            return redirect("workers:detail", pk=worker.pk)
    else:
        form = WorkerForm(instance=worker, company=request.user.company)
        perm_form = None
        if is_admin:
            perm_form = AppPermissionForm(initial={"apps": worker.allowed_apps or []})

    return render(request, "workers/form.html", {
        "form": form,
        "worker": worker,
        "cert_qualifications": worker.qualifications.all(),
        "health_checkups": worker.health_checkups.all(),
        "is_president": _is_president(request.user),
        "is_admin": is_admin,
        "perm_form": perm_form,
    })


@login_required
def evaluation_list(request):
    from apps.workers.eval_data import get_available_roles

    evaluations = WorkerEvaluation.objects.select_related(
        "worker", "worker__job_title", "worker__position", "evaluated_by",
    ).order_by("-period", "worker__name")
    return render(request, "workers/evaluations.html", {
        "evaluations": evaluations,
        "sheet_roles": get_available_roles(request.user.company),
    })


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
        # 総合評点は廃止したため、必ず送信される総合コメント欄の有無で判定する
        if worker_id and "total_comment" in request.POST:
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
                "question_scale": data["question_scale"],
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
    current_half = "上期" if 4 <= today.month <= 9 else "下期"

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
        raise PermissionDenied("この操作にはadmin権限が必要です。")

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


@login_required
def eval_survey_pdf(request):
    """評価者別アンケートPDF。

    役員: 比較形式（被評価者を横並び、職種ごとにグループ化）
    一般: 個別形式（対象者ごとに1ページ）
    """
    from apps.workers.eval_data import get_sections_for_worker
    from apps.workers.pdf_template import generate_comparison_pdf, generate_evaluator_pdf

    evaluator_id = request.GET.get("evaluator_id")
    period = request.GET.get("period", "")

    if not evaluator_id:
        messages.error(request, "評価者が指定されていません。")
        return redirect("workers:eval_create")

    evaluator = get_object_or_404(Worker, pk=evaluator_id)
    company = request.user.company
    template = EvaluationTemplate.unscoped.filter(
        company=company, is_active=True,
    ).order_by("-created_at").first()

    if not template:
        messages.error(request, "評価テンプレートが未作成です。")
        return redirect("workers:evaluations")

    is_exec = _is_executive(evaluator)
    qs = Worker.objects.filter(is_active=True).select_related("job_title", "position")
    if not is_exec:
        qs = qs.exclude(pk=evaluator.pk)
    workers = list(qs.order_by("name"))

    from urllib.parse import quote

    if is_exec:
        # 役員: 比較形式PDF（質問が行、被評価者が列で横並び）
        pdf_bytes = generate_comparison_pdf(template, workers, period)
        safe_name = f"eval_comparison_{evaluator.pk}.pdf"
        display_name = f"比較評価シート_{evaluator.name}.pdf"
    else:
        # 一般: 個別形式PDF（対象者ごとに1ページ）
        targets_with_data = []
        for w in workers:
            data = get_sections_for_worker(w, company=company)
            eval_items = _get_eval_items_with_max_score(data)
            targets_with_data.append({
                "worker_name": w.name,
                "job_title": str(w.job_title) if w.job_title else "-",
                "survey_items": eval_items,
                "scale": data["scale"],
                "question_scale": data["question_scale"],
                "overall": data["overall"],
            })
        pdf_bytes = generate_evaluator_pdf(
            template, evaluator.name, targets_with_data, period,
        )
        safe_name = f"eval_survey_{evaluator.pk}.pdf"
        display_name = f"評価アンケート_{evaluator.name}.pdf"

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = (
        f"attachment; filename=\"{safe_name}\"; "
        f"filename*=UTF-8''{quote(display_name)}"
    )
    return response


@login_required
def eval_role_sheet_pdf(request):
    """役職別の人材評価シート（白紙）をPDFで出力する。

    ?role=電工 のように指定すると、その職種のシートだけを出力する。
    指定しない場合は全職種を1つのPDFにまとめる（職種ごとに改ページ）。
    """
    from urllib.parse import quote

    from apps.workers.eval_data import get_available_roles, get_sections_for_role
    from apps.workers.pdf_template import generate_evaluator_pdf

    company = request.user.company
    template = EvaluationTemplate.unscoped.filter(
        company=company, is_active=True,
    ).order_by("-created_at").first()

    if not template:
        messages.error(request, "評価テンプレートが未作成です。")
        return redirect("workers:evaluations")

    available = get_available_roles(company)
    role = request.GET.get("role", "").strip()
    if role and role not in available:
        messages.error(request, f"職種「{role}」の評価項目がありません。")
        return redirect("workers:evaluations")

    roles = [role] if role else available
    if not roles:
        messages.error(request, "職種別の評価項目が登録されていません。")
        return redirect("workers:evaluations")

    period = request.GET.get("period", "")

    targets_with_data = []
    for r in roles:
        data = get_sections_for_role(r, company)
        targets_with_data.append({
            # 氏名を空にすると、PDF側が役職別の白紙シートとして描画する
            "worker_name": "",
            "job_title": r,
            "survey_items": _get_eval_items_with_max_score(data),
            "scale": data["scale"],
            "question_scale": data["question_scale"],
        })

    pdf_bytes = generate_evaluator_pdf(template, "", targets_with_data, period)

    if role:
        safe_name = "eval_sheet_role.pdf"
        display_name = f"人材評価シート_{role}.pdf"
    else:
        safe_name = "eval_sheet_all_roles.pdf"
        display_name = "人材評価シート_全役職.pdf"

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = (
        f"attachment; filename=\"{safe_name}\"; "
        f"filename*=UTF-8''{quote(display_name)}"
    )
    return response


@login_required
def evaluation_edit(request, pk):
    """既存の評価を編集する。"""
    from apps.workers.eval_data import get_sections_for_worker

    evaluation = get_object_or_404(
        WorkerEvaluation.objects.select_related(
            "worker", "worker__job_title", "worker__position", "evaluated_by",
        ),
        pk=pk,
    )
    worker = evaluation.worker
    data = get_sections_for_worker(worker, company=request.user.company)
    eval_items = _get_eval_items_with_max_score(data)

    if request.method == "POST":
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
        evaluation.score = int(total_score) if total_score else None
        evaluation.comment = request.POST.get("total_comment", "")
        evaluation.responses = responses
        evaluation.overall_responses = overall_responses
        evaluation.save()

        messages.success(request, "評価を更新しました。")
        return redirect("workers:eval_detail", pk=evaluation.pk)

    # 既存の回答値を survey_items に埋め込む
    responses = evaluation.responses or {}
    for item in eval_items:
        rkey = f"{item['section']}_{item['num']}"
        rval = responses.get(rkey, {})
        item["saved_score"] = rval.get("score")
        item["saved_free_text"] = rval.get("free_text", "")
        saved_questions = rval.get("questions", {})
        for q in item.get("questions", []):
            # questions のキーは qnum の最後の部分（例: "1-1" → "1"）
            q_key = str(q["qnum"]).rsplit("-", 1)[-1] if "-" in str(q["qnum"]) else str(q["qnum"])
            q["saved_score"] = saved_questions.get(q_key)

    # overall の既存回答
    overall_responses = evaluation.overall_responses or {}
    overall_with_saved = []
    for o in data["overall"]:
        o_copy = dict(o)
        o_copy["saved_text"] = overall_responses.get(str(o["qnum"]), "")
        overall_with_saved.append(o_copy)

    return render(request, "workers/eval_edit.html", {
        "evaluation": evaluation,
        "worker": worker,
        "survey_items": eval_items,
        "scale": data["scale"],
        "question_scale": data["question_scale"],
        "overall": overall_with_saved,
        "sections": data["sections"],
    })


# ---- Worker Qualifications (資格) ----

@login_required
def qualification_create(request, worker_pk):
    worker = get_object_or_404(Worker, pk=worker_pk)
    if request.method == "POST":
        form = WorkerQualificationForm(request.POST, request.FILES)
        if form.is_valid():
            qual = form.save(commit=False)
            qual.worker = worker
            qual.company = request.user.company
            qual.created_by = request.user
            qual.save()
            messages.success(request, "資格を登録しました。")
            return redirect("workers:detail", pk=worker.pk)
    else:
        form = WorkerQualificationForm()
    return render(request, "workers/qualification_form.html", {
        "form": form, "worker": worker,
    })


@login_required
def qualification_edit(request, pk):
    qual = get_object_or_404(WorkerQualification.objects.select_related("worker"), pk=pk)
    if request.method == "POST":
        form = WorkerQualificationForm(request.POST, request.FILES, instance=qual)
        if form.is_valid():
            form.save()
            messages.success(request, "資格を更新しました。")
            return redirect("workers:detail", pk=qual.worker.pk)
    else:
        form = WorkerQualificationForm(instance=qual)
    return render(request, "workers/qualification_form.html", {
        "form": form, "worker": qual.worker,
    })


@login_required
def qualification_delete(request, pk):
    qual = get_object_or_404(WorkerQualification.objects.select_related("worker"), pk=pk)
    worker_pk = qual.worker.pk
    if request.method == "POST":
        qual.delete()
        messages.success(request, "資格を削除しました。")
        return redirect("workers:detail", pk=worker_pk)
    return render(request, "workers/qualification_confirm_delete.html", {
        "qual": qual, "worker": qual.worker,
    })


# ---- Health Checkups (健康診断) ----

@login_required
def health_checkup_create(request, worker_pk):
    worker = get_object_or_404(Worker, pk=worker_pk)
    if request.method == "POST":
        form = HealthCheckupForm(request.POST, request.FILES)
        if form.is_valid():
            checkup = form.save(commit=False)
            checkup.worker = worker
            checkup.company = request.user.company
            checkup.created_by = request.user
            checkup.save()
            messages.success(request, "健康診断記録を登録しました。")
            return redirect("workers:detail", pk=worker.pk)
    else:
        form = HealthCheckupForm()
    return render(request, "workers/health_checkup_form.html", {
        "form": form, "worker": worker,
    })


@login_required
def health_checkup_edit(request, pk):
    checkup = get_object_or_404(HealthCheckup.objects.select_related("worker"), pk=pk)
    if request.method == "POST":
        form = HealthCheckupForm(request.POST, request.FILES, instance=checkup)
        if form.is_valid():
            form.save()
            messages.success(request, "健康診断記録を更新しました。")
            return redirect("workers:detail", pk=checkup.worker.pk)
    else:
        form = HealthCheckupForm(instance=checkup)
    return render(request, "workers/health_checkup_form.html", {
        "form": form, "worker": checkup.worker,
    })


@login_required
def health_checkup_delete(request, pk):
    checkup = get_object_or_404(HealthCheckup.objects.select_related("worker"), pk=pk)
    worker_pk = checkup.worker.pk
    if request.method == "POST":
        checkup.delete()
        messages.success(request, "健康診断記録を削除しました。")
        return redirect("workers:detail", pk=worker_pk)
    return render(request, "workers/health_checkup_confirm_delete.html", {
        "checkup": checkup, "worker": checkup.worker,
    })
