from django.urls import path

from apps.sites import views

app_name = "sites"

urlpatterns = [
    path("", views.site_list, name="list"),
    path("new/", views.site_create, name="create"),
    path("import/", views.site_import, name="import"),
    path("<int:pk>/", views.site_detail, name="detail"),
    path("<int:pk>/estimate-import/", views.site_estimate_import, name="estimate_import"),
    # 内訳書・内訳明細書
    path("<int:pk>/boq/edit/", views.site_boq_edit, name="boq_edit"),
    path("<int:pk>/boq/import/", views.site_boq_import, name="boq_import"),
    path("<int:pk>/boq/export/", views.site_boq_export, name="boq_export"),
    path("<int:pk>/edit/", views.site_edit, name="edit"),
    path("<int:pk>/delete/", views.site_delete, name="delete"),
    # 工程（手入力）
    path("<int:site_pk>/processes/new/", views.process_create, name="process_create"),
    path("processes/<int:pk>/edit/", views.process_edit, name="process_edit"),
    path("processes/<int:pk>/delete/", views.process_delete, name="process_delete"),
]
