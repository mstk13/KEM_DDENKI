from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.masters.models import CostCategory, Customer, Supplier, WorkStandard, WorkType


@admin.register(WorkType)
class WorkTypeAdmin(SimpleHistoryAdmin):
    list_display = ("code", "name", "parent", "company", "display_order", "is_active")
    list_filter = ("is_active", "company")
    search_fields = ("code", "name")


@admin.register(CostCategory)
class CostCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "display_order")


@admin.register(Customer)
class CustomerAdmin(SimpleHistoryAdmin):
    list_display = ("code", "name", "company", "is_active")
    list_filter = ("is_active", "company")
    search_fields = ("code", "name")


@admin.register(Supplier)
class SupplierAdmin(SimpleHistoryAdmin):
    list_display = ("code", "name", "company", "is_active")
    list_filter = ("is_active", "company")
    search_fields = ("code", "name")


@admin.register(WorkStandard)
class WorkStandardAdmin(SimpleHistoryAdmin):
    list_display = ("name", "work_type", "company", "standard_unit_cost", "is_active")
    list_filter = ("is_active", "company")
