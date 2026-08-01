from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.materials.models import Material, PurchaseOrder, PurchaseOrderItem


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
