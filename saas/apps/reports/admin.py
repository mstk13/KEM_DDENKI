from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.reports.models import DailyReport, DailyReportMaterial


class DailyReportMaterialInline(admin.TabularInline):
    model = DailyReportMaterial
    extra = 0


@admin.register(DailyReport)
class DailyReportAdmin(SimpleHistoryAdmin):
    list_display = (
        "report_date", "report_type", "worker", "site", "work_type",
        "work_hours", "status", "company",
    )
    list_filter = ("status", "report_type", "report_date", "company")
    search_fields = ("worker__name", "site__name")
    inlines = [DailyReportMaterialInline]


@admin.register(DailyReportMaterial)
class DailyReportMaterialAdmin(SimpleHistoryAdmin):
    list_display = ("daily_report", "material", "quantity_used")
