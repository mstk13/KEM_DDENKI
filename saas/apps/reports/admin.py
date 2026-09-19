from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.reports.models import (
    DailyReport,
    DailyReportMaterial,
    WorkTallyEditor,
    WorkTallyEntry,
    WorkTallySettings,
)


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


@admin.register(WorkTallySettings)
class WorkTallySettingsAdmin(SimpleHistoryAdmin):
    list_display = ("company", "regular_start", "regular_end", "night_start")


@admin.register(WorkTallyEntry)
class WorkTallyEntryAdmin(SimpleHistoryAdmin):
    list_display = ("work_date", "worker", "start_time", "end_time", "vehicle", "excluded")
    list_filter = ("excluded", "company")
    search_fields = ("worker__name", "site_names", "work_description")


@admin.register(WorkTallyEditor)
class WorkTallyEditorAdmin(SimpleHistoryAdmin):
    list_display = ("worker", "granted_by", "created_at", "company")
