from django.urls import path

from apps.tenants import views

app_name = "tenants"

urlpatterns = [
    # 自社情報（ADR-0071）
    path("", views.company_document_list, name="company_document_list"),
    path("new/", views.company_document_create, name="company_document_create"),
    path("<int:pk>/", views.company_document_detail, name="company_document_detail"),
    path("<int:pk>/analyze/", views.company_document_analyze, name="company_document_analyze"),
    path("<int:pk>/confirm/", views.company_document_confirm, name="company_document_confirm"),
    path("<int:pk>/file/", views.company_document_file, name="company_document_file"),
    path("<int:pk>/delete/", views.company_document_delete, name="company_document_delete"),
]
