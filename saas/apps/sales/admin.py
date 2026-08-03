from django.contrib import admin

from apps.sales.models import SalesAttachment, SalesVisit


class SalesAttachmentInline(admin.TabularInline):
    model = SalesAttachment
    extra = 0


@admin.register(SalesVisit)
class SalesVisitAdmin(admin.ModelAdmin):
    list_display = ["company_name", "rep_name", "industry", "status", "visit_date"]
    list_filter = ["industry", "status"]
    search_fields = ["company_name", "rep_name", "sales_content"]
    inlines = [SalesAttachmentInline]
