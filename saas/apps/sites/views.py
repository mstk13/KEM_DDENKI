import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.costs.models import BudgetItem
from apps.costs.services import get_site_cost_summary
from apps.estimation.forms import BoqImportForm, BoqLineRowFormSet
from apps.estimation.models import BoqLine
from apps.estimation.services import boq_import
from apps.estimation.services.boq_import import rebuild_tree
from apps.materials.services import (
    create_quotation_from_lines,
    match_lines_to_materials,
)
from apps.permissions.services import has_module_permission
from apps.sites.forms import EstimateUploadForm, ProcessForm, SiteForm
from apps.sites.importer import FIELD_LABELS, parse_rows, read_rows
from apps.sites.line_items import (
    deserialize_lines,
    extract_lines,
    serialize_lines,
)
from apps.sites.models import EstimateImport, Process, Site
from apps.sites.services import (
    APPLY_FIELDS,
    apply_estimate_to_site,
    build_estimate_diff,
    collect_site_deletion_impact,
    estimate_values_for_site,
    find_customer_by_name,
    get_site_summary,
)


@login_required
def site_list(request):
    sites = Site.objects.select_related("customer", "manager", "estimator").order_by(
        "-created_at"
    )
    return render(request, "sites/list.html", {"sites": sites})


@login_required
def site_detail(request, pk):
    site = get_object_or_404(Site, pk=pk)
    processes = site.processes.select_related("work_type").order_by("display_order")
    summary = get_site_summary(site)

    # 見積もり/実経費は現場詳細に統合したが、原価は誰でも見てよい情報ではない。
    # costs モジュールと同じ判定（社長・役員・developer・社員番号G始まり・個別許可）を
    # 通す。権限が無ければ金額系は一切コンテキストに載せない。
    can_view_costs = has_module_permission(request.user, "costs", "read")
    cost_summary = get_site_cost_summary(site) if can_view_costs else None

    # get_site_summary は工程進捗などと一緒に金額も返す。権限が無いユーザーには
    # テンプレートに渡さない（従来は原価合計・粗利が全社員に見えていた）。
    if not can_view_costs:
        for money_key in ("total_cost", "budget_total", "gross_profit", "margin_rate"):
            summary.pop(money_key, None)

    # 実行予算の明細（見積もりの内訳）。区分別の集計だけでは「何にいくら見た
    # のか」が分からないので、項目行そのものも出す。原価と同じ扱いなので
    # 権限が無ければ引かない。
    budget_items = (
        BudgetItem.objects.filter(site=site)
        .select_related("work_type", "cost_category")
        .order_by("cost_category__display_order", "work_type__code", "pk")
        if can_view_costs
        else None
    )

    boq_lines = list(_site_boq_lines(site))

    return render(request, "sites/detail.html", {
        "site": site,
        "processes": processes,
        "can_view_costs": can_view_costs,
        "cost_summary": cost_summary,
        "purchase_orders": site.purchase_orders.select_related("supplier").order_by(
            "-order_date"
        ),
        # 見積内訳。明細まで現場詳細で開けるようにするので prefetch する
        # （見積ごとに N+1 で明細を引くと、取り込んだ現場で一気に重くなる）。
        # customer も select_related する。自社発行の見積は supplier が空で、
        # 相手先は customer 側に入っているため。
        "quotations": (
            site.quotations.select_related("supplier", "customer")
            .prefetch_related("items__material")
            .order_by("-quotation_date")
        ),
        "budget_items": budget_items,
        # 内訳書・内訳明細書。階層ツリーなので parent も一緒に引く。
        "boq_lines": boq_lines,
        "boq_total": _boq_total(boq_lines),
        "boq_meisai_count": sum(1 for line in boq_lines if line.is_meisai),
        **summary,
    })


@login_required
def site_create(request):
    if request.method == "POST":
        form = SiteForm(request.POST, company=request.user.company, user=request.user)
        if form.is_valid():
            site = form.save(commit=False)
            site.company = request.user.company
            site.created_by = request.user
            site.save()
            return redirect("sites:detail", pk=site.pk)
    else:
        form = SiteForm(company=request.user.company)
    return render(request, "sites/form.html", {"form": form})


