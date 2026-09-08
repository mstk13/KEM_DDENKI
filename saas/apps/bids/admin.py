from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.bids.models import (
    BidCompetitor,
    BidCost,
    BidProject,
    Qualification,
    ScrapeTarget,
    UnifiedQualification,
    UnitPrice,
)


class BidCostInline(admin.StackedInline):
    model = BidCost
    extra = 0


class BidCompetitorInline(admin.TabularInline):
    model = BidCompetitor
    extra = 0


@admin.register(BidProject)
class BidProjectAdmin(SimpleHistoryAdmin):
    list_display = (
        "title", "client", "region", "category", "status",
        "budget", "deadline", "company",
    )
    list_filter = ("status", "region", "category", "company")
    search_fields = ("title", "client", "location", "design_no")
    inlines = [BidCostInline, BidCompetitorInline]


@admin.register(BidCost)
class BidCostAdmin(SimpleHistoryAdmin):
    list_display = ("project", "estimate_amount", "actual_cost", "company")
    list_filter = ("company",)


@admin.register(BidCompetitor)
class BidCompetitorAdmin(SimpleHistoryAdmin):
    list_display = ("competitor_name", "project", "competitor_amount", "company")
    list_filter = ("company",)


@admin.register(ScrapeTarget)
class ScrapeTargetAdmin(SimpleHistoryAdmin):
    list_display = (
        "name", "region", "category_filter",
        "is_active", "last_scraped_at", "company",
    )
    list_filter = ("is_active", "region", "company")


@admin.register(UnitPrice)
class UnitPriceAdmin(SimpleHistoryAdmin):
    list_display = ("category", "item_name", "unit", "unit_price", "company")
    list_filter = ("category", "company")
    search_fields = ("item_name",)


@admin.register(Qualification)
class QualificationAdmin(SimpleHistoryAdmin):
    list_display = (
        "issuer", "category", "grade", "valid_from", "valid_until", "renewed", "company",
    )
    list_filter = ("renewed", "company")
    search_fields = ("issuer",)


@admin.register(UnifiedQualification)
class UnifiedQualificationAdmin(SimpleHistoryAdmin):
    list_display = (
        "sort_order", "agency",
        "goods_sales_grade", "goods_sales_score",
        "services_grade", "services_score",
        "purchase_grade", "purchase_score",
        "company",
    )
    list_filter = ("company",)
    search_fields = ("agency",)
