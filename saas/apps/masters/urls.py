from django.urls import path

from apps.masters import views

app_name = "masters"

urlpatterns = [
    path("", views.worktype_list, name="worktypes"),
]
