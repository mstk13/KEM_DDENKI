from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.masters.forms import CustomerForm, SupplierForm
from apps.masters.models import CostCategory, Customer, Supplier, WorkType


@login_required
def worktype_list(request):
    return render(request, "masters/worktypes.html", {
        "worktypes": WorkType.objects.all(),
        "cost_categories": CostCategory.objects.all(),
        "customers": Customer.objects.all(),
        "suppliers": Supplier.objects.all(),
    })


# =====================================================================
# 顧客管理
# =====================================================================

@login_required
def customer_list(request):
    qs = Customer.objects.order_by("code")
    return render(request, "masters/customer_list.html", {"customers": qs})


@login_required
def customer_create(request):
    if request.method == "POST":
        form = CustomerForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.company = request.user.company
            obj.created_by = request.user
            obj.save()
            messages.success(request, "顧客を登録しました。")
            return redirect("masters:customer_list")
    else:
        form = CustomerForm()
    return render(request, "masters/customer_form.html", {"form": form, "type_label": "顧客"})


@login_required
def customer_edit(request, pk):
    obj = get_object_or_404(Customer, pk=pk)
    if request.method == "POST":
        form = CustomerForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "顧客を更新しました。")
            return redirect("masters:customer_list")
    else:
        form = CustomerForm(instance=obj)
    return render(request, "masters/customer_form.html", {"form": form, "type_label": "顧客"})


@login_required
def customer_delete(request, pk):
    obj = get_object_or_404(Customer, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "顧客を削除しました。")
        return redirect("masters:customer_list")
    return render(request, "masters/confirm_delete.html", {"obj": obj, "type_label": "顧客", "back_url": "masters:customer_list"})


# =====================================================================
# 発注先（仕入先）管理
# =====================================================================

@login_required
def supplier_list(request):
    qs = Supplier.objects.order_by("code")
    return render(request, "masters/supplier_list.html", {"suppliers": qs})


@login_required
def supplier_create(request):
    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.company = request.user.company
            obj.created_by = request.user
            obj.save()
            messages.success(request, "発注先を登録しました。")
            return redirect("masters:supplier_list")
    else:
        form = SupplierForm()
    return render(request, "masters/customer_form.html", {"form": form, "type_label": "発注先"})


@login_required
def supplier_edit(request, pk):
    obj = get_object_or_404(Supplier, pk=pk)
    if request.method == "POST":
        form = SupplierForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "発注先を更新しました。")
            return redirect("masters:supplier_list")
    else:
        form = SupplierForm(instance=obj)
    return render(request, "masters/customer_form.html", {"form": form, "type_label": "発注先"})


@login_required
def supplier_delete(request, pk):
    obj = get_object_or_404(Supplier, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "発注先を削除しました。")
        return redirect("masters:supplier_list")
    return render(request, "masters/confirm_delete.html", {"obj": obj, "type_label": "発注先", "back_url": "masters:supplier_list"})