def _parse_uploaded_estimate(request, uploaded):
    """アップロードされた見積ファイルを一時ファイルに落として読み取る。

    見出し項目と明細行の両方を、**1回の読み込み**から取る。PDF を2回開くと
    その分だけ待たされるため。

    読み取りに失敗しても例外は投げず、メッセージを出して (None, []) を返す。
    取り込み口で500にするより、手入力に切り替えられるほうが現場は困らない。

    Returns:
        (見出し項目の dict または None, 明細のリスト)
    """
    suffix = Path(uploaded.name).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        for chunk in uploaded.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name
    try:
        rows = read_rows(tmp_path, suffix)
        return parse_rows(rows), extract_lines(rows)
    except Exception as e:  # noqa: BLE001 — 読み取り失敗は画面に出して続行させる
        messages.error(request, f"ファイルを読み取れませんでした: {e}")
        return None, []
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _register_estimate_lines(request, site, company, filename):
    """確認画面から戻ってきた明細を、自社発行の見積として登録する。

    明細を登録しない選択もできるので、チェックが無ければ何もしない。
    材料マスタの引き当ては**ここでサーバ側からやり直す**。画面が持ち回るのは
    名称などの文字列だけで、材料の pk は往復させない。

    Returns:
        作成した Quotation。登録しなかった場合は None。
    """
    if not request.POST.get("register_lines"):
        return None

    lines = deserialize_lines(request.POST.get("lines_json", ""))
    if not lines:
        return None

    matched = match_lines_to_materials(company, lines)
    quotation, _items = create_quotation_from_lines(
        company=company,
        user=request.user,
        site=site,
        customer=site.customer,
        lines=matched,
        # 見積書に見積日の記載を求めない（ラベルが定まらないため）。
        # 取り込んだ日を入れ、必要なら見積画面で直してもらう。
        quotation_date=date.today(),
        quotation_number=site.code,
        source_filename=filename,
    )
    return quotation


@login_required
def site_import(request):
    """見積ファイル（ライデンの CSV / 見積書の PDF）から現場を登録する。

    読み取れた項目は確認画面の初期値に入れ、読み取れなかった項目は空で出す。
    どの項目もその場で直せる。取引先は自動作成せず、引き当てられなければ
    未登録として知らせて選んでもらう（表記ゆれで重複マスタを作らないため）。
    """
    company = request.user.company
    upload_form = EstimateUploadForm()
    site_form = None
    parsed = None
    parsed_lines: list[dict] = []
    parsed_customer_name = ""
    filename = ""

    if request.method == "POST" and request.POST.get("step") == "confirm":
        site_form = SiteForm(request.POST, company=company, user=request.user)
        parsed_customer_name = request.POST.get("parsed_customer_name", "")
        filename = request.POST.get("filename", "")
        if site_form.is_valid():
            # 現場・取込履歴・見積明細はまとめて入るか、まとめて入らないか。
            # 現場だけできて明細が落ちると、同じファイルを入れ直したときに
            # 現場が二重になる。
            with transaction.atomic():
                site = site_form.save(commit=False)
                site.company = company
                site.created_by = request.user
                site.save()
                # 取込履歴は確定時だけ残す。読み取りを試しただけの操作は業務上の
                # 出来事ではないので、履歴に混ぜるとノイズになる。
                EstimateImport.objects.create(
                    company=company,
                    created_by=request.user,
                    customer=site.customer,
                    customer_name_raw=parsed_customer_name,
                    site=site,
                    filename=filename,
                    estimate_number=site.code,
                    amount=site.contract_amount,
                    payment_terms=site.payment_terms,
                )
                quotation = _register_estimate_lines(
                    request, site, company, filename,
                )

            if quotation is not None:
                messages.success(
                    request,
                    f"見積ファイルから現場「{site.name}」と"
                    f"見積明細 {quotation.items.count()} 件を登録しました。",
                )
            else:
                messages.success(
                    request, f"見積ファイルから現場「{site.name}」を登録しました。"
                )
            return redirect("sites:detail", pk=site.pk)
        messages.error(request, "入力内容を確認してください。")

    elif request.method == "POST":
        upload_form = EstimateUploadForm(request.POST, request.FILES)
        if upload_form.is_valid():
            uploaded = upload_form.cleaned_data["file"]
            filename = uploaded.name
            parsed, parsed_lines = _parse_uploaded_estimate(request, uploaded)

        if parsed:
            parsed_customer_name = parsed.get("customer_name") or ""
            matched = find_customer_by_name(company, parsed_customer_name)
            site_form = SiteForm(
                company=company,
                initial={
                    "code": parsed.get("code") or "",
                    "name": parsed.get("name") or "",
                    # 引き当てできたときだけ名前を入れる。読み取った宛名をそのまま
                    # 初期値にすると、確定時に機械が読んだ表記のまま顧客マスタが
                    # できてしまう（取り込みで自動作成しない方針を保つ）。
                    "customer_name": matched.name if matched else "",
                    "payment_terms": parsed.get("payment_terms") or "",
                    "estimate_valid_until": parsed.get("estimate_valid_until") or "",
                    "contract_amount": parsed.get("contract_amount") or 0,
                    "address": parsed.get("address") or "",
                    "note": parsed.get("note") or "",
                    "extracted_details": "\n".join(
                        f"{label}: {value}" for label, value in parsed.get("details", [])
                    ),
                    "start_date": parsed.get("start_date") or "",
                    "end_date": parsed.get("end_date") or "",
                    "status": Site.Status.ESTIMATING,
                },
            )

    customer_matched = (
        find_customer_by_name(company, parsed_customer_name)
        if parsed_customer_name
        else None
    )

    # 材料マスタの引き当ては表示のためだけに行う。確定時はサーバ側で
    # やり直すので、ここでの結果を持ち回ることはしない。
    line_rows = match_lines_to_materials(company, parsed_lines) if parsed_lines else []

    return render(request, "sites/import.html", {
        "upload_form": upload_form,
        "form": site_form,
        "filename": filename,
        "parsed_customer_name": parsed_customer_name,
        "customer_matched": customer_matched,
        "line_rows": line_rows,
        "line_total": sum((r["amount"] or 0) for r in line_rows),
        "unmatched_count": sum(1 for r in line_rows if r["material"] is None),
        "lines_json": serialize_lines(parsed_lines) if parsed_lines else "",
        "read_rows": (
            [(FIELD_LABELS[k], parsed[k]) for k in parsed["found"]] if parsed else []
        ),
        "missing_labels": (
            [FIELD_LABELS[k] for k in parsed["missing"]] if parsed else []
        ),
        "detail_rows": parsed.get("details", []) if parsed else [],
        "recent_imports": (
            EstimateImport.objects.select_related("customer", "site")[:10]
            if site_form is None
            else []
        ),
    })


