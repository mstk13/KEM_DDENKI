from django.contrib import admin

from apps.ai.models import AIFeedback, AILog


class AIFeedbackInline(admin.StackedInline):
    model = AIFeedback
    extra = 0
    readonly_fields = ("rating", "is_adopted", "comment", "rated_by")


@admin.register(AILog)
class AILogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "task_type",
        "model_used",
        "site",
        "status",
        "latency_ms",
        "cost_usd",
        "company",
    )
    list_filter = ("task_type", "model_used", "status", "company")
    search_fields = ("site__name",)
    readonly_fields = (
        "task_type",
        "model_used",
        "model_version",
        "site",
        "input_data",
        "prompt",
        "response",
        "response_parsed",
        "status",
        "error_message",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "requested_by",
        "company",
    )
    inlines = [AIFeedbackInline]

    def has_change_permission(self, request, obj=None):
        return False  # AILog は不変（追記のみ）

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AIFeedback)
class AIFeedbackAdmin(admin.ModelAdmin):
    list_display = ("ai_log", "rating", "is_adopted", "rated_by", "created_at")
    list_filter = ("rating", "is_adopted")
    readonly_fields = ("ai_log", "rating", "is_adopted", "comment", "rated_by")
