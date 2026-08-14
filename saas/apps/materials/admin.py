from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.materials.models import (
    Material,
    MaterialSupplier,
    ProcurementRecord,
    PurchaseOrder,
    PurchaseOrderItem,
)


@admin.register(Material)
class MaterialAdmin(SimpleHistoryAdmin):
    list_display = ("code", "name", "unit", "category", "company", "is_active")
    list_filter = ("is_active", "company")
    search_fields = ("code", "name")


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 0


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(SimpleHistoryAdmin):
    list_display = ("__str__", "site", "supplier", "order_date", "status", "company")
    list_filter = ("status", "company")
    inlines = [PurchaseOrderItemInline]


@admin.register(PurchaseOrderItem)
class PurchaseOrderItemAdmin(SimpleHistoryAdmin):
    list_display = ("purchase_order", "material", "quantity", "unit_price", "work_type")


class MaterialSupplierInline(admin.TabularInline):
    model = MaterialSupplier
    extra = 0
    fields = ("supplier", "supplier_code", "standard_unit_price", "lead_time_days", "is_preferred")


@admin.register(MaterialSupplier)
class MaterialSupplierAdmin(SimpleHistoryAdmin):
    list_display = (
        "material", "supplier", "standard_unit_price",
        "lead_time_days", "is_preferred", "company",
    )
    list_filter = ("is_preferred", "company")
    search_fields = ("material__name", "supplier__name")


@admin.register(ProcurementRecord)
class ProcurementRecordAdmin(SimpleHistoryAdmin):
    list_display = (
        "site", "material", "supplier", "ordered_date",
        "delivered_date", "actual_lead_days", "unit_price_paid", "company",
    )
    list_filter = ("company",)
    search_fields = ("material__name", "supplier__name", "site__name")
