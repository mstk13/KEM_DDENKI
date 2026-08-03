from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.masters.forms import BusinessCardForm, CustomerForm, SupplierEvaluationForm, SupplierForm
from apps.masters.models import BusinessCard, CostCategory, Customer, Supplier, SupplierEvaluation, WorkType
from apps.masters.services import get_customer_site_history, get_supplier_rating_summary


@login_required
def worktype_list(request):
    return render(request, "masters/worktypes.html", {
        "worktypes": WorkType.objects.all(),
        "cost_categories": CostCategory.objects.all(),
        "customers": Customer.objects.all(),
        "suppliers": Supplier.objects.all(),
    })


@login_required
def customer_list(request):
    customers = Customer.objects.order_by("code")
    return render(request, "masters/customer_list.html", {"customers": customers})


@login_required
def customer_create(request):
    if request.method == "POST":
        form = CustomerForm(request.POST)
        if form.is_valid():
            c = form.save(commit=False)
            c.company = request.user.company
            c.created_by = request.user
            c.save()
            messages.success(request, "得意先を登録しました。")
            return redirect("masters:customer_list")
    else:
        form = CustomerForm()
    return render(request, "masters/customer_form.html", {"form": form, "title": "得意先を登録"})


@login_required
def customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == "POST":
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, "得意先を更新しました。")
            return redirect("masters:customer_detail", pk=pk)
    else:
        form = CustomerForm(instance=customer)
    return render(request, "masters/customer_form.html", {"form": form, "title": "得意先を編集"})


@login_required
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    sites = get_customer_site_history(customer)
    cards = customer.business_cards.all()
    return render(request, "masters/customer_detail.html", {
        "customer": customer, "sites": sites, "cards": cards,
    })


@login_required
def supplier_list(request):
    suppliers = Supplier.objects.order_by("code")
    for s in suppliers:
        s.rating = get_supplier_rating_summary(s)
    return render(request, "masters/supplier_list.html", {"suppliers": suppliers})


@login_required
def supplier_create(request):
    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            s = form.save(commit=False)
            s.company = request.user.company
            s.created_by = request.user
            s.save()
            messages.success(request, "仕入先を登録しました。")
            return redirect("masters:supplier_list")
    else:
        form = SupplierForm()
    return render(request, "masters/supplier_form.html", {"form": form, "title": "仕入先を登録"})


@login_required
def supplier_detail(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    rating = get_supplier_rating_summary(supplier)
    evaluations = SupplierEvaluation.unscoped.filter(supplier=supplier).order_by("-evaluation_date")
    cards = supplier.business_cards.all()
    return render(request, "masters/supplier_detail.html", {
        "supplier": supplier, "rating": rating, "evaluations": evaluations, "cards": cards,
    })


@login_required
def supplier_edit(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == "POST":
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, "仕入先を更新しました。")
            return redirect("masters:supplier_detail", pk=pk)
    else:
        form = SupplierForm(instance=supplier)
    return render(request, "masters/supplier_form.html", {"form": form, "title": "仕入先を編集"})


@login_required
def supplier_eval_create(request, supplier_pk):
    supplier = get_object_or_404(Supplier, pk=supplier_pk)
    if request.method == "POST":
        form = SupplierEvaluationForm(request.POST)
        if form.is_valid():
            ev = form.save(commit=False)
            ev.supplier = supplier
            ev.evaluator = request.user
            ev.company = request.user.company
            ev.created_by = request.user
            ev.save()
            messages.success(request, "評価を登録しました。")
            return redirect("masters:supplier_detail", pk=supplier_pk)
    else:
        form = SupplierEvaluationForm()
    return render(request, "masters/eval_form.html", {"form": form, "supplier": supplier})


@login_required
def business_card_create(request):
    customer_id = request.GET.get("customer")
    supplier_id = request.GET.get("supplier")
    if request.method == "POST":
        form = BusinessCardForm(request.POST, request.FILES)
        if form.is_valid():
            card = form.save(commit=False)
            card.company = request.user.company
            card.created_by = request.user
            if customer_id:
                card.customer_id = customer_id
            if supplier_id:
                card.supplier_id = supplier_id
            card.save()
            messages.success(request, "名刺を登録しました。")
            if customer_id:
                return redirect("masters:customer_detail", pk=customer_id)
            if supplier_id:
                return redirect("masters:supplier_detail", pk=supplier_id)
            return redirect("masters:worktypes")
    else:
        form = BusinessCardForm()
    return render(request, "masters/card_form.html", {"form": form})
