from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.attendance.models import AttendPlan, AttendSettings


@admin.register(AttendSettings)
class AttendSettingsAdmin(SimpleHistoryAdmin):
    list_display = ("key", "value", "company")
    list_filter = ("company",)


@admin.register(AttendPlan)
class AttendPlanAdmin(SimpleHistoryAdmin):
    list_display = (
        "plan_date", "worker", "kind", "start_time", "end_time", "note", "company",
    )
    list_filter = ("kind", "company")
    search_fields = ("worker__name", "note")
    date_hierarchy = "plan_date"
