from django.urls import path

from apps.sales import views

app_name = "sales"

urlpatterns = [
    path("", views.visit_list, name="visit_list"),
    path("new/", views.visit_create, name="visit_create"),
    path("<int:pk>/", views.visit_detail, name="visit_detail"),
    path("<int:pk>/edit/", views.visit_edit, name="visit_edit"),
    path("<int:pk>/delete/", views.visit_delete, name="visit_delete"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("industry/", views.industry_browse, name="industry_browse"),
]
