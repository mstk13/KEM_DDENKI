from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.estimation.models import (
    EstimationItem,
    EstimationStandard,
    ItemAlias,
    LaborRate,
    Orderer,
    OrdererDataSource,
    OverheadRule,
    WorkRate,
)


class ItemAliasInline(admin.TabularInline):
    model = ItemAlias
    extra = 0
    fields = (
        "source_type",
        "raw_name",
        "normalized_name",
        "confidence",
        "matched_by",
        "status",
    )
    readonly_fields = ("normalized_name", "confidence", "matched_by")


@admin.register(EstimationItem)
class EstimationItemAdmin(SimpleHistoryAdmin):
    list_display = (
        "code",
        "canonical_name",
        "category",
        "unit",
        "standard_price",
        "status",
        "company",
    )
    list_filter = ("category", "status", "company")
    search_fields = ("code", "canonical_name")
    inlines = [ItemAliasInline]


@admin.register(ItemAlias)
class ItemAliasAdmin(SimpleHistoryAdmin):
    list_display = (
        "raw_name",
        "normalized_name",
        "source_type",
        "estimation_item",
        "confidence",
        "matched_by",
        "status",
        "company",
    )
    list_filter = ("source_type", "status", "matched_by", "company")
    search_fields = ("raw_name", "normalized_name")


class OrdererDataSourceInline(admin.TabularInline):
    model = OrdererDataSource
    extra = 0
    fields = (
        "category",
        "scope",
        "name",
        "source_url",
        "update_cycle",
        "data_format",
        "is_free",
        "last_checked_at",
    )


@admin.register(Orderer)
class OrdererAdmin(SimpleHistoryAdmin):
    list_display = ("name", "kind", "system_type", "prefecture", "is_active", "company")
    list_filter = ("kind", "system_type", "is_active", "company")
    search_fields = ("name",)
    inlines = [OrdererDataSourceInline]


@admin.register(OrdererDataSource)
class OrdererDataSourceAdmin(SimpleHistoryAdmin):
    list_display = (
        "orderer",
        "category",
        "scope",
        "name",
        "update_cycle",
        "data_format",
        "is_free",
        "last_checked_at",
        "company",
    )
    list_filter = ("category", "scope", "data_format", "is_free", "company")
    search_fields = ("name", "orderer__name")


@admin.register(LaborRate)
class LaborRateAdmin(SimpleHistoryAdmin):
    list_display = ("fiscal_year", "prefecture", "trade", "amount", "company")
    list_filter = ("fiscal_year", "prefecture", "company")
    search_fields = ("trade", "prefecture")


class WorkRateInline(admin.TabularInline):
    model = WorkRate
    extra = 0
    fields = ("work_code", "work_name", "unit", "status", "extracted_by")


class OverheadRuleInline(admin.TabularInline):
    model = OverheadRule
    extra = 0
    fields = ("category", "work_type_label", "status")


@admin.register(EstimationStandard)
class EstimationStandardAdmin(SimpleHistoryAdmin):
    list_display = ("name", "orderer", "fiscal_year", "status", "company")
    list_filter = ("fiscal_year", "status", "company")
    search_fields = ("name", "orderer__name")
    inlines = [WorkRateInline, OverheadRuleInline]


@admin.register(WorkRate)
class WorkRateAdmin(SimpleHistoryAdmin):
    list_display = ("work_name", "unit", "standard", "status", "extracted_by", "company")
    list_filter = ("status", "extracted_by", "company")
    search_fields = ("work_name", "work_code")


@admin.register(OverheadRule)
class OverheadRuleAdmin(SimpleHistoryAdmin):
    list_display = ("category", "work_type_label", "standard", "status", "company")
    list_filter = ("category", "status", "company")
    search_fields = ("work_type_label",)
