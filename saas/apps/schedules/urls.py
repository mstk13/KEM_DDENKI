from django.urls import path

from apps.schedules import views

app_name = "schedules"

urlpatterns = [
    # Site schedule list + Gantt
    path("", views.schedule_list, name="list"),
    path("compare/", views.schedule_compare, name="compare"),
    path("<int:pk>/", views.schedule_detail, name="detail"),
    # Calendar
    path("calendar/", views.calendar_view, name="calendar"),
    path("calendar/events/", views.calendar_events, name="calendar_events"),
    # Template
    path("<int:site_pk>/apply-template/", views.apply_template_view, name="apply_template"),
    # Phases
    path("<int:site_pk>/phases/new/", views.phase_create, name="phase_create"),
    path("phases/<int:pk>/edit/", views.phase_edit, name="phase_edit"),
    path("phases/<int:pk>/delete/", views.phase_delete, name="phase_delete"),
    # Milestones
    path("<int:site_pk>/milestones/new/", views.milestone_create, name="milestone_create"),
    path("milestones/<int:pk>/edit/", views.milestone_edit, name="milestone_edit"),
    path("milestones/<int:pk>/delete/", views.milestone_delete, name="milestone_delete"),
    # Assignments
    path("<int:site_pk>/assignments/new/", views.assignment_create, name="assignment_create"),
    path("assignments/<int:pk>/delete/", views.assignment_delete, name="assignment_delete"),
]
