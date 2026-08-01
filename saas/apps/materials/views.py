from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.materials.forms import MaterialForm, PurchaseOrderForm
from apps.materials.models import Material, PurchaseOrder


@login_required
def material_list(request):
    materials = Material.objects.order_by("code")
    purchase_orders = PurchaseOrder.objects.select_related(
        "site", "supplier"
    ).order_by("-order_date")
    return render(request, "materials/list.html", {
        "materials": materials,
        "purchase_orders": purchase_orders,
    })


@login_required
def material_create(request):
    if request.method == "POST":
        form = MaterialForm(request.POST, company=request.user.company)
        if form.is_valid():
            m = form.save(commit=False)
            m.company = request.user.company
            m.created_by = request.user
            m.save()
            return redirect("materials:list")
    else:
        form = MaterialForm(company=request.user.company)
    return render(request, "materials/form.html", {"form": form, "title": "材料を登録"})


@login_required
def po_create(request):
    if request.method == "POST":
        form = PurchaseOrderForm(request.POST, company=request.user.company)
        if form.is_valid():
            po = form.save(commit=False)
            po.company = request.user.company
            po.created_by = request.user
            po.save()
            return redirect("materials:list")
    else:
        form = PurchaseOrderForm(company=request.user.company)
    return render(request, "materials/form.html", {"form": form, "title": "発注書を作成"})
