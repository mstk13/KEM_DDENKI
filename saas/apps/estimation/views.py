"""積算アプリのビュー。"""

import os
import tempfile
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.estimation.forms import (
    BoqLineForm,
    EstimationItemForm,
    EstimationProjectForm,
    EstimationStandardForm,
    ItemAliasReviewForm,
    LaborRateImportForm,
    OrdererDataSourceForm,
    OrdererForm,
    PurchaseCSVImportForm,
    PurchaseRecordForm,
    WorkRateForm,
)
from apps.estimation.models import (
    BoqLine,
    CostComparison,
    EstimationItem,
    EstimationProject,
    EstimationStandard,
    ItemAlias,
    LaborRate,
    Orderer,
    OrdererDataSource,
    PurchaseRecord,
    WorkRate,
)
from apps.estimation.services import approve_alias, reject_alias


# ---------------------------------------------------------------------------
# 品目マスタ
# ---------------------------------------------------------------------------


@login_required
def item_list(request):
    """積算品目の一覧。"""
    items = EstimationItem.objects.select_related("work_type").order_by("-updated_at")

    q = request.GET.get("q", "").strip()
    if q:
        items = items.filter(canonical_name__icontains=q)

    category = request.GET.get("category", "")
    if category:
        items = items.filter(category=category)

    status = request.GET.get("status", "")
    if status:
        items = items.filter(status=status)

    return render(request, "estimation/item_list.html", {
        "items": items,
        "q": q,
        "category": category,
        "status": status,
        "categories": EstimationItem.Category.choices,
        "statuses": EstimationItem.Status.choices,
    })


@login_required
def item_create(request):
    """積算品目の新規作成。"""
    if request.method == "POST":
        form = EstimationItemForm(request.POST, company=request.user.company)
        if form.is_valid():
            item = form.save(commit=False)
            item.company = request.user.company
            item.created_by = request.user
            item.save()
            return redirect("estimation:item_detail", pk=item.pk)
    else:
        form = EstimationItemForm(company=request.user.company)
    return render(request, "estimation/item_form.html", {
        "form": form,
        "is_new": True,
    })


@login_required
def item_detail(request, pk):
    """積算品目の詳細。紐付き名寄せ一覧を含む。"""
    item = get_object_or_404(EstimationItem, pk=pk)
    aliases = item.aliases.order_by("-updated_at")
    return render(request, "estimation/item_detail.html", {
        "item": item,
        "aliases": aliases,
    })


@login_required
def item_edit(request, pk):
    """積算品目の編集。"""
    item = get_object_or_404(EstimationItem, pk=pk)
    if request.method == "POST":
        form = EstimationItemForm(
            request.POST, instance=item, company=request.user.company,
        )
        if form.is_valid():
            form.save()
            return redirect("estimation:item_detail", pk=item.pk)
    else:
        form = EstimationItemForm(instance=item, company=request.user.company)
    return render(request, "estimation/item_form.html", {
        "form": form,
        "is_new": False,
        "item": item,
    })


# ---------------------------------------------------------------------------
# 名寄せレビュー
# ---------------------------------------------------------------------------


@login_required
def alias_list(request):
    """名寄せレビューキュー。"""
    aliases = ItemAlias.objects.select_related("estimation_item").order_by(
        "status", "confidence", "-updated_at",
    )

    status_filter = request.GET.get("status", "pending")
    if status_filter and status_filter != "all":
        aliases = aliases.filter(status=status_filter)

    source_type = request.GET.get("source_type", "")
    if source_type:
        aliases = aliases.filter(source_type=source_type)

    q = request.GET.get("q", "").strip()
    if q:
        aliases = aliases.filter(raw_name__icontains=q)

    # ステータスごとの件数
    status_counts = {}
    all_aliases = ItemAlias.objects.all()
    for code, _label in ItemAlias.Status.choices:
        status_counts[code] = all_aliases.filter(status=code).count()

    return render(request, "estimation/alias_list.html", {
        "aliases": aliases,
        "status_filter": status_filter,
        "source_type": source_type,
        "q": q,
        "source_types": ItemAlias.SourceType.choices,
        "status_counts": status_counts,
    })


