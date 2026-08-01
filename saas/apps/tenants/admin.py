from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.tenants.models import Company, CompanyApp


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
