from django.urls import path

from apps.workers import views

app_name = "workers"

urlpatterns = [
    path("", views.worker_list, name="list"),
    path("new/", views.worker_create, name="create"),
    path("<int:pk>/", views.worker_detail, name="detail"),
    path("<int:pk>/edit/", views.worker_edit, name="edit"),
]
