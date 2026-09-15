from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.sites.models import (
    DocumentTemplate,
    EstimateImport,
    Process,
    Site,
    SiteDocument,
    SiteDocumentFile,
    SitePhoto,
)


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


# 提出書類（ADR-0065）。最初のリストの名前・並び順・入れる／外すは、ここで変える
@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(SimpleHistoryAdmin):
    list_display = ("name", "phase", "display_order", "is_active", "company")
    list_editable = ("display_order", "is_active")
    list_filter = ("phase", "is_active", "company")
    search_fields = ("name",)


class SiteDocumentFileInline(admin.TabularInline):
    model = SiteDocumentFile
    extra = 0
    fields = ("original_filename", "kind", "size", "note", "created_at")
    readonly_fields = ("original_filename", "kind", "size", "created_at")


@admin.register(SiteDocument)
class SiteDocumentAdmin(SimpleHistoryAdmin):
    list_display = ("name", "site", "phase", "status", "submitted_on", "is_custom", "company")
    list_filter = ("phase", "status", "is_custom", "company")
    search_fields = ("name", "site__name", "note")
    raw_id_fields = ("site", "template")
    inlines = [SiteDocumentFileInline]


@admin.register(SiteDocumentFile)
class SiteDocumentFileAdmin(SimpleHistoryAdmin):
    list_display = ("original_filename", "document", "kind", "size", "created_by", "created_at")
    list_filter = ("kind", "company")
    search_fields = ("original_filename", "document__name", "document__site__name")
    raw_id_fields = ("document",)
