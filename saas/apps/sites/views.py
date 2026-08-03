from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.sites.forms import SiteForm
from apps.sites.models import Site
from apps.sites.services import get_site_summary


@login_required
def site_list(request):
    sites = Site.objects.select_related("customer").order_by("-created_at")
    return render(request, "sites/list.html", {"sites": sites})


@login_required
def site_detail(request, pk):
    site = get_object_or_404(Site, pk=pk)
    processes = site.processes.select_related("work_type").order_by("display_order")
    summary = get_site_summary(site)
    return render(request, "sites/detail.html", {
        "site": site,
        "processes": processes,
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
