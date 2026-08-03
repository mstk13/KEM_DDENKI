from django.urls import path

from apps.reports import views

app_name = "reports"

urlpatterns = [
    path("", views.report_list, name="list"),
    path("new/", views.report_create, name="create"),
    path("<int:pk>/edit/", views.report_edit, name="edit"),
    path("<int:pk>/approve/", views.report_approve, name="approve"),
    path("safety/", views.safety_check, name="safety_check"),
    path("safety/<int:pk>/complete/", views.safety_complete, name="safety_complete"),
    path("monthly/", views.monthly_summary, name="monthly_summary"),
]
