from django.urls import path

from apps.reports import views

app_name = "reports"

urlpatterns = [
    path("", views.report_list, name="list"),
    path("new/", views.report_create, name="create"),
    path("<int:pk>/edit/", views.report_edit, name="edit"),
    path("<int:pk>/approve/", views.report_approve, name="approve"),
]
