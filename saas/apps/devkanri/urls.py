from django.urls import path

from apps.devkanri import views

app_name = "devkanri"

urlpatterns = [
    # Projects
    path("", views.project_list, name="project_list"),
    path("new/", views.project_create, name="project_create"),
    path("<int:pk>/", views.project_detail, name="project_detail"),
    path("<int:pk>/edit/", views.project_edit, name="project_edit"),
    path("<int:pk>/delete/", views.project_delete, name="project_delete"),
    # Tasks
    path("<int:project_pk>/tasks/new/", views.task_create, name="task_create"),
    path("tasks/<int:pk>/", views.task_detail, name="task_detail"),
    path("tasks/<int:pk>/edit/", views.task_edit, name="task_edit"),
    path("tasks/<int:pk>/delete/", views.task_delete, name="task_delete"),
    path("tasks/<int:pk>/move/", views.task_move, name="task_move"),
]
