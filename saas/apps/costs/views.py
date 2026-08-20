
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.json_utils import json_for_script
from apps.costs.forms import BudgetImportForm, BudgetItemForm, ManualCostForm
from apps.costs.models import CostAccessGrant, CostTransaction
from apps.costs.services import (
    create_budget_items_from_lines,
    get_monthly_cost_trend,
    get_site_cost_summary,
)
from apps.masters.models import CostCategory, WorkType
from apps.permissions.decorators import module_permission_required
from apps.sites.line_items import (
    deserialize_lines,
    parse_uploaded_lines,
    serialize_lines,
)
from apps.sites.models import Site


@login_required
@module_permission_required("costs", "read")
def cost_list(request):
    """原価一覧（現場ごとの概要）。"""
    sites = Site.objects.filter(
        status__in=[Site.Status.IN_PROGRESS, Site.Status.COMPLETED],
    )

    site_summaries = []
    for site in sites:
        summary = get_site_cost_summary(site)
        # アラートレベル判定
        pct = summary["consumption_pct"]
        if pct >= 100:
            alert_level = "error"
        elif pct >= 90:
            alert_level = "danger"
        elif pct >= 80:
            alert_level = "warning"
        elif pct >= 75:
            alert_level = "caution"
        else:
            alert_level = "normal"

        site_summaries.append({
            "site": site,
            "alert_level": alert_level,
            **summary,
        })

    return render(request, "costs/list.html", {
        "site_summaries": site_summaries,
        # 見積書の受け口。読み取りは costs:budget_import が受ける。
        "import_form": BudgetImportForm(company=request.user.company),
    })


@login_required
@module_permission_required("costs", "read")
def cost_detail(request, site_id):
    """現場別の見積もり/実経費ダッシュボード。グラフ・区分別消化率を表示。"""
    from django.db.models import Sum

    from apps.materials.models import PurchaseOrder

    site = get_object_or_404(Site, pk=site_id)
    summary = get_site_cost_summary(site)
    trend = get_monthly_cost_trend(site)

    transactions = CostTransaction.objects.filter(
        site=site,
    ).select_related(
        "work_type", "cost_category",
    ).order_by("-transaction_date")[:30]

    # 発注（見積もり）vs 実経費
    purchase_orders = PurchaseOrder.objects.filter(
        site=site,
    ).select_related("supplier").order_by("-order_date")

    po_vs_actual = []
    for po in purchase_orders:
        estimate = po.total_amount or 0
        # 実経費: この発注に紐づく CostTransaction の合計
        actual = CostTransaction.unscoped.filter(
            site=site,
            source_type=CostTransaction.SourceType.PO_ITEM,
            supplier=po.supplier,
        ).aggregate(t=Sum("amount"))["t"] or 0
        po_vs_actual.append({
            "po": po,
            "estimate": estimate,
            "actual": actual,
            "diff": estimate - actual,
        })

    return render(request, "costs/detail.html", {
        "site": site,
        "summary": summary,
        "trend_json": json_for_script(trend),
        "transactions": transactions,
        "po_vs_actual": po_vs_actual,
    })


@login_required
@module_permission_required("costs", "read")
def cost_chart_data(request, site_id):
    """Chart.js用のJSONデータを返す（HTMX/Ajax用）。"""
    site = get_object_or_404(Site, pk=site_id)
    trend = get_monthly_cost_trend(site)
    return JsonResponse(trend)


@login_required
@module_permission_required("costs", "write")
def budget_create(request, site_id):
    """予算項目の追加。"""
    site = get_object_or_404(Site, pk=site_id)
    if request.method == "POST":
        form = BudgetItemForm(request.POST, company=request.user.company)
        if form.is_valid():
            item = form.save(commit=False)
            item.site = site
            item.company = request.user.company
            item.created_by = request.user
            item.save()
            messages.success(request, "予算項目を追加しました。")
            return redirect("costs:detail", site_id=site.pk)
    else:
        form = BudgetItemForm(company=request.user.company)
    return render(request, "costs/budget_form.html", {"form": form, "site": site})


@login_required
@module_permission_required("costs", "write")
def manual_cost_create(request):
    """手動原価入力（外注費・経費）。"""
    if request.method == "POST":
        form = ManualCostForm(request.POST, company=request.user.company)
        if form.is_valid():
            tx = form.save(commit=False)
            tx.company = request.user.company
            tx.created_by = request.user
            tx.save()
            messages.success(request, "原価データを登録しました。")
            return redirect("costs:list")
    else:
        form = ManualCostForm(company=request.user.company)
    return render(request, "costs/manual_cost_form.html", {"form": form})


# ── 原価アクセス管理 ──


@login_required
@module_permission_required("costs", "admin")
def cost_access_list(request):
    """原価モジュールへのアクセス許可を管理する。"""
    User = __import__("django.contrib.auth", fromlist=["get_user_model"]).get_user_model()
    company = request.user.company

    grants = CostAccessGrant.unscoped.filter(
        company=company,
    ).select_related("user", "granted_by")

    # 社員番号Gで始まるユーザー一覧（自動アクセス対象）
    auto_access_users = User.objects.filter(
        company=company,
        employee_no__regex=r"^[Gg]",
    )

    # 追加可能なユーザー候補（まだ許可されておらず、自動対象でもない）
    granted_user_ids = grants.values_list("user_id", flat=True)
    auto_user_ids = auto_access_users.values_list("id", flat=True)
    exclude_ids = set(granted_user_ids) | set(auto_user_ids)
    available_users = User.objects.filter(
        company=company,
    ).exclude(id__in=exclude_ids).order_by("employee_no", "last_name")

    return render(request, "costs/access_list.html", {
        "grants": grants,
        "auto_access_users": auto_access_users,
        "available_users": available_users,
    })


