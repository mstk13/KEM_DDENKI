from django.urls import path

from apps.bids import views

app_name = "bids"

urlpatterns = [
    path("", views.project_list, name="project_list"),
    path("new/", views.project_create, name="project_create"),
    path("<int:pk>/", views.project_detail, name="project_detail"),
    path("<int:pk>/edit/", views.project_edit, name="project_edit"),
    path("qualifications/", views.qualification_list, name="qualification_list"),
    path("qualifications/new/", views.qualification_create, name="qualification_create"),
    path("qualifications/import/", views.qualification_import, name="qualification_import"),
    path("qualifications/<int:pk>/edit/", views.qualification_edit, name="qualification_edit"),
    path("unit-prices/", views.unit_price_list, name="unit_price_list"),
    path("unit-prices/new/", views.unit_price_create, name="unit_price_create"),
    path("unit-prices/<int:pk>/edit/", views.unit_price_edit, name="unit_price_edit"),
    path("dashboard/", views.bid_dashboard, name="dashboard"),
    path("<int:pk>/mark-won/", views.bid_mark_won, name="mark_won"),
    path("<int:pk>/start-estimation/", views.bid_start_estimation, name="start_estimation"),
    # スクレイピングターゲット管理
    path("scrape-targets/", views.scrape_target_list, name="scrape_target_list"),
    path("scrape-targets/new/", views.scrape_target_create, name="scrape_target_create"),
    path("scrape-targets/<int:pk>/edit/", views.scrape_target_edit, name="scrape_target_edit"),
    path("scrape-targets/<int:pk>/run/", views.scrape_run, name="scrape_run"),
    path("scrape-targets/run-all/", views.scrape_run_all, name="scrape_run_all"),
]
