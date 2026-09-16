from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.tenants.models import (
    Company,
    CompanyApp,
    CompanyDocument,
    CompanyDocumentType,
)


class CompanyAppInline(admin.TabularInline):
    model = CompanyApp
    extra = 0


@admin.register(Company)
class CompanyAdmin(SimpleHistoryAdmin):
    list_display = ("name", "industry_type", "contract_plan", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    inlines = [CompanyAppInline]


@admin.register(CompanyApp)
class CompanyAppAdmin(SimpleHistoryAdmin):
    list_display = ("company", "app_code", "is_enabled", "enabled_at")
    list_filter = ("app_code", "is_enabled")


# 自社書類（ADR-0071）。書類の種類の名前・並び順・使う／使わないはここで変える


@admin.register(CompanyDocumentType)
class CompanyDocumentTypeAdmin(SimpleHistoryAdmin):
    list_display = ("name", "has_renewal", "display_order", "is_active", "company")
    list_editable = ("display_order", "is_active")
    list_filter = ("has_renewal", "is_active", "company")
    search_fields = ("name",)


@admin.register(CompanyDocument)
class CompanyDocumentAdmin(SimpleHistoryAdmin):
    list_display = (
        "name", "original_filename", "issued_on", "renewal_on",
        "confirmed", "ai_checked_at", "company",
    )
    list_filter = ("kind", "confirmed", "company")
    search_fields = ("name", "original_filename", "memo", "ai_summary")
    raw_id_fields = ("doc_type",)
    readonly_fields = (
        "kind", "original_filename", "size", "ai_summary", "ai_fields",
        "ai_checked_at", "confirmed_at", "reminder_step",
    )
