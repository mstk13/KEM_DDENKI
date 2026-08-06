from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.attendance.models import AttendEntry, AttendReport, AttendSettings


class AttendEntryInline(admin.TabularInline):
    model = AttendEntry
    extra = 0


@admin.register(AttendReport)
class AttendReportAdmin(SimpleHistoryAdmin):
    list_display = ("report_date", "site_name", "status", "company", "created_at")
    list_filter = ("status", "company")
    search_fields = ("site_name",)
    inlines = [AttendEntryInline]


@admin.register(AttendEntry)
class AttendEntryAdmin(SimpleHistoryAdmin):
    list_display = (
        "employee_name", "report", "start_time", "end_time",
        "normal_minutes", "overtime_minutes", "company",
    )
    list_filter = ("company",)
    search_fields = ("employee_name",)


@admin.register(AttendSettings)
class AttendSettingsAdmin(SimpleHistoryAdmin):
    list_display = ("key", "value", "company")
    list_filter = ("company",)
