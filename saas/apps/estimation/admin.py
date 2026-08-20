from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.estimation.models import (
    BoqLine,
    CostComparison,
    EstimationItem,
    EstimationProject,
    EstimationStandard,
    ItemAlias,
    ItemEmbedding,
    LaborRate,
    Orderer,
    OrdererDataSource,
    OverheadRule,
    PurchaseRecord,
    WageFloor,
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
        "data_scope",
        "company",
    )
    list_filter = ("category", "status", "data_scope", "company")
    search_fields = ("code", "canonical_name")
    inlines = [ItemAliasInline]


@admin.register(ItemEmbedding)
class ItemEmbeddingAdmin(SimpleHistoryAdmin):
    """埋め込みは再生成可能な派生データ。管理画面では中身を確認するだけ。

    vector（1,024次元）は画面に出さない。読めないうえに表示が重くなる。
    """

    list_display = (
        "estimation_item",
        "model_tag",
        "dim",
        "source_text",
        "updated_at",
        "company",
    )
    list_filter = ("model_tag", "company")
    search_fields = ("estimation_item__code", "estimation_item__canonical_name")
    readonly_fields = ("dim", "source_hash")
    exclude = ("vector",)


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
        "data_scope",
        "company",
    )
    list_filter = ("source_type", "status", "matched_by", "data_scope", "company")
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
        "orderer", "category", "scope", "name",
        "update_cycle", "data_format", "is_free", "last_checked_at", "company",
    )
    list_filter = ("category", "scope", "data_format", "is_free", "company")
    search_fields = ("name", "orderer__name")


@admin.register(LaborRate)
class LaborRateAdmin(SimpleHistoryAdmin):
    list_display = (
        "valid_from", "prefecture", "occupation_name",
        "unit_price", "status", "data_scope", "company",
    )
    list_filter = ("status", "data_scope", "prefecture", "company")
    search_fields = ("occupation_name", "occupation_code", "prefecture")


class WorkRateInline(admin.TabularInline):
    model = WorkRate
    extra = 0
    fields = ("work_code", "work_name", "unit", "status", "extracted_by")


class OverheadRuleInline(admin.TabularInline):
    model = OverheadRule
    extra = 0
    fields = ("work_category", "cost_type", "status")


@admin.register(EstimationStandard)
class EstimationStandardAdmin(SimpleHistoryAdmin):
    list_display = (
        "name", "orderer", "valid_from", "applies_by",
        "status", "data_scope", "company",
    )
    list_filter = ("status", "applies_by", "data_scope", "company")
    search_fields = ("name", "orderer__name")
    inlines = [WorkRateInline, OverheadRuleInline]


@admin.register(WorkRate)
class WorkRateAdmin(SimpleHistoryAdmin):
    list_display = (
        "work_name", "unit", "standard",
        "status", "extracted_by", "data_scope", "company",
    )
    list_filter = ("status", "extracted_by", "data_scope", "company")
    search_fields = ("work_name", "work_code")


@admin.register(OverheadRule)
class OverheadRuleAdmin(SimpleHistoryAdmin):
    list_display = (
        "cost_type", "work_category", "standard",
        "status", "data_scope", "company",
    )
    list_filter = ("cost_type", "work_category", "status", "data_scope", "company")
    search_fields = ("work_category",)


@admin.register(WageFloor)
class WageFloorAdmin(SimpleHistoryAdmin):
    list_display = (
        "municipality", "occupation_name", "hourly_floor",
        "worker_type", "valid_from", "company",
    )
    list_filter = ("municipality", "worker_type", "company")
    search_fields = ("municipality", "occupation_name")


# --- M3/M4 ---


class BoqLineInline(admin.TabularInline):
    model = BoqLine
    extra = 0
    fields = ("level", "sort_order", "name", "unit", "quantity", "unit_price", "amount")


@admin.register(EstimationProject)
class EstimationProjectAdmin(SimpleHistoryAdmin):
    list_display = ("name", "orderer", "primary_work_category", "status", "company")
    list_filter = ("status", "primary_work_category", "company")
    search_fields = ("name", "orderer__name")
    inlines = [BoqLineInline]


@admin.register(BoqLine)
class BoqLineAdmin(SimpleHistoryAdmin):
    # 持ち主は積算案件か現場のどちらか。両方出さないとどちらに属する明細か
    # 一覧で分からない。
    list_display = (
        "name", "level", "project", "site", "unit", "quantity", "amount", "company",
    )
    list_filter = ("level", "company")
    search_fields = ("name", "site__name", "project__name")


@admin.register(PurchaseRecord)
class PurchaseRecordAdmin(SimpleHistoryAdmin):
    list_display = (
        "raw_name", "purchase_date", "quantity", "unit_price",
        "supplier", "import_source", "data_scope", "company",
    )
    list_filter = ("import_source", "data_scope", "company")
    search_fields = ("raw_name", "raw_code")


@admin.register(CostComparison)
class CostComparisonAdmin(SimpleHistoryAdmin):
    list_display = (
        "project", "estimation_item", "standard_price",
        "own_price", "diff_amount", "diff_ratio", "company",
    )
    list_filter = ("company",)
    search_fields = ("estimation_item__canonical_name",)