@login_required
def alias_review(request, pk):
    """個別の名寄せレビュー。"""
    alias = get_object_or_404(ItemAlias, pk=pk)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "approve":
            # 紐付先が指定されていれば更新
            item_pk = request.POST.get("estimation_item")
            if item_pk:
                alias.estimation_item_id = int(item_pk)
            approve_alias(alias, request.user)
            return redirect("estimation:alias_list")
        elif action == "reject":
            reject_alias(alias, request.user)
            return redirect("estimation:alias_list")

    form = ItemAliasReviewForm(instance=alias, company=request.user.company)
    return render(request, "estimation/alias_review.html", {
        "alias": alias,
        "form": form,
    })


@login_required
def alias_bulk_approve(request):
    """高信頼度の名寄せを一括承認。"""
    if request.method == "POST":
        alias_ids = request.POST.getlist("alias_ids")
        if alias_ids:
            aliases = ItemAlias.objects.filter(
                pk__in=alias_ids,
                status=ItemAlias.Status.PENDING,
                confidence__gte=Decimal("95"),
            )
            now = timezone.now()
            aliases.update(
                status=ItemAlias.Status.APPROVED,
                reviewed_by=request.user,
                reviewed_at=now,
            )
    return redirect("estimation:alias_list")


# ---------------------------------------------------------------------------
# 発注機関
# ---------------------------------------------------------------------------


@login_required
def orderer_list(request):
    """発注機関の一覧。"""
    orderers = Orderer.objects.order_by("kind", "name")

    q = request.GET.get("q", "").strip()
    if q:
        orderers = orderers.filter(name__icontains=q)

    return render(request, "estimation/orderer_list.html", {
        "orderers": orderers,
        "q": q,
    })


@login_required
def orderer_create(request):
    """発注機関の新規作成。"""
    if request.method == "POST":
        form = OrdererForm(request.POST, company=request.user.company)
        if form.is_valid():
            orderer = form.save(commit=False)
            orderer.company = request.user.company
            orderer.created_by = request.user
            orderer.save()
            return redirect("estimation:orderer_list")
    else:
        form = OrdererForm(company=request.user.company)
    return render(request, "estimation/orderer_form.html", {
        "form": form,
        "is_new": True,
    })


@login_required
def orderer_edit(request, pk):
    """発注機関の編集。"""
    orderer = get_object_or_404(Orderer, pk=pk)
    if request.method == "POST":
        form = OrdererForm(
            request.POST, instance=orderer, company=request.user.company,
        )
        if form.is_valid():
            form.save()
            return redirect("estimation:orderer_list")
    else:
        form = OrdererForm(instance=orderer, company=request.user.company)
    return render(request, "estimation/orderer_form.html", {
        "form": form,
        "is_new": False,
        "orderer": orderer,
    })


# ---------------------------------------------------------------------------
# データソース管理（官公庁ごとのデータ差異）
# ---------------------------------------------------------------------------


@login_required
def datasource_matrix(request):
    """官公庁×データ区分のマトリクス表示。

    どの発注機関がどのデータで独自基準を持っているかを一覧で確認できる。
    メンテナンス時に「どの発注機関のどのデータを更新すべきか」を把握する。
    """
    orderers = Orderer.objects.filter(is_active=True).order_by("kind", "name")
    categories = OrdererDataSource.DataCategory.choices
    sources = OrdererDataSource.objects.select_related("orderer").all()

    # orderer_id × category → datasource のルックアップ辞書
    source_map = {}
    for src in sources:
        source_map[(src.orderer_id, src.category)] = src

    # マトリクスデータを構築
    matrix_rows = []
    for orderer in orderers:
        row = {
            "orderer": orderer,
            "cells": [],
        }
        for cat_code, _cat_label in categories:
            src = source_map.get((orderer.pk, cat_code))
            row["cells"].append({
                "category": cat_code,
                "source": src,
                "scope": src.scope if src else "unset",
            })
        matrix_rows.append(row)

    # 共通データソースの説明（凡例用）
    common_sources = [
        {
            "category": "設計労務単価",
            "source": "国交省「公共工事設計労務単価」",
            "update": "年次（3月公表）",
            "format": "Excel",
            "note": "都道府県別・職種別。全発注者共通。",
        },
        {
            "category": "積算基準（営繕系）",
            "source": "国交省官庁営繕部「公共建築工事積算基準」",
            "update": "年次（3月頃）",
            "format": "PDF",
            "note": "標準単価積算基準/共通費積算基準/数量積算基準/設備数量積算基準を含む。"
                    "営繕系発注者の基本。発注者によっては独自補足あり。",
        },
        {
            "category": "資材単価",
            "source": "経済調査会「積算資料」/ 建設物価調査会「建設物価」",
            "update": "隔月",
            "format": "有償DB / 書籍",
            "note": "有償。システム組込みは別ライセンスの可能性あり。要個別照会。",
        },
    ]

    return render(request, "estimation/datasource_matrix.html", {
        "matrix_rows": matrix_rows,
        "categories": categories,
        "common_sources": common_sources,
    })