@login_required
def site_estimate_import(request, pk):
    """既にある現場へ、見積ファイルから読み取った数値を反映する。

    落札や受注のフェーズ移行で自動作成された現場は、件名と概算金額しか
    入っていない。そこへ後からライデンの Excel / CSV や見積書 PDF を入れて
    金額・工期・支払条件などを埋めるための入口。

    新規登録の取り込み（site_import）と違い、**項目ごとに反映するかを選ぶ**。
    現場担当が直した値をファイルの内容で黙って上書きしないため、既定で
    チェックが入るのは今が空欄の項目だけにしてある。
    """
    company = request.user.company
    site = get_object_or_404(Site, pk=pk)
    upload_form = EstimateUploadForm()
    diff_rows: list[dict] = []
    parsed = None
    parsed_customer_name = request.POST.get("parsed_customer_name", "")
    filename = request.POST.get("filename", "")

    if request.method == "POST" and request.POST.get("step") == "confirm":
        # 確認画面が持ち回った値。ファイルは既に手元に無いので読み直さない。
        values = {
            field: request.POST[f"value_{field}"]
            for field, _label in APPLY_FIELDS
            if request.POST.get(f"value_{field}")
        }
        applied = apply_estimate_to_site(
            site, values, set(request.POST.getlist("apply")), company,
        )
        if applied:
            # 取込履歴は実際に反映できたときだけ残す。読み取りを試しただけの
            # 操作は業務上の出来事ではないので、履歴に混ぜるとノイズになる。
            EstimateImport.objects.create(
                company=company,
                created_by=request.user,
                customer=site.customer,
                customer_name_raw=parsed_customer_name,
                site=site,
                filename=filename,
                estimate_number=site.code,
                amount=site.contract_amount,
                payment_terms=site.payment_terms,
            )
            messages.success(
                request,
                f"見積ファイルから {'、'.join(applied)} を現場「{site.name}」に反映しました。",
            )
        else:
            messages.info(request, "反映する項目が選ばれていなかったので、何も変更していません。")
        return redirect("sites:detail", pk=site.pk)

    if request.method == "POST":
        upload_form = EstimateUploadForm(request.POST, request.FILES)
        if upload_form.is_valid():
            uploaded = upload_form.cleaned_data["file"]
            filename = uploaded.name
            # この画面は既にある現場の項目を埋めるためのもの。明細は
            # 新規登録（site_import）側で扱うので、ここでは使わない。
            parsed, _lines = _parse_uploaded_estimate(request, uploaded)

        if parsed:
            parsed_customer_name = parsed.get("customer_name") or ""
            matched = find_customer_by_name(company, parsed_customer_name)
            diff_rows = build_estimate_diff(
                site, estimate_values_for_site(parsed, matched), company,
            )
            if not diff_rows:
                messages.warning(
                    request,
                    "このファイルからは、この現場へ反映できる項目を読み取れませんでした。",
                )

    return render(request, "sites/estimate_import.html", {
        "site": site,
        "upload_form": upload_form,
        "diff_rows": diff_rows,
        "filename": filename,
        "parsed_customer_name": parsed_customer_name,
        "customer_unmatched": bool(parsed_customer_name)
        and not find_customer_by_name(company, parsed_customer_name),
        "missing_labels": (
            [FIELD_LABELS[k] for k in parsed["missing"]] if parsed else []
        ),
        "past_imports": site.estimate_imports.select_related("created_by")[:10],
    })


