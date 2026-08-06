from django.urls import path

from apps.evaluation import views

app_name = "evaluation"

urlpatterns = [
    path("", views.eval_list, name="eval_list"),
    path("new/", views.eval_create, name="eval_create"),
    path("<int:pk>/", views.eval_detail, name="eval_detail"),
    path("<int:pk>/input/", views.eval_input, name="eval_input"),
    path("criteria/", views.criteria_list, name="criteria_list"),
    path("criteria/new/", views.criteria_create, name="criteria_create"),
    path("criteria/<int:pk>/edit/", views.criteria_edit, name="criteria_edit"),
    path("assignments/", views.assignment_list, name="assignment_list"),
    path("assignments/<int:pk>/delete/", views.assignment_delete, name="assignment_delete"),
    path("employee/<int:pk>/summary/", views.employee_summary, name="employee_summary"),
]