@login_required
def orderer_detail(request, pk):
    """発注機関の詳細。データソース一覧を含む。"""
    orderer = get_object_or_404(Orderer, pk=pk)
    data_sources = orderer.data_sources.order_by("category")

    # 未登録のカテゴリを算出
    registered_categories = set(data_sources.values_list("category", flat=True))
    missing_categories = [
        (code, label)
        for code, label in OrdererDataSource.DataCategory.choices
        if code not in registered_categories
    ]

    return render(request, "estimation/orderer_detail.html", {
        "orderer": orderer,
        "data_sources": data_sources,
        "missing_categories": missing_categories,
    })


@login_required
def datasource_create(request, orderer_pk):
    """データソースの新規追加。"""
    orderer = get_object_or_404(Orderer, pk=orderer_pk)
    if request.method == "POST":
        form = OrdererDataSourceForm(request.POST)
        if form.is_valid():
            ds = form.save(commit=False)
            ds.orderer = orderer
            ds.company = request.user.company
            ds.created_by = request.user
            ds.save()
            return redirect("estimation:orderer_detail", pk=orderer.pk)
    else:
        initial = {}
        cat = request.GET.get("category")
        if cat:
            initial["category"] = cat
        form = OrdererDataSourceForm(initial=initial)
    return render(request, "estimation/datasource_form.html", {
        "form": form,
        "orderer": orderer,
        "is_new": True,
    })


@login_required
def datasource_edit(request, pk):
    """データソースの編集。"""
    ds = get_object_or_404(OrdererDataSource, pk=pk)
    if request.method == "POST":
        form = OrdererDataSourceForm(request.POST, instance=ds)
        if form.is_valid():
            form.save()
            return redirect("estimation:orderer_detail", pk=ds.orderer.pk)
    else:
        form = OrdererDataSourceForm(instance=ds)
    return render(request, "estimation/datasource_form.html", {
        "form": form,
        "orderer": ds.orderer,
        "is_new": False,
        "datasource": ds,
    })


# ---------------------------------------------------------------------------
# M2: 労務単価
# ---------------------------------------------------------------------------


@login_required
def labor_rate_list(request):
    """設計労務単価の一覧。"""
    rates = LaborRate.objects.order_by("-fiscal_year", "prefecture", "trade")

    fiscal_year = request.GET.get("fiscal_year", "")
    if fiscal_year:
        rates = rates.filter(fiscal_year=int(fiscal_year))

    prefecture = request.GET.get("prefecture", "")
    if prefecture:
        rates = rates.filter(prefecture=prefecture)

    trade = request.GET.get("trade", "")
    if trade:
        rates = rates.filter(trade__icontains=trade)

    # 年度の選択肢
    fiscal_years = (
        LaborRate.objects.values_list("fiscal_year", flat=True)
        .distinct()
        .order_by("-fiscal_year")
    )
    # 都道府県の選択肢
    prefectures = (
        LaborRate.objects.values_list("prefecture", flat=True)
        .distinct()
        .order_by("prefecture")
    )

    return render(request, "estimation/labor_rate_list.html", {
        "rates": rates[:500],
        "fiscal_year": fiscal_year,
        "prefecture": prefecture,
        "trade": trade,
        "fiscal_years": fiscal_years,
        "prefectures": prefectures,
    })