@login_required
def site_edit(request, pk):
    site = get_object_or_404(Site, pk=pk)
    if request.method == "POST":
        form = SiteForm(
            request.POST, instance=site, company=request.user.company, user=request.user,
        )
        if form.is_valid():
            form.save()
            return redirect("sites:detail", pk=site.pk)
    else:
        form = SiteForm(instance=site, company=request.user.company)
    return render(request, "sites/form.html", {"form": form})


@login_required
def site_delete(request, pk):
    """現場を削除する。一覧・詳細のどちらからでも入れる。

    現場は全業務データの起点なので、削除は日報・実行予算・原価・発注まで
    カスケードする。取り消せないため、確認画面で**何件消えるかを実数で**
    見せてから POST を受ける。
    """
    site = get_object_or_404(Site, pk=pk)

    # 一覧から来たならキャンセルで一覧へ戻す。詳細は削除後に消えるので、
    # 戻り先はこの2つに限定する（外部URLを受け取らないのでリダイレクト先は安全）。
    from_list = request.GET.get("from") == "list"
    back_url = reverse("sites:list") if from_list else reverse(
        "sites:detail", args=[site.pk]
    )

    try:
        impact = collect_site_deletion_impact(site)
    except ProtectedError as exc:
        impact = None
        protected_error = exc
    else:
        protected_error = None

    if request.method == "POST":
        if protected_error is not None:
            messages.error(
                request,
                f"現場「{site.name}」は他のデータから参照されているため削除できません。",
            )
            return redirect(back_url)
        name = site.name
        with transaction.atomic():
            site.delete()
        messages.success(request, f"現場「{name}」を削除しました。")
        return redirect("sites:list")

    return render(request, "sites/confirm_delete.html", {
        "site": site,
        "impact": impact,
        "impact_blocked": protected_error is not None,
        "back_url": back_url,
    })


@login_required
def process_create(request, site_pk):
    """工程を手入力で追加する。AI工程提案を使わない場合の入口。"""
    site = get_object_or_404(Site, pk=site_pk)
    if request.method == "POST":
        form = ProcessForm(request.POST, company=request.user.company)
        if form.is_valid():
            process = form.save(commit=False)
            process.site = site
            process.company = site.company
            process.created_by = request.user
            process.save()
            messages.success(request, f"工程「{process.name}」を追加しました。")
            return redirect("sites:detail", pk=site.pk)
    else:
        # 表示順は既存工程の末尾に付ける
        next_order = site.processes.count() * 10
        form = ProcessForm(
            company=request.user.company,
            initial={"display_order": next_order},
        )
    return render(request, "sites/process_form.html", {"form": form, "site": site})


