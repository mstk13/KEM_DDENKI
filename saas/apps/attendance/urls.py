from django.urls import path

from apps.attendance import views

app_name = "attendance"

urlpatterns = [
    path("", views.report_list, name="report_list"),
    path("new/", views.report_create, name="report_create"),
    path("<int:pk>/", views.report_detail, name="report_detail"),
    path("<int:pk>/edit/", views.report_edit, name="report_edit"),
    path("<int:pk>/delete/", views.report_delete, name="report_delete"),
    path("entries/", views.entry_list, name="entry_list"),
    path("employee/<int:pk>/", views.employee_record, name="employee_record"),
    path("summary/", views.summary, name="summary"),
    # 出社予定（実績の日報とは別画面）
    path("plans/", views.plan_board, name="plan_board"),
    path("plans/day/", views.plan_day, name="plan_day"),
    path("plans/set/", views.plan_set, name="plan_set"),
    path("plans/fill/", views.plan_fill, name="plan_fill"),
    path("plans/clear-day/", views.plan_clear_day, name="plan_clear_day"),
    path("settings/", views.settings_view, name="settings"),
]
