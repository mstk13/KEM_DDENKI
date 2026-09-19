from django.urls import path

from apps.reports import tally_views, views

app_name = "reports"

urlpatterns = [
    path("", views.report_list, name="list"),
    path("new/", views.report_create, name="create"),
    path("pdf/", views.report_list_pdf, name="list_pdf"),
    path("<int:pk>/", views.report_detail, name="detail"),
    path("<int:pk>/pdf/", views.report_pdf, name="pdf"),
    path("<int:pk>/edit/", views.report_edit, name="edit"),
    path("<int:pk>/delete/", views.report_delete, name="delete"),
    path("<int:pk>/approve/", views.report_approve, name="approve"),
    path("approve/bulk/", views.report_approve_bulk, name="approve_bulk"),
    path("safety/", views.safety_check, name="safety_check"),
    path("safety/<int:pk>/complete/", views.safety_complete, name="safety_complete"),
    path("monthly/", views.monthly_summary, name="monthly_summary"),
    # 作業日報集計（ADR-0104）
    path("monthly/pdf/", tally_views.tally_pdf_all, name="tally_pdf_all"),
    path("monthly/settings/", tally_views.tally_settings, name="tally_settings"),
    path("monthly/editors/", tally_views.tally_editors, name="tally_editors"),
    path(
        "monthly/editors/<int:worker_pk>/grant/",
        tally_views.tally_editor_grant, name="tally_editor_grant",
    ),
    path(
        "monthly/editors/<int:worker_pk>/revoke/",
        tally_views.tally_editor_revoke, name="tally_editor_revoke",
    ),
    path("monthly/<int:worker_pk>/", tally_views.tally_sheet, name="tally_sheet"),
    path("monthly/<int:worker_pk>/pdf/", tally_views.tally_pdf, name="tally_pdf"),
    path("monthly/<int:worker_pk>/add/", tally_views.tally_add_day, name="tally_add_day"),
    path(
        "monthly/<int:worker_pk>/<int:year>/<int:month>/<int:day>/",
        tally_views.tally_entry_edit, name="tally_entry_edit",
    ),
    path(
        "monthly/<int:worker_pk>/<int:year>/<int:month>/<int:day>/reset/",
        tally_views.tally_entry_reset, name="tally_entry_reset",
    ),
    path(
        "monthly/<int:worker_pk>/<int:year>/<int:month>/<int:day>/exclude/",
        tally_views.tally_entry_exclude, name="tally_entry_exclude",
    ),
]
