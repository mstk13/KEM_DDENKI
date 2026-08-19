from django.urls import path

from apps.costs import views

app_name = "costs"

urlpatterns = [
    path("", views.cost_list, name="list"),
    path("<int:site_id>/", views.cost_detail, name="detail"),
    path("<int:site_id>/chart-data/", views.cost_chart_data, name="chart_data"),
    path("<int:site_id>/budget/new/", views.budget_create, name="budget_create"),
    # 見積書から実行予算を起こす（TOP の受け口が POST してくる）
    path("budget/import/", views.budget_import, name="budget_import"),
    path("manual/new/", views.manual_cost_create, name="manual_cost_create"),
    # アクセス管理
    path("access/", views.cost_access_list, name="access_list"),
    path("access/grant/", views.cost_access_grant, name="access_grant"),
    path("access/<int:pk>/revoke/", views.cost_access_revoke, name="access_revoke"),
]
