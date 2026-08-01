from django.urls import path

from apps.workers import views

app_name = "workers"

urlpatterns = [
    path("", views.worker_list, name="list"),
    path("new/", views.worker_create, name="create"),
    path("<int:pk>/", views.worker_detail, name="detail"),
    path("<int:pk>/edit/", views.worker_edit, name="edit"),
    path("evaluations/", views.evaluation_list, name="evaluations"),
    path("evaluations/new/", views.evaluation_create, name="eval_create"),
    path("evaluations/<int:pk>/", views.evaluation_detail, name="eval_detail"),
]
