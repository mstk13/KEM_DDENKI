from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.sales.models import SalesVisit


@admin.register(SalesVisit)
class SalesVisitAdmin(SimpleHistoryAdmin):
    list_display = ("company_name", "industry", "rep_name", "status", "visit_date", "company")
    list_filter = ("industry", "status", "company")
    search_fields = ("company_name", "rep_name", "business_overview")
