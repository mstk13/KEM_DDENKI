from django.urls import path

from apps.sales import views

app_name = "sales"

urlpatterns = [
    path("", views.sales_dashboard, name="dashboard"),
    path("list/", views.sales_list, name="list"),
    path("by-industry/", views.sales_by_industry, name="by_industry"),
    path("new/", views.sales_create, name="create"),
    path("<int:pk>/", views.sales_detail, name="detail"),
    path("<int:pk>/edit/", views.sales_edit, name="edit"),
]
