from django.urls import path

from apps.workers import views

app_name = "workers"

urlpatterns = [
    path("", views.worker_list, name="list"),
    path("document-alerts/", views.document_alert_dashboard, name="document_alerts"),
    path("excel/", views.worker_excel, name="excel"),
    path("new/", views.worker_create, name="create"),
    path("<int:pk>/", views.worker_detail, name="detail"),
    path("<int:pk>/edit/", views.worker_edit, name="edit"),
    path("evaluations/", views.evaluation_list, name="evaluations"),
    path("evaluations/new/", views.evaluation_create, name="eval_create"),
    path("evaluations/<int:pk>/", views.evaluation_detail, name="eval_detail"),
    path("evaluations/template/", views.eval_template_edit, name="eval_template_edit"),
    path("evaluations/template/pdf/", views.eval_template_pdf, name="eval_template_pdf"),
    path("evaluations/comparison-pdf/", views.eval_comparison_pdf, name="eval_comparison_pdf"),
    path("evaluations/survey-pdf/", views.eval_survey_pdf, name="eval_survey_pdf"),
    path("evaluations/role-sheet-pdf/", views.eval_role_sheet_pdf, name="eval_role_sheet_pdf"),
    path("evaluations/<int:pk>/edit/", views.evaluation_edit, name="eval_edit"),
    path("evaluations/targets-api/", views.eval_targets_api, name="eval_targets_api"),
    # Qualifications
    path("<int:worker_pk>/qualifications/new/", views.qualification_create, name="qual_create"),
    path("qualifications/<int:pk>/edit/", views.qualification_edit, name="qual_edit"),
    path("qualifications/<int:pk>/delete/", views.qualification_delete, name="qual_delete"),
    # Health checkups
    path("<int:worker_pk>/health/new/", views.health_checkup_create, name="health_create"),
    path("health/<int:pk>/edit/", views.health_checkup_edit, name="health_edit"),
    path("health/<int:pk>/delete/", views.health_checkup_delete, name="health_delete"),
]
