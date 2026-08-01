from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.costs.models import BudgetItem, CostTransaction


@admin.register(BudgetItem)
class BudgetItemAdmin(SimpleHistoryAdmin):
    list_display = (
        "site", "work_type", "cost_category", "name", "quantity", "unit_price", "amount",
    )
    list_filter = ("company", "cost_category")
    search_fields = ("name", "site__name")


@admin.register(CostTransaction)
class CostTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_date", "site", "work_type", "cost_category",
        "source_type", "amount", "company",
    )
    list_filter = ("source_type", "cost_category", "company")
    search_fields = ("site__name",)
    readonly_fields = (
        "source_type", "source_id", "amount", "transaction_date",
        "site", "work_type", "cost_category", "company",
    )

    def has_change_permission(self, request, obj=None):
        return False  # CostTransaction は不変（追記のみ）

    def has_delete_permission(self, request, obj=None):
        return False
