from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.sites.forms import ProcessForm, SiteForm
from apps.sites.models import Process, Site
from apps.sites.services import get_site_summary


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
