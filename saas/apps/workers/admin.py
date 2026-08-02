from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.workers.models import (
    EvaluationTemplate,
    HealthCheckup,
    JobTitle,
    Position,
    Worker,
    WorkerEvaluation,
    WorkerQualification,
)


@admin.register(JobTitle)
class JobTitleAdmin(SimpleHistoryAdmin):
    list_display = ("name", "company", "is_active")
    list_filter = ("is_active", "company")


@admin.register(Position)
class PositionAdmin(SimpleHistoryAdmin):
    list_display = ("name", "rank", "company", "is_active")
    list_filter = ("is_active", "company")


@admin.register(Worker)
class WorkerAdmin(SimpleHistoryAdmin):
    list_display = (
        "name", "job_title", "position", "hourly_cost", "company", "is_active",
    )
    list_filter = ("is_active", "company", "job_title", "position")
    search_fields = ("name",)


@admin.register(EvaluationTemplate)
class EvaluationTemplateAdmin(SimpleHistoryAdmin):
    list_display = ("name", "company", "is_active")
    list_filter = ("is_active", "company")


@admin.register(WorkerQualification)
class WorkerQualificationAdmin(SimpleHistoryAdmin):
    list_display = ("worker", "name", "category", "acquired_date", "expiry_date", "company")
    list_filter = ("category", "company")
    search_fields = ("name", "worker__name")


@admin.register(HealthCheckup)
class HealthCheckupAdmin(SimpleHistoryAdmin):
    list_display = ("worker", "checkup_date", "result", "institution", "company")
    list_filter = ("result", "company")
    search_fields = ("worker__name",)


@admin.register(WorkerEvaluation)
class WorkerEvaluationAdmin(SimpleHistoryAdmin):
    list_display = ("worker", "evaluated_by", "period", "score", "company")
    list_filter = ("period", "company")
