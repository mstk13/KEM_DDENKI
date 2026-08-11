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
    EstimationItemForm,
    EstimationStandardForm,
    ItemAliasReviewForm,
    LaborRateImportForm,
    OrdererDataSourceForm,
    OrdererForm,
    WorkRateForm,
)
from apps.estimation.models import (
    EstimationItem,
    EstimationStandard,
    ItemAlias,
    LaborRate,
    Orderer,
    OrdererDataSource,
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
            fiscal_year = form.cleaned_data["fiscal_year"]
            source_url = form.cleaned_data.get("source_url", "")

            # 一時ファイルに保存して解析
            with tempfile.NamedTemporaryFile(
                suffix=".xlsx", delete=False,
            ) as tmp:
                for chunk in uploaded.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            try:
                from apps.estimation.services.labor_import import import_labor_rates

                result = import_labor_rates(
                    file_path=tmp_path,
                    fiscal_year=fiscal_year,
                    company=request.user.company,
                    source_url=source_url,
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