@login_required
def labor_rate_import(request):
    """労務単価 Excel インポート。"""
    if request.method == "POST":
        form = LaborRateImportForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = request.FILES["file"]
            import_type = form.cleaned_data["import_type"]
            valid_from = form.cleaned_data["valid_from"]
            fiscal_year_label = form.cleaned_data.get("fiscal_year_label", "")

            suffix = ".pdf" if import_type == "pdf" else ".xlsx"
            with tempfile.NamedTemporaryFile(
                suffix=suffix, delete=False,
            ) as tmp:
                for chunk in uploaded.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            try:
                if import_type == "pdf":
                    from apps.estimation.services.labor_pdf import import_labor_rates_from_pdf

                    result_obj = import_labor_rates_from_pdf(
                        file_path=tmp_path,
                        valid_from=valid_from,
                        company=request.user.company,
                        fiscal_year_label=fiscal_year_label,
                    )
                    result = {
                        "created": result_obj.created,
                        "updated": result_obj.updated,
                        "total": result_obj.total,
                    }
                    if result_obj.errors:
                        for err in result_obj.errors[:5]:
                            messages.warning(request, err)
                else:
                    from apps.estimation.services.labor_import import import_labor_rates_from_excel

                    result = import_labor_rates_from_excel(
                        file_path=tmp_path,
                        valid_from=valid_from,
                        company=request.user.company,
                        fiscal_year_label=fiscal_year_label,
                    )
                messages.success(
                    request,
                    f"インポート完了: {result['created']}件作成, "
                    f"{result['updated']}件更新 (計{result['total']}件)",
                )
                return redirect("estimation:labor_rate_list")
            except Exception as e:
                messages.error(request, f"インポートエラー: {e}")
            finally:
                os.unlink(tmp_path)
    else:
        form = LaborRateImportForm()

    return render(request, "estimation/labor_rate_import.html", {
        "form": form,
    })


# ---------------------------------------------------------------------------
# M2: 積算基準
# ---------------------------------------------------------------------------


@login_required
def standard_list(request):
    """積算基準の一覧。"""
    standards = EstimationStandard.objects.select_related("orderer").order_by(
        "-fiscal_year", "orderer__name",
    )
    return render(request, "estimation/standard_list.html", {
        "standards": standards,
    })


@login_required
def standard_create(request):
    """積算基準の新規作成。"""
    if request.method == "POST":
        form = EstimationStandardForm(
            request.POST, request.FILES, company=request.user.company,
        )
        if form.is_valid():
            std = form.save(commit=False)
            std.company = request.user.company
            std.created_by = request.user
            std.save()
            return redirect("estimation:standard_detail", pk=std.pk)
    else:
        form = EstimationStandardForm(company=request.user.company)
    return render(request, "estimation/standard_form.html", {
        "form": form,
        "is_new": True,
    })


@login_required
def standard_detail(request, pk):
    """積算基準の詳細。歩掛・共通費率を含む。"""
    standard = get_object_or_404(EstimationStandard, pk=pk)
    work_rates = standard.work_rates.order_by("work_code")
    overhead_rules = standard.overhead_rules.order_by("category")
    return render(request, "estimation/standard_detail.html", {
        "standard": standard,
        "work_rates": work_rates,
        "overhead_rules": overhead_rules,
    })


@login_required
def standard_edit(request, pk):
    """積算基準の編集。"""
    standard = get_object_or_404(EstimationStandard, pk=pk)
    if request.method == "POST":
        form = EstimationStandardForm(
            request.POST, request.FILES,
            instance=standard, company=request.user.company,
        )
        if form.is_valid():
            form.save()
            return redirect("estimation:standard_detail", pk=standard.pk)
    else:
        form = EstimationStandardForm(
            instance=standard, company=request.user.company,
        )
    return render(request, "estimation/standard_form.html", {
        "form": form,
        "is_new": False,
        "standard": standard,
    })


# ---------------------------------------------------------------------------
# M2: 歩掛
# ---------------------------------------------------------------------------


