from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.devkanri.models import DevComment, DevProject, DevTask, Meyasubako


@admin.register(DevProject)
class DevProjectAdmin(SimpleHistoryAdmin):
    list_display = ("name", "status", "assignee", "start_date", "due_date", "company")
    list_filter = ("status", "company")
    search_fields = ("name",)


@admin.register(DevTask)
class DevTaskAdmin(SimpleHistoryAdmin):
    list_display = ("title", "project", "status", "priority", "category", "assignee", "company")
    list_filter = ("status", "priority", "category", "company")
    search_fields = ("title",)


@admin.register(DevComment)
class DevCommentAdmin(SimpleHistoryAdmin):
    list_display = ("task", "author", "created_at", "company")
    list_filter = ("company",)


@admin.register(Meyasubako)
class MeyasubakoAdmin(SimpleHistoryAdmin):
    list_display = ("title", "kind", "module", "reporter_name", "urgency", "resolved", "created_at", "company")
    list_filter = ("kind", "module", "urgency", "resolved", "company")
    search_fields = ("title", "reporter_name")
