from django.urls import path

from apps.ai import views

app_name = "ai"

urlpatterns = [
    path("logs/", views.ai_log_list, name="log_list"),
    path("logs/<int:pk>/feedback/", views.ai_feedback_create, name="feedback_create"),
    path("dashboard/", views.ai_dashboard, name="dashboard"),
]
