import datetime
import tempfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.bids.forms import (
    BidCostForm,
    BidProjectForm,
    QualificationForm,
    UnitPriceForm,
)
from apps.bids.models import BidProject, Qualification, UnitPrice


@login_required
def project_list(request):
    qs = BidProject.objects.order_by("-created_at")

    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    region = request.GET.get("region", "").strip()

    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(client__icontains=q))
    if status:
        qs = qs.filter(status=status)
    if region:
        qs = qs.filter(region__icontains=region)

    return render(request, "bids/project_list.html", {
        "projects": qs,
        "q": q,
        "status": status,
        "region": region,
        "status_choices": BidProject.Status.choices,
    })


@login_required
def project_detail(request, pk):
    project = get_object_or_404(BidProject, pk=pk)
    cost = getattr(project, "cost", None)
    competitors = project.competitors.all()
    return render(request, "bids/project_detail.html", {
        "project": project,
        "cost": cost,
        "competitors": competitors,
    })


@login_required
def project_create(request):
    if request.method == "POST":
        form = BidProjectForm(request.POST)
        cost_form = BidCostForm(request.POST, prefix="cost")
        if form.is_valid() and cost_form.is_valid():
            project = form.save(commit=False)
            project.company = request.user.company
            project.created_by = request.user
            project.save()
            cost = cost_form.save(commit=False)
            cost.project = project
            cost.company = request.user.company
            cost.created_by = request.user
            cost.save()
            return redirect("bids:project_detail", pk=project.pk)
    else:
        form = BidProjectForm()
        cost_form = BidCostForm(prefix="cost")
    return render(request, "bids/project_form.html", {
        "form": form,
        "cost_form": cost_form,
    })


@login_required
def project_edit(request, pk):
    project = get_object_or_404(BidProject, pk=pk)
    cost = getattr(project, "cost", None)
    if request.method == "POST":
        form = BidProjectForm(request.POST, instance=project)
        cost_form = BidCostForm(request.POST, prefix="cost", instance=cost)
        if form.is_valid() and cost_form.is_valid():
            form.save()
            cost_obj = cost_form.save(commit=False)
            cost_obj.project = project
            cost_obj.company = request.user.company
            if not cost_obj.pk:
                cost_obj.created_by = request.user
            cost_obj.save()
            return redirect("bids:project_detail", pk=project.pk)
    else:
        form = BidProjectForm(instance=project)
        cost_form = BidCostForm(prefix="cost", instance=cost)
    return render(request, "bids/project_form.html", {
        "form": form,
        "cost_form": cost_form,
    })


@login_required
def qualification_list(request):
    qs = Qualification.objects.all()
    today = datetime.date.today()
    alert_date = today + datetime.timedelta(days=90)
    return render(request, "bids/qualification_list.html", {
        "qualifications": qs,
        "today": today,
        "alert_date": alert_date,
    })


@login_required
def qualification_import(request):
    """Excel/PDFから入札参加資格を一括インポート。"""
    preview = None
    filename = ""

    if request.method == "POST":
        # 確定インポート
        if "confirm_import" in request.POST:
            import json

            records = json.loads(request.POST.get("records_json", "[]"))
            replace_all = request.POST.get("replace_all") == "1"

            if replace_all:
                Qualification.objects.all().delete()

            count = 0
            for rec in records:
                Qualification.objects.create(
                    company=request.user.company,
                    created_by=request.user,
                    issuer=rec.get("issuer") or "不明",
                    category=rec.get("category") or "",
                    grade=rec.get("grade") or "",
                    keisin_score=rec.get("keisin_score"),
                    total_score=rec.get("total_score"),
                    vendor_number=rec.get("vendor_number") or "",
                    valid_from=rec.get("valid_from") or None,
                    valid_until=rec.get("valid_until") or None,
                    application_type=rec.get("application_type") or "",
                    application_method=rec.get("application_method") or "",
                )
                count += 1

            action = "置換" if replace_all else "追加"
            messages.success(request, f"{count}件の資格を{action}インポートしました。")
            return redirect("bids:qualification_list")

        # ファイルアップロード → プレビュー
        uploaded = request.FILES.get("file")
        if uploaded:
            from apps.bids.importer import import_excel, import_pdf

            suffix = Path(uploaded.name).suffix.lower()
            filename = uploaded.name

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                for chunk in uploaded.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            try:
                if suffix in (".xlsx", ".xls"):
                    preview = import_excel(tmp_path)
                elif suffix == ".pdf":
                    preview = import_pdf(tmp_path)
                else:
                    messages.error(request, "Excel(.xlsx) または PDF(.pdf) のみ対応しています。")
            except Exception as e:
                messages.error(request, f"ファイル読み込みエラー: {e}")
            finally:
                Path(tmp_path).unlink(missing_ok=True)

    import json
    return render(request, "bids/qualification_import.html", {
        "preview": preview,
        "preview_json": json.dumps(preview, ensure_ascii=False) if preview else "[]",
        "filename": filename,
        "count": len(preview) if preview else 0,
    })


@login_required
def qualification_create(request):
    if request.method == "POST":
        form = QualificationForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.company = request.user.company
            obj.created_by = request.user
            obj.save()
            return redirect("bids:qualification_list")
    else:
        form = QualificationForm()
    return render(request, "bids/qualification_form.html", {"form": form})


@login_required
def qualification_edit(request, pk):
    obj = get_object_or_404(Qualification, pk=pk)
    if request.method == "POST":
        form = QualificationForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            return redirect("bids:qualification_list")
    else:
        form = QualificationForm(instance=obj)
    return render(request, "bids/qualification_form.html", {"form": form})


@login_required
def unit_price_list(request):
    qs = UnitPrice.objects.all()
    return render(request, "bids/unit_price_list.html", {"unit_prices": qs})


@login_required
def unit_price_create(request):
    if request.method == "POST":
        form = UnitPriceForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.company = request.user.company
            obj.created_by = request.user
            obj.save()
            return redirect("bids:unit_price_list")
    else:
        form = UnitPriceForm()
    return render(request, "bids/unit_price_form.html", {"form": form})


@login_required
def unit_price_edit(request, pk):
    obj = get_object_or_404(UnitPrice, pk=pk)
    if request.method == "POST":
        form = UnitPriceForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            return redirect("bids:unit_price_list")
    else:
        form = UnitPriceForm(instance=obj)
    return render(request, "bids/unit_price_form.html", {"form": form})
