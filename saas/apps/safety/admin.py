from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.safety.models import EntryConfirmation, KyParticipant, KySheet


class KyParticipantInline(admin.TabularInline):
    model = KyParticipant
    extra = 0
    fields = ("worker", "health", "health_note", "tester", "signed_at")
    readonly_fields = ("signed_at",)


@admin.register(KySheet)
class KySheetAdmin(SimpleHistoryAdmin):
    list_display = ("work_date", "site", "crew_name", "leader_name", "company")
    list_filter = ("company",)
    search_fields = ("site__name", "crew_name", "leader_name")
    raw_id_fields = ("site",)
    inlines = [KyParticipantInline]


@admin.register(KyParticipant)
class KyParticipantAdmin(SimpleHistoryAdmin):
    list_display = ("sheet", "worker", "health", "tester", "signed_at", "company")
    list_filter = ("health", "tester", "company")
    raw_id_fields = ("sheet", "worker")


@admin.register(EntryConfirmation)
class EntryConfirmationAdmin(SimpleHistoryAdmin):
    list_display = ("entry_date", "site", "worker", "company")
    list_filter = ("company",)
    search_fields = ("site__name", "worker__name")
    raw_id_fields = ("site", "worker")