@login_required
def workrate_create(request, standard_pk):
    """歩掛の新規追加。"""
    standard = get_object_or_404(EstimationStandard, pk=standard_pk)
    if request.method == "POST":
        form = WorkRateForm(request.POST)
        if form.is_valid():
            wr = form.save(commit=False)
            wr.standard = standard
            wr.company = request.user.company
            wr.created_by = request.user
            wr.save()
            return redirect("estimation:standard_detail", pk=standard.pk)
    else:
        form = WorkRateForm()
    return render(request, "estimation/workrate_form.html", {
        "form": form,
        "standard": standard,
        "is_new": True,
    })


@login_required
def workrate_edit(request, pk):
    """歩掛の編集。"""
    wr = get_object_or_404(WorkRate, pk=pk)
    if request.method == "POST":
        form = WorkRateForm(request.POST, instance=wr)
        if form.is_valid():
            form.save()
            return redirect("estimation:standard_detail", pk=wr.standard.pk)
    else:
        form = WorkRateForm(instance=wr)
    return render(request, "estimation/workrate_form.html", {
        "form": form,
        "standard": wr.standard,
        "is_new": False,
        "workrate": wr,
    })


# ---------------------------------------------------------------------------
# M3: 積算案件
# ---------------------------------------------------------------------------


@login_required
def project_list(request):
    """積算案件の一覧。"""
    projects = EstimationProject.objects.select_related(
        "orderer", "standard",
    ).order_by("-updated_at")

    status = request.GET.get("status", "")
    if status:
        projects = projects.filter(status=status)

    q = request.GET.get("q", "").strip()
    if q:
        projects = projects.filter(name__icontains=q)

    return render(request, "estimation/project_list.html", {
        "projects": projects,
        "status": status,
        "q": q,
        "statuses": EstimationProject.Status.choices,
    })


@login_required
def project_create(request):
    """積算案件の新規作成。"""
    if request.method == "POST":
        form = EstimationProjectForm(request.POST, company=request.user.company)
        if form.is_valid():
            proj = form.save(commit=False)
            proj.company = request.user.company
            proj.created_by = request.user
            proj.save()
            return redirect("estimation:project_detail", pk=proj.pk)
    else:
        form = EstimationProjectForm(company=request.user.company)
    return render(request, "estimation/project_form.html", {
        "form": form, "is_new": True,
    })


@login_required
def project_detail(request, pk):
    """積算案件の詳細。内訳書・差分分析を含む。"""
    proj = get_object_or_404(EstimationProject, pk=pk)
    boq_lines = BoqLine.objects.filter(project=proj).order_by("sort_order")
    comparisons = CostComparison.objects.filter(project=proj).select_related(
        "estimation_item",
    ).order_by("-diff_amount")

    # 粗利サマリ
    from decimal import Decimal
    total_standard = sum(
        (c.standard_price or 0) * (c.quantity or 1) for c in comparisons
    )
    total_own = sum(
        (c.own_price or 0) * (c.quantity or 1) for c in comparisons
    )
    total_diff = total_standard - total_own if total_standard and total_own else Decimal("0")

    return render(request, "estimation/project_detail.html", {
        "project": proj,
        "boq_lines": boq_lines,
        "comparisons": comparisons,
        "total_standard": total_standard,
        "total_own": total_own,
        "total_diff": total_diff,
    })


@login_required
def project_edit(request, pk):
    """積算案件の編集。"""
    proj = get_object_or_404(EstimationProject, pk=pk)
    if request.method == "POST":
        form = EstimationProjectForm(
            request.POST, instance=proj, company=request.user.company,
        )
        if form.is_valid():
            form.save()
            return redirect("estimation:project_detail", pk=proj.pk)
    else:
        form = EstimationProjectForm(instance=proj, company=request.user.company)
    return render(request, "estimation/project_form.html", {
        "form": form, "is_new": False, "project": proj,
    })