@login_required
def process_edit(request, pk):
    process = get_object_or_404(Process, pk=pk)
    if request.method == "POST":
        form = ProcessForm(
            request.POST, instance=process, company=request.user.company,
        )
        if form.is_valid():
            form.save()
            messages.success(request, f"工程「{process.name}」を更新しました。")
            return redirect("sites:detail", pk=process.site_id)
    else:
        form = ProcessForm(instance=process, company=request.user.company)
    return render(request, "sites/process_form.html", {
        "form": form,
        "site": process.site,
        "process": process,
    })


@login_required
def process_delete(request, pk):
    process = get_object_or_404(Process, pk=pk)
    site_pk = process.site_id
    if request.method == "POST":
        process.delete()
        messages.success(request, f"工程「{process.name}」を削除しました。")
        return redirect("sites:detail", pk=site_pk)
    return render(request, "sites/process_confirm_delete.html", {"process": process})


# ===================================================================
# 内訳書・内訳明細書（ADR-0016）
#
# BoqLine は元々 estimation.EstimationProject 専用だったが、積算案件は
# 発注機関が必須のため民間工事の現場では作れなかった。現場に直接
# ぶら下げられるようにしたので、現場詳細から一通り操作できるようにする。
# ===================================================================


def _site_boq_lines(site):
    """現場の内訳書を表示順で返す。"""
    return (
        BoqLine.objects.filter(site=site)
        .select_related("parent")
        .order_by("sort_order", "pk")
    )


def _boq_total(lines):
    """内訳書の合計。

    最上位（親を持たない）行だけを足す。種目・科目を立てた内訳書で
    全行を足すと、上位行と細目で二重に数えることになる。
    """
    return sum(
        (line.amount or Decimal("0")) for line in lines if line.parent_id is None
    )


@login_required
def site_boq_edit(request, pk):
    """内訳書を表形式でまとめて編集する。"""
    site = get_object_or_404(Site, pk=pk)
    queryset = _site_boq_lines(site)

    if request.method == "POST":
        formset = BoqLineRowFormSet(request.POST, queryset=queryset)
        if formset.is_valid():
            with transaction.atomic():
                for index, form in enumerate(formset.forms, start=1):
                    if form in formset.deleted_forms:
                        if form.instance.pk:
                            form.instance.delete()
                        continue
                    if not (form.cleaned_data.get("name") or "").strip():
                        # 入力されなかった空行。保存もエラーにもしない。
                        continue

                    line = form.save(commit=False)
                    line.site = site
                    line.project = None
                    line.company = site.company
                    line.sort_order = index
                    if line.amount is None:
                        line.calc_amount()
                    line.save()

                rebuild_tree(list(_site_boq_lines(site)))

            messages.success(request, "内訳書を保存しました。")
            return redirect("sites:detail", pk=site.pk)
    else:
        formset = BoqLineRowFormSet(queryset=queryset)

    return render(request, "sites/boq_edit.html", {
        "site": site,
        "formset": formset,
        "levels": BoqLine.Level.choices,
    })


@login_required
def site_boq_import(request, pk):
    """内訳書ファイル（Excel / PDF）を取り込む。"""
    site = get_object_or_404(Site, pk=pk)
    result = None

    if request.method == "POST":
        form = BoqImportForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = form.cleaned_data["upload"]
            result = boq_import.parse_upload(uploaded.name, uploaded.read())

            for warning in result.warnings:
                messages.warning(request, warning)

            if result.drafts:
                created = boq_import.load_drafts(
                    result.drafts,
                    company=site.company,
                    site=site,
                    user=request.user,
                    replace=form.cleaned_data["replace"],
                )
                messages.success(
                    request,
                    f"{uploaded.name} から {created} 行を取り込みました"
                    f"（うち内訳明細書 {result.meisai_count} 行）。",
                )
                return redirect("sites:detail", pk=site.pk)

            messages.error(request, "取り込める明細がありませんでした。")
    else:
        form = BoqImportForm()

    return render(request, "sites/boq_import.html", {
        "site": site,
        "form": form,
        "result": result,
    })


@login_required
def site_boq_export(request, pk):
    """現場の内訳書を Excel でダウンロードする。"""
    from django.http import HttpResponse

    from apps.estimation.services.boq_export import export_boq_to_excel

    site = get_object_or_404(Site, pk=pk)
    excel_bytes = export_boq_to_excel(site=site)
    response = HttpResponse(
        excel_bytes,
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
    filename = f"boq_site_{site.code or site.pk}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
