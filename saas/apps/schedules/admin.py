from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.schedules.models import Assignment, Milestone, Phase


@admin.register(Phase)
class PhaseAdmin(SimpleHistoryAdmin):
    list_display = ("name", "site", "start_date", "end_date", "progress", "company")
    list_filter = ("company",)
    search_fields = ("name",)


@admin.register(Milestone)
class MilestoneAdmin(SimpleHistoryAdmin):
    list_display = ("name", "site", "target_date", "completed", "company")
    list_filter = ("completed", "company")
    search_fields = ("name",)


@admin.register(Assignment)
class AssignmentAdmin(SimpleHistoryAdmin):
    list_display = ("worker", "site", "start_date", "end_date", "company")
    list_filter = ("company",)
    search_fields = ("worker__name", "site__name")