@login_required
def boq_export(request, pk):
    """内訳書 Excel ダウンロード。"""
    from django.http import HttpResponse
    from apps.estimation.services.boq_export import export_boq_to_excel

    proj = get_object_or_404(EstimationProject, pk=pk)
    excel_bytes = export_boq_to_excel(proj)
    response = HttpResponse(
        excel_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="boq_{proj.pk}.xlsx"'
    return response


@login_required
def boqline_create(request, project_pk):
    """内訳書明細の追加。"""
    proj = get_object_or_404(EstimationProject, pk=project_pk)
    if request.method == "POST":
        form = BoqLineForm(request.POST, company=request.user.company, project=proj)
        if form.is_valid():
            line = form.save(commit=False)
            line.project = proj
            line.company = request.user.company
            line.created_by = request.user
            line.calc_amount()
            line.save()
            return redirect("estimation:project_detail", pk=proj.pk)
    else:
        parent_pk = request.GET.get("parent")
        initial = {}
        if parent_pk:
            initial["parent"] = parent_pk
        form = BoqLineForm(
            initial=initial, company=request.user.company, project=proj,
        )
    return render(request, "estimation/boqline_form.html", {
        "form": form, "project": proj, "is_new": True,
    })


@login_required
def boqline_edit(request, pk):
    """内訳書明細の編集。"""
    line = get_object_or_404(BoqLine, pk=pk)
    if request.method == "POST":
        form = BoqLineForm(
            request.POST, instance=line,
            company=request.user.company, project=line.project,
        )
        if form.is_valid():
            line = form.save(commit=False)
            line.calc_amount()
            line.save()
            return redirect("estimation:project_detail", pk=line.project.pk)
    else:
        form = BoqLineForm(
            instance=line, company=request.user.company, project=line.project,
        )
    return render(request, "estimation/boqline_form.html", {
        "form": form, "project": line.project, "is_new": False, "line": line,
    })


# ---------------------------------------------------------------------------
# M4: 差分分析
# ---------------------------------------------------------------------------


@login_required
def generate_comparison(request, pk):
    """差分分析を生成する。"""
    from apps.estimation.services.comparison import generate_comparisons

    proj = get_object_or_404(EstimationProject, pk=pk)
    if request.method == "POST":
        result = generate_comparisons(proj)
        messages.success(
            request,
            f"差分分析完了: {result['created']}件作成, "
            f"{result['updated']}件更新, 差額合計 {result['total_diff']:,.0f}円",
        )
    return redirect("estimation:project_detail", pk=proj.pk)


@login_required
def purchase_list(request):
    """仕入実績の一覧。"""
    records = PurchaseRecord.objects.select_related(
        "estimation_item", "supplier",
    ).order_by("-purchase_date")

    q = request.GET.get("q", "").strip()
    if q:
        records = records.filter(raw_name__icontains=q)

    return render(request, "estimation/purchase_list.html", {
        "records": records[:500], "q": q,
    })


@login_required
def purchase_create(request):
    """仕入実績の手入力。"""
    if request.method == "POST":
        form = PurchaseRecordForm(request.POST, company=request.user.company)
        if form.is_valid():
            rec = form.save(commit=False)
            rec.company = request.user.company
            rec.created_by = request.user
            rec.import_source = PurchaseRecord.ImportSource.MANUAL
            rec.data_scope = "tenant"
            rec.save()
            return redirect("estimation:purchase_list")
    else:
        form = PurchaseRecordForm(company=request.user.company)
    return render(request, "estimation/purchase_form.html", {
        "form": form, "is_new": True,
    })


@login_required
def purchase_csv_import(request):
    """仕入実績 CSV インポート。"""
    if request.method == "POST":
        form = PurchaseCSVImportForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = request.FILES["file"]
            content = uploaded.read().decode("utf-8-sig")
            auto_match = form.cleaned_data.get("auto_match", True)

            try:
                from apps.estimation.services.purchase_import import import_purchase_records

                result = import_purchase_records(
                    file_content=content,
                    company=request.user.company,
                    auto_match=auto_match,
                )
                messages.success(
                    request,
                    f"インポート完了: {result['created']}件作成, "
                    f"{result['matched']}件名寄せ成功",
                )
                return redirect("estimation:purchase_list")
            except Exception as e:
                messages.error(request, f"インポートエラー: {e}")
    else:
        form = PurchaseCSVImportForm()
    return render(request, "estimation/purchase_csv_import.html", {
        "form": form,
    })
