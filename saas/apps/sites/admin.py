from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.sites.models import EstimateImport, Process, Site, SitePhoto


class ProcessInline(admin.TabularInline):
    model = Process
    extra = 0


@admin.register(Site)
class SiteAdmin(SimpleHistoryAdmin):
    list_display = (
        "code", "name", "customer", "status", "contract_amount",
        "manager", "estimator", "company",
    )
    list_filter = ("status", "company")
    search_fields = ("code", "name")
    inlines = [ProcessInline]


@admin.register(EstimateImport)
class EstimateImportAdmin(SimpleHistoryAdmin):
    list_display = (
        "created_at", "filename", "customer", "customer_name_raw",
        "estimate_number", "amount", "site", "company",
    )
    list_filter = ("company",)
    search_fields = ("filename", "customer_name_raw", "estimate_number")


@admin.register(Process)
class ProcessAdmin(SimpleHistoryAdmin):
    list_display = ("name", "site", "work_type", "status", "planned_start", "planned_end")
    list_filter = ("status", "company")


@admin.register(SitePhoto)
class SitePhotoAdmin(SimpleHistoryAdmin):
    list_display = ("taken_on", "site", "kind", "location", "created_by", "company")
    list_filter = ("kind", "company")
    search_fields = ("location", "note", "site__name", "original_filename")
    raw_id_fields = ("site",)
