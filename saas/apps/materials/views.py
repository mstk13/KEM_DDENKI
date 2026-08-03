from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.materials.forms import DeliveryForm, MaterialForm, PurchaseOrderForm, QuotationForm
from apps.materials.models import (
    Delivery,
    Inventory,
    Material,
    PurchaseOrder,
    Quotation,
)
from apps.materials.services import compare_quotations, inspect_delivery


@login_required
def material_list(request):
    materials = Material.objects.order_by("code")
    purchase_orders = PurchaseOrder.objects.select_related(
        "site", "supplier"
    ).order_by("-order_date")[:20]
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
            messages.success(request, "材料を登録しました。")
            return redirect("materials:list")
    else:
        form = MaterialForm(company=request.user.company)
    return render(request, "materials/form.html", {"form": form, "title": "材料を登録"})


@login_required
def material_edit(request, pk):
    material = get_object_or_404(Material, pk=pk)
    if request.method == "POST":
        form = MaterialForm(request.POST, instance=material, company=request.user.company)
        if form.is_valid():
            form.save()
            messages.success(request, "材料を更新しました。")
            return redirect("materials:list")
    else:
        form = MaterialForm(instance=material, company=request.user.company)
    return render(request, "materials/form.html", {"form": form, "title": "材料を編集"})


# ── 発注 ──

@login_required
def po_list(request):
    orders = PurchaseOrder.objects.select_related(
        "site", "supplier"
    ).order_by("-order_date")
    return render(request, "materials/po_list.html", {"orders": orders})


@login_required
def po_create(request):
    if request.method == "POST":
        form = PurchaseOrderForm(request.POST, request.FILES, company=request.user.company)
        if form.is_valid():
            po = form.save(commit=False)
            po.company = request.user.company
            po.created_by = request.user
            po.save()
            messages.success(request, "発注書を作成しました。")
            return redirect("materials:po_detail", pk=po.pk)
    else:
        form = PurchaseOrderForm(company=request.user.company)
    return render(request, "materials/form.html", {"form": form, "title": "発注書を作成"})


@login_required
def po_detail(request, pk):
    po = get_object_or_404(PurchaseOrder.objects.select_related("site", "supplier"), pk=pk)
    items = po.items.select_related("material", "work_type").all()
    deliveries = po.deliveries.all()
    return render(request, "materials/po_detail.html", {
        "po": po,
        "items": items,
        "deliveries": deliveries,
    })


# ── 見積 ──

@login_required
def quotation_list(request):
    quotations = Quotation.objects.select_related(
        "site", "supplier"
    ).order_by("-quotation_date")
    return render(request, "materials/quotation_list.html", {"quotations": quotations})


@login_required
def quotation_create(request):
    if request.method == "POST":
        form = QuotationForm(request.POST, request.FILES, company=request.user.company)
        if form.is_valid():
            q = form.save(commit=False)
            q.company = request.user.company
            q.created_by = request.user
            q.save()
            messages.success(request, "見積を登録しました。")
            return redirect("materials:quotation_list")
    else:
        form = QuotationForm(company=request.user.company)
    return render(request, "materials/form.html", {"form": form, "title": "見積を登録"})


@login_required
def quotation_compare(request):
    """同一材料の仕入先別見積比較。"""
    material_id = request.GET.get("material_id")
    site_id = request.GET.get("site_id")
    results = []
    materials = Material.objects.order_by("name")

    if material_id:
        results = compare_quotations(material_id, site_id)

    return render(request, "materials/quotation_compare.html", {
        "materials": materials,
        "results": results,
        "selected_material_id": int(material_id) if material_id else None,
    })


# ── 納品・検収 ──

@login_required
def delivery_create(request, po_pk):
    po = get_object_or_404(PurchaseOrder, pk=po_pk)
    if request.method == "POST":
        form = DeliveryForm(request.POST)
        if form.is_valid():
            delivery = form.save(commit=False)
            delivery.purchase_order = po
            delivery.company = request.user.company
            delivery.created_by = request.user
            delivery.save()
            messages.success(request, "納品を記録しました。")
            return redirect("materials:po_detail", pk=po.pk)
    else:
        form = DeliveryForm()
    return render(request, "materials/delivery_form.html", {"form": form, "po": po})


@login_required
def delivery_inspect(request, pk):
    """検収を実行する。"""
    delivery = get_object_or_404(Delivery, pk=pk)
    if request.method == "POST":
        inspect_delivery(delivery, inspected_by=request.user)
        messages.success(request, "検収を完了し、在庫・原価を更新しました。")
    return redirect("materials:po_detail", pk=delivery.purchase_order.pk)


# ── 在庫 ──

@login_required
def inventory_list(request):
    inventories = Inventory.objects.select_related(
        "material", "site"
    ).order_by("material__name", "site__name")
    return render(request, "materials/inventory_list.html", {"inventories": inventories})
