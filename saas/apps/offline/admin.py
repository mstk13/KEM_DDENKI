from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.offline.models import OfflineSubmission


@admin.register(OfflineSubmission)
class OfflineSubmissionAdmin(SimpleHistoryAdmin):
    list_display = ("created_at", "user", "path", "location", "company")
    list_filter = ("company",)
    search_fields = ("path", "client_request_id")
    readonly_fields = ("client_request_id", "path", "location")
