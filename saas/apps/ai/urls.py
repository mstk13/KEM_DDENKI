from django.urls import path

from apps.ai import views

app_name = "ai"

urlpatterns = [
    path("logs/", views.ai_log_list, name="log_list"),
    path("logs/<int:pk>/feedback/", views.ai_feedback_create, name="feedback_create"),
    path("dashboard/", views.ai_dashboard, name="dashboard"),
    path("sites/", views.ai_site_select, name="site_select"),
    path("predict/<int:site_id>/", views.cost_prediction, name="cost_prediction"),
    path("optimize/<int:site_id>/", views.cost_optimization, name="cost_optimization"),
    path("schedule-suggest/<int:site_id>/", views.schedule_suggestion, name="schedule_suggestion"),
    path("schedule-risk/<int:site_id>/", views.schedule_risk, name="schedule_risk"),
    path("batch/", views.batch_list, name="batch_list"),
]