@login_required
@module_permission_required("costs", "admin")
def cost_access_grant(request):
    """ユーザーに原価アクセスを付与する。"""
    if request.method == "POST":
        User = __import__("django.contrib.auth", fromlist=["get_user_model"]).get_user_model()
        user_id = request.POST.get("user_id")
        memo = request.POST.get("memo", "")
        try:
            target_user = User.objects.get(pk=user_id, company=request.user.company)
        except User.DoesNotExist:
            messages.error(request, "ユーザーが見つかりません。")
            return redirect("costs:access_list")

        CostAccessGrant.unscoped.get_or_create(
            company=request.user.company,
            user=target_user,
            defaults={
                "granted_by": request.user,
                "memo": memo,
                "created_by": request.user,
            },
        )
        messages.success(request, f"{target_user} にアクセス権を付与しました。")
    return redirect("costs:access_list")


@login_required
@module_permission_required("costs", "admin")
def cost_access_revoke(request, pk):
    """原価アクセス許可を取り消す。"""
    if request.method == "POST":
        grant = get_object_or_404(
            CostAccessGrant.unscoped, pk=pk, company=request.user.company,
        )
        user_name = str(grant.user)
        grant.delete()
        messages.success(request, f"{user_name} のアクセス権を取り消しました。")
    return redirect("costs:access_list")


@login_required
@module_permission_required("costs", "write")
def budget_import(request):
    """見積書（PDF / Excel / CSV）を読んで実行予算を起こす。

    現場見積もり TOP の受け口から来る。読み取り → 確認 → 登録 の2段構え。
    見積取り込み（sites:import）と同じ明細パーサを使うが、あちらは現場と
    見積を作るのに対し、こちらは**既にある現場の実行予算**を作る。

    工種と原価区分は見積書に書かれていないので、確認画面で行ごとに選ぶ。
    受け口で選んだ既定値が全行に入った状態で出るので、違う行だけ直せばよい。
    """
    company = request.user.company

    if request.method != "POST":
        return redirect("costs:list")

    # ---- 確認画面からの登録 ----
    if request.POST.get("step") == "confirm":
        site = get_object_or_404(
            Site.unscoped, company=company, pk=request.POST.get("site"),
        )
        lines = deserialize_lines(request.POST.get("lines_json", ""))
        rows = _rows_with_classification(request, company, lines)

        if not rows:
            messages.info(request, "登録する行が選ばれていなかったので、何も追加していません。")
            return redirect("costs:list")

        items = create_budget_items_from_lines(
            company=company, user=request.user, site=site, rows=rows,
        )
        messages.success(
            request,
            f"見積書から現場「{site.name}」の実行予算を {len(items)} 件登録しました。",
        )
        return redirect("costs:detail", site_id=site.pk)

    # ---- 受け口からの読み取り ----
    form = BudgetImportForm(request.POST, request.FILES, company=company)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("costs:list")

    try:
        lines = parse_uploaded_lines(form.cleaned_data["file"])
    except Exception as e:  # noqa: BLE001 — 読み取り失敗は画面に出して続行させる
        messages.error(request, f"ファイルを読み取れませんでした: {e}")
        return redirect("costs:list")

    if not lines:
        messages.warning(
            request,
            "明細を読み取れませんでした。"
            "「名称／品名／材料名」と「数量・単価・金額」の見出しがある表が"
            "見つからない場合、数字を推測で拾わない作りにしています。",
        )
        return redirect("costs:list")

    site = form.cleaned_data["site"]
    default_work_type = form.cleaned_data["default_work_type"]
    default_cost_category = form.cleaned_data["default_cost_category"]

    return render(request, "costs/budget_import.html", {
        "site": site,
        "filename": form.cleaned_data["file"].name,
        "lines": list(enumerate(lines)),
        "lines_json": serialize_lines(lines),
        "line_total": sum((line["amount"] or 0) for line in lines),
        "default_work_type": default_work_type,
        "default_cost_category": default_cost_category,
        # unscoped: 取り込み経路は company を明示して絞る。
        "work_types": WorkType.unscoped.filter(company=company, is_active=True),
        "cost_categories": CostCategory.objects.all(),
    })


def _rows_with_classification(request, company, lines):
    """確認画面で選ばれた工種・原価区分を明細に添える。

    チェックの外れた行は落とす。工種や原価区分を引けなかった行も落とす
    （他社の工種の pk を送られても拾わないよう company で絞って引く）。
    """
    # unscoped: 取り込み経路は company を明示して絞る。
    work_types = {
        w.pk: w for w in WorkType.unscoped.filter(company=company, is_active=True)
    }
    categories = {c.pk: c for c in CostCategory.objects.all()}

    rows = []
    for index, line in enumerate(lines):
        if not request.POST.get(f"include_{index}"):
            continue
        work_type = work_types.get(_as_pk(request.POST.get(f"work_type_{index}")))
        category = categories.get(_as_pk(request.POST.get(f"cost_category_{index}")))
        if work_type is None or category is None:
            continue
        rows.append({**line, "work_type": work_type, "cost_category": category})
    return rows


def _as_pk(raw):
    return int(raw) if raw and str(raw).isdigit() else None
