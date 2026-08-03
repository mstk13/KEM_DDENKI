from django.contrib import admin

from apps.notifications.models import AlertLog, AlertRule, Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["title", "recipient", "level", "module", "is_read", "sent_at"]
    list_filter = ["level", "module", "is_read", "channel"]
    search_fields = ["title", "body"]
    readonly_fields = ["sent_at", "read_at"]


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ["name", "alert_type", "threshold_value", "notification_level", "is_active"]
    list_filter = ["alert_type", "is_active"]


@admin.register(AlertLog)
class AlertLogAdmin(admin.ModelAdmin):
    list_display = ["alert_rule", "reference_type", "reference_id", "triggered_at"]
    list_filter = ["alert_rule__alert_type"]
    readonly_fields = ["triggered_at"]
