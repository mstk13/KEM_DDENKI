from django.urls import path

from apps.costs import views

app_name = "costs"

urlpatterns = [
    path("", views.cost_list, name="list"),
    path("<int:site_id>/", views.cost_detail, name="detail"),
    path("<int:site_id>/chart-data/", views.cost_chart_data, name="chart_data"),
    path("<int:site_id>/budget/new/", views.budget_create, name="budget_create"),
    path("manual/new/", views.manual_cost_create, name="manual_cost_create"),
]
