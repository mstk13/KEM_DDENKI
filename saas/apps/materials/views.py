from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.materials.forms import (
    DeliveryForm,
    DeliveryItemForm,
    MaterialForm,
    PurchaseOrderForm,
    PurchaseOrderItemForm,
    QuotationForm,
    QuotationItemForm,
)
from apps.materials.models import (
    Delivery,
    DeliveryItem,
    Inventory,
    Material,
    PurchaseOrder,
    PurchaseOrderItem,
    Quotation,
    QuotationItem,
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
            return redirect("materials:quotation_detail", pk=q.pk)
    else:
        form = QuotationForm(company=request.user.company)
    return render(request, "materials/form.html", {"form": form, "title": "見積を登録"})


@login_required
def quotation_detail(request, pk):
    quotation = get_object_or_404(
        Quotation.objects.select_related("site", "supplier"), pk=pk,
    )
    items = quotation.items.select_related("material").all()
    item_form = QuotationItemForm(company=request.user.company)
    return render(request, "materials/quotation_detail.html", {
        "quotation": quotation,
        "items": items,
        "item_form": item_form,
    })


@login_required
def quotation_item_add(request, quotation_pk):
    quotation = get_object_or_404(Quotation, pk=quotation_pk)
    if request.method == "POST":
        form = QuotationItemForm(request.POST, company=request.user.company)
        if form.is_valid():
            item = form.save(commit=False)
            item.quotation = quotation
            item.company = request.user.company
            item.created_by = request.user
            item.amount = item.quantity * item.unit_price
            item.save()
            # 合計金額を再計算
            _recalculate_quotation_total(quotation)
            messages.success(request, "明細を追加しました。")
    return redirect("materials:quotation_detail", pk=quotation.pk)


@login_required
def quotation_item_edit(request, pk):
    item = get_object_or_404(QuotationItem, pk=pk)
    quotation = item.quotation
    if request.method == "POST":
        form = QuotationItemForm(request.POST, instance=item, company=request.user.company)
        if form.is_valid():
            item = form.save(commit=False)
            item.amount = item.quantity * item.unit_price
            item.save()
            _recalculate_quotation_total(quotation)
            messages.success(request, "明細を更新しました。")
            return redirect("materials:quotation_detail", pk=quotation.pk)
    else:
        form = QuotationItemForm(instance=item, company=request.user.company)
    return render(request, "materials/quotation_item_edit.html", {
        "form": form,
        "item": item,
        "quotation": quotation,
    })


@login_required
def quotation_item_delete(request, pk):
    item = get_object_or_404(QuotationItem, pk=pk)
    quotation = item.quotation
    if request.method == "POST":
        item.delete()
        _recalculate_quotation_total(quotation)
        messages.success(request, "明細を削除しました。")
    return redirect("materials:quotation_detail", pk=quotation.pk)


def _recalculate_quotation_total(quotation):
    from django.db.models import Sum
    total = quotation.items.aggregate(t=Sum("amount"))["t"] or 0
    quotation.total_amount = total
    quotation.save(update_fields=["total_amount"])


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


@login_required
def quotation_pdf(request, pk):
    """見積書をPDF出力する。"""
    from apps.materials.services import generate_quotation_pdf

    quotation = get_object_or_404(
        Quotation.objects.select_related("site", "supplier"), pk=pk,
    )
    items = quotation.items.select_related("material").all()

    from django.http import HttpResponse
    response = HttpResponse(content_type="application/pdf")
    filename = f"見積書_{quotation.pk}_{quotation.quotation_date}.pdf"
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    generate_quotation_pdf(response, quotation, items, request.user)
    return response


# ── 発注 ──


@login_required
def po_list(request):
    from apps.sites.models import Site

    orders = PurchaseOrder.objects.select_related(
        "site", "supplier", "ordered_by"
    ).order_by("-order_date")

    selected_site = request.GET.get("site", "")
    if selected_site:
        orders = orders.filter(site_id=selected_site)

    return render(request, "materials/po_list.html", {
        "orders": orders,
        "sites": Site.objects.order_by("name"),
        "selected_site": selected_site,
    })


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
        # 現場詳細から遷移した場合は現場を初期選択しておく
        form = PurchaseOrderForm(
            company=request.user.company,
            initial=_site_initial(request),
        )
    return render(request, "materials/form.html", {"form": form, "title": "発注書を作成"})


def _site_initial(request):
    """?site=<pk> が付いていれば現場の初期値を返す。"""
    site_id = request.GET.get("site")
    return {"site": site_id} if site_id else {}


@login_required
def po_detail(request, pk):
    po = get_object_or_404(
        PurchaseOrder.objects.select_related("site", "supplier", "ordered_by"), pk=pk,
    )
    items = po.items.select_related("material", "work_type").all()
    deliveries = po.deliveries.select_related("received_by", "inspected_by").all()
    item_form = PurchaseOrderItemForm(company=request.user.company)
    return render(request, "materials/po_detail.html", {
        "po": po,
        "items": items,
        "deliveries": deliveries,
        "item_form": item_form,
    })


@login_required
def po_item_add(request, po_pk):
    po = get_object_or_404(PurchaseOrder, pk=po_pk)
    if request.method == "POST":
        form = PurchaseOrderItemForm(request.POST, company=request.user.company)
        if form.is_valid():
            item = form.save(commit=False)
            item.purchase_order = po
            item.company = request.user.company
            item.created_by = request.user
            item.save()
            po.recalculate_total()
            messages.success(request, "発注明細を追加しました。")
    return redirect("materials:po_detail", pk=po.pk)


@login_required
def po_item_delete(request, pk):
    item = get_object_or_404(PurchaseOrderItem, pk=pk)
    po = item.purchase_order
    if request.method == "POST":
        item.delete()
        po.recalculate_total()
        messages.success(request, "発注明細を削除しました。")
    return redirect("materials:po_detail", pk=po.pk)


# ── 発注書 Excel 出力 ──


@login_required
def po_excel_download(request, pk):
    """発注書 Excel ダウンロード。"""
    from django.http import HttpResponse

    from apps.materials.excel_service import generate_purchase_order_excel

    po = get_object_or_404(
        PurchaseOrder.objects.select_related("site", "supplier", "quotation"), pk=pk,
    )
    items = po.items.select_related("material", "work_type").all()

    buf = generate_purchase_order_excel(po, items)
    filename = f"発注書_PO-{po.pk:05d}_{po.order_date}.xlsx"
    response = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def po_acceptance_excel_download(request, pk):
    """発注請書 Excel ダウンロード。"""
    from django.http import HttpResponse

    from apps.materials.excel_service import generate_purchase_order_acceptance_excel

    po = get_object_or_404(
        PurchaseOrder.objects.select_related("site", "supplier", "quotation"), pk=pk,
    )
    items = po.items.select_related("material", "work_type").all()

    buf = generate_purchase_order_acceptance_excel(po, items)
    filename = f"発注請書_PO-{po.pk:05d}_{po.order_date}.xlsx"
    response = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ── 発注書 PDF 出力 ──


@login_required
def po_pdf_download(request, pk):
    """発注書 PDF ダウンロード。"""
    from django.http import HttpResponse

    from apps.materials.services import generate_purchase_order_pdf

    po = get_object_or_404(
        PurchaseOrder.objects.select_related("site", "supplier", "quotation"), pk=pk,
    )
    items = po.items.select_related("material", "work_type").all()

    response = HttpResponse(content_type="application/pdf")
    filename = f"発注書_PO-{po.pk:05d}_{po.order_date}.pdf"
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    generate_purchase_order_pdf(response, po, items, request.user)
    return response


@login_required
def po_acceptance_pdf_download(request, pk):
    """発注請書 PDF ダウンロード。"""
    from django.http import HttpResponse

    from apps.materials.services import generate_purchase_order_acceptance_pdf

    po = get_object_or_404(
        PurchaseOrder.objects.select_related("site", "supplier", "quotation"), pk=pk,
    )
    items = po.items.select_related("material", "work_type").all()

    response = HttpResponse(content_type="application/pdf")
    filename = f"発注請書_PO-{po.pk:05d}_{po.order_date}.pdf"
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    generate_purchase_order_acceptance_pdf(response, po, items, request.user)
    return response


# ── CSV インポート ──


@login_required
def po_csv_import(request, site_id=None):
    """仕入先CSVから発注書を作成する。

    Step 1: CSVアップロード + 仕入先選択
    Step 2: パース結果を確認 → 発注書作成
    """
    from apps.materials.excel_service import parse_supplier_csv
    from apps.sites.models import Site

    sites = Site.objects.order_by("name")
    suppliers = []
    from apps.masters.models import Supplier
    suppliers = Supplier.unscoped.filter(
        company=request.user.company, is_active=True,
    ).order_by("name")

    if request.method == "POST" and "csv_file" in request.FILES:
        # Step 1: Parse CSV
        import json
        from decimal import Decimal

        csv_file = request.FILES["csv_file"]
        supplier_id = request.POST.get("supplier")
        selected_site_id = request.POST.get("site") or site_id

        parsed_items = parse_supplier_csv(csv_file)

        # 金額を計算して付与
        for item in parsed_items:
            item["amount"] = int(item["quantity"] * item["unit_price"])

        subtotal = sum(item["amount"] for item in parsed_items)

        # JSON シリアライズ用にDecimal→str変換
        items_for_json = [
            {
                "name": it["name"],
                "quantity": str(it["quantity"]),
                "unit": it["unit"],
                "unit_price": str(it["unit_price"]),
                "tax_rate": str(it["tax_rate"]),
            }
            for it in parsed_items
        ]

        return render(request, "materials/csv_confirm.html", {
            "parsed_items": parsed_items,
            "supplier_id": supplier_id,
            "site_id": selected_site_id,
            "sites": sites,
            "suppliers": suppliers,
            "csv_filename": csv_file.name,
            "subtotal": subtotal,
            "items_json": json.dumps(items_for_json, ensure_ascii=False),
        })

    if request.method == "POST" and "confirm_import" in request.POST:
        # Step 2: Create PO from parsed data
        import json
        from datetime import date
        from decimal import Decimal

        supplier_id = request.POST.get("supplier_id")
        selected_site_id = request.POST.get("site_id")
        items_json = request.POST.get("items_json", "[]")

        supplier = get_object_or_404(Supplier, pk=supplier_id)
        site = get_object_or_404(Site, pk=selected_site_id) if selected_site_id else None

        if not site:
            messages.error(request, "現場を選択してください。")
            return redirect("materials:csv_import")

        # Create PurchaseOrder
        po = PurchaseOrder(
            company=request.user.company,
            created_by=request.user,
            site=site,
            supplier=supplier,
            order_date=date.today(),
            subject=site.name,
            payment_terms="月末締翌月末払",
        )
        po.save()

        # Create items
        items_data = json.loads(items_json)
        for item_data in items_data:
            PurchaseOrderItem.objects.create(
                company=request.user.company,
                created_by=request.user,
                purchase_order=po,
                material_name=item_data.get("name", ""),
                quantity=Decimal(str(item_data.get("quantity", 0))),
                unit=item_data.get("unit", ""),
                unit_price=Decimal(str(item_data.get("unit_price", 0))),
                tax_rate=Decimal(str(item_data.get("tax_rate", "0.10"))),
            )

        po.recalculate_total()
        messages.success(request, f"発注書 PO-{po.pk:05d} を作成しました（{len(items_data)}件）。")
        return redirect("materials:po_detail", pk=po.pk)

    return render(request, "materials/csv_upload.html", {
        "sites": sites,
        "suppliers": suppliers,
        "selected_site_id": site_id,
    })


# ── 納品・受領・検収 ──


@login_required
def delivery_create(request, po_pk):
    """納品を記録する（画像アップロード対応）。"""
    po = get_object_or_404(PurchaseOrder, pk=po_pk)
    po_items = po.items.select_related("material").all()

    if request.method == "POST":
        form = DeliveryForm(request.POST)
        image = request.FILES.get("delivery_image")

        if form.is_valid():
            delivery = form.save(commit=False)
            delivery.purchase_order = po
            delivery.company = request.user.company
            delivery.created_by = request.user

            if image:
                delivery.image = image
                delivery.original_filename = image.name

            delivery.save()

            # 画像がある場合はOCRで明細を自動生成
            if image:
                try:
                    from apps.materials.services import extract_delivery_items_from_image
                    extracted_items = extract_delivery_items_from_image(
                        delivery, po, request.user.company,
                    )
                    if extracted_items:
                        messages.success(
                            request,
                            f"納品を記録し、画像から{len(extracted_items)}件の明細を読み取りました。"
                            "内容を確認・編集してください。",
                        )
                        return redirect("materials:delivery_detail", pk=delivery.pk)
                except Exception as e:
                    messages.warning(request, f"画像の読み取りに失敗しました: {e}")

            # 画像なしまたはOCR失敗 → PO明細から明細テンプレを生成
            if not delivery.items.exists():
                for po_item in po_items:
                    DeliveryItem.unscoped.create(
                        company=request.user.company,
                        created_by=request.user,
                        delivery=delivery,
                        material=po_item.material,
                        ordered_qty=po_item.quantity,
                        delivered_qty=0,
                    )

            messages.success(request, "納品を記録しました。明細の納品数量を入力してください。")
            return redirect("materials:delivery_detail", pk=delivery.pk)
    else:
        form = DeliveryForm()

    return render(request, "materials/delivery_form.html", {
        "form": form,
        "po": po,
        "po_items": po_items,
    })


@login_required
def delivery_detail(request, pk):
    """納品の詳細・明細編集画面。"""
    delivery = get_object_or_404(
        Delivery.objects.select_related(
            "purchase_order__site", "purchase_order__supplier",
            "received_by", "inspected_by",
        ),
        pk=pk,
    )
    items = delivery.items.select_related("material").all()
    return render(request, "materials/delivery_detail.html", {
        "delivery": delivery,
        "items": items,
        "po": delivery.purchase_order,
    })


@login_required
def delivery_item_edit(request, pk):
    """納品明細を編集する。"""
    item = get_object_or_404(DeliveryItem, pk=pk)
    delivery = item.delivery
    if request.method == "POST":
        form = DeliveryItemForm(request.POST, instance=item, company=request.user.company)
        if form.is_valid():
            form.save()
            messages.success(request, "明細を更新しました。")
            return redirect("materials:delivery_detail", pk=delivery.pk)
    else:
        form = DeliveryItemForm(instance=item, company=request.user.company)
    return render(request, "materials/delivery_item_edit.html", {
        "form": form,
        "item": item,
        "delivery": delivery,
    })


@login_required
def delivery_receive(request, pk):
    """受領を確認する。"""
    delivery = get_object_or_404(Delivery, pk=pk)
    if request.method == "POST":
        delivery.received = True
        delivery.received_by = request.user
        delivery.received_at = timezone.now()
        delivery.save(update_fields=["received", "received_by", "received_at"])
        messages.success(request, "受領を確認しました。")
    return redirect("materials:po_detail", pk=delivery.purchase_order.pk)


@login_required
def delivery_inspect(request, pk):
    """検収を実行する（受領確認済みが前提）。"""
    delivery = get_object_or_404(Delivery, pk=pk)
    if request.method == "POST":
        if not delivery.received:
            messages.error(request, "先に受領確認を行ってください。")
            return redirect("materials:po_detail", pk=delivery.purchase_order.pk)
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
