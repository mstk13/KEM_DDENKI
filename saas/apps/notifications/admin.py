from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.notifications.models import AlertLog, AlertRule, Notification, PushSubscription


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["title", "recipient", "level", "module", "is_read", "sent_at"]
    list_filter = ["level", "module", "is_read", "channel"]
    search_fields = ["title", "body"]
    readonly_fields = ["sent_at", "read_at", "pushed_at"]


@admin.register(PushSubscription)
class PushSubscriptionAdmin(SimpleHistoryAdmin):
    list_display = [
        "user",
        "company",
        "user_agent",
        "created_at",
        "last_success_at",
        "failure_count",
    ]
    list_filter = ["company"]
    search_fields = ["user__username", "user_agent"]
    readonly_fields = ["endpoint", "p256dh", "auth", "last_success_at", "failure_count"]


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ["name", "alert_type", "threshold_value", "notification_level", "is_active"]
    list_filter = ["alert_type", "is_active"]


@admin.register(AlertLog)
class AlertLogAdmin(admin.ModelAdmin):
    list_display = ["alert_rule", "reference_type", "reference_id", "triggered_at"]
    list_filter = ["alert_rule__alert_type"]
    readonly_fields = ["triggered_at"]
