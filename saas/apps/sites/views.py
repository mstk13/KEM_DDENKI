import tempfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.sites.forms import EstimateUploadForm, ProcessForm, SiteForm
from apps.sites.importer import FIELD_LABELS, parse_estimate_file
from apps.sites.models import EstimateImport, Process, Site
from apps.sites.services import find_customer_by_name, get_site_summary


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
    return render(request, "sites/detail.html", {
        "site": site,
        "processes": processes,
        "purchase_orders": site.purchase_orders.select_related("supplier").order_by(
            "-order_date"
        ),
        "quotations": site.quotations.select_related("supplier").order_by(
            "-quotation_date"
        ),
        **summary,
    })


@login_required
def site_create(request):
    if request.method == "POST":
        form = SiteForm(request.POST, company=request.user.company)
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

    読み取りに失敗しても例外は投げず、メッセージを出して None を返す。
    取り込み口で500にするより、手入力に切り替えられるほうが現場は困らない。
    """
    suffix = Path(uploaded.name).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        for chunk in uploaded.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name
    try:
        return parse_estimate_file(tmp_path, suffix)
    except Exception as e:  # noqa: BLE001 — 読み取り失敗は画面に出して続行させる
        messages.error(request, f"ファイルを読み取れませんでした: {e}")
        return None
    finally:
        Path(tmp_path).unlink(missing_ok=True)


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
    parsed_customer_name = ""
    filename = ""

    if request.method == "POST" and request.POST.get("step") == "confirm":
        site_form = SiteForm(request.POST, company=company)
        parsed_customer_name = request.POST.get("parsed_customer_name", "")
        filename = request.POST.get("filename", "")
        if site_form.is_valid():
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
            parsed = _parse_uploaded_estimate(request, uploaded)

        if parsed:
            parsed_customer_name = parsed.get("customer_name") or ""
            matched = find_customer_by_name(company, parsed_customer_name)
            site_form = SiteForm(
                company=company,
                initial={
                    "code": parsed.get("code") or "",
                    "name": parsed.get("name") or "",
                    "customer": matched.pk if matched else None,
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

    return render(request, "sites/import.html", {
        "upload_form": upload_form,
        "form": site_form,
        "filename": filename,
        "parsed_customer_name": parsed_customer_name,
        "customer_matched": customer_matched,
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
def site_edit(request, pk):
    site = get_object_or_404(Site, pk=pk)
    if request.method == "POST":
        form = SiteForm(request.POST, instance=site, company=request.user.company)
        if form.is_valid():
            form.save()
            return redirect("sites:detail", pk=site.pk)
    else:
        form = SiteForm(instance=site, company=request.user.company)
    return render(request, "sites/form.html", {"form": form})


@login_required
def site_delete(request, pk):
    site = get_object_or_404(Site, pk=pk)
    if request.method == "POST":
        site.delete()
        messages.success(request, f"現場「{site.name}」を削除しました。")
        return redirect("sites:list")
    return render(request, "sites/confirm_delete.html", {"site": site})


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
