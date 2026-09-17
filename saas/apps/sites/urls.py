from django.urls import path

from apps.sites import document_views, views

app_name = "sites"

urlpatterns = [
    path("", views.site_list, name="list"),
    path("new/", views.site_create, name="create"),
    # 現場名の重複に入力の途中で気づくための候補（ADR-0077）
    path("name-suggestions/", views.site_name_suggestions, name="name_suggestions"),
    path("import/", views.site_import, name="import"),
    # 現場の名寄せ（ADR-0084）。候補を出すところまでが機械の仕事
    path("merge/", views.site_merge_list, name="merge_list"),
    path("merge/scan/", views.site_merge_scan, name="merge_scan"),
    # ADR-0090: 機械が拾えなかった組を、人が選んでまとめる
    path("merge/manual/", views.site_merge_manual, name="merge_manual"),
    path("merge/<int:pk>/apply/", views.site_merge_apply, name="merge_apply"),
    path("merge/<int:pk>/ignore/", views.site_merge_ignore, name="merge_ignore"),
    path("merge/<int:pk>/undo/", views.site_merge_undo, name="merge_undo"),
    path("<int:pk>/", views.site_detail, name="detail"),
    path("<int:pk>/estimate-import/", views.site_estimate_import, name="estimate_import"),
    # 内訳書・内訳明細書
    path("<int:pk>/boq/edit/", views.site_boq_edit, name="boq_edit"),
    path("<int:pk>/boq/import/", views.site_boq_import, name="boq_import"),
    path("<int:pk>/boq/export/", views.site_boq_export, name="boq_export"),
    # 現場写真（ADR-0051）
    path("photos/new/", views.site_photo_quick_upload, name="photo_quick"),
    path("<int:pk>/photos/", views.site_photo_list, name="photo_list"),
    path("<int:pk>/photos/new/", views.site_photo_upload, name="photo_upload"),
    path("photos/<int:pk>/edit/", views.site_photo_edit, name="photo_edit"),
    path("photos/<int:pk>/delete/", views.site_photo_delete, name="photo_delete"),
    path(
        "photos/<int:pk>/image/", views.site_photo_file, {"variant": "image"},
        name="photo_image",
    ),
    path(
        "photos/<int:pk>/thumb/", views.site_photo_file, {"variant": "thumb"},
        name="photo_thumb",
    ),
    # 提出書類（ADR-0067）
    path("<int:pk>/documents/", document_views.site_document_list, name="document_list"),
    path("<int:pk>/documents/add/", document_views.site_document_add, name="document_add"),
    path("documents/<int:pk>/", document_views.site_document_detail, name="document_detail"),
    path(
        "documents/<int:pk>/delete/", document_views.site_document_delete,
        name="document_delete",
    ),
    path("documents/files/<int:pk>/", document_views.site_document_file, name="document_file"),
    path(
        "documents/files/<int:pk>/delete/", document_views.site_document_file_delete,
        name="document_file_delete",
    ),
    path("<int:pk>/edit/", views.site_edit, name="edit"),
    path("<int:pk>/delete/", views.site_delete, name="delete"),
    # 工程（手入力）
    path("<int:site_pk>/processes/new/", views.process_create, name="process_create"),
    path("processes/<int:pk>/edit/", views.process_edit, name="process_edit"),
    path("processes/<int:pk>/delete/", views.process_delete, name="process_delete"),
]
