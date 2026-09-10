from django.urls import path

from apps.materials import views

app_name = "materials"

urlpatterns = [
    # 材料マスタ
    path("", views.material_list, name="list"),
    path("new/", views.material_create, name="create_material"),
    path("<int:pk>/edit/", views.material_edit, name="edit_material"),
    # 見積
    path("quotations/", views.quotation_list, name="quotation_list"),
    path("quotations/new/", views.quotation_create, name="quotation_create"),
    path("quotations/<int:pk>/", views.quotation_detail, name="quotation_detail"),
    path(
        "quotations/<int:quotation_pk>/item/add/",
        views.quotation_item_add,
        name="quotation_item_add",
    ),
    path("quotations/item/<int:pk>/edit/", views.quotation_item_edit, name="quotation_item_edit"),
    path(
        "quotations/item/<int:pk>/delete/",
        views.quotation_item_delete,
        name="quotation_item_delete",
    ),
    path("quotations/<int:pk>/pdf/", views.quotation_pdf, name="quotation_pdf"),
    path("quotations/compare/", views.quotation_compare, name="quotation_compare"),
    # 発注
    path("po/", views.po_list, name="po_list"),
    path("po/new/", views.po_create, name="create_po"),
    path("po/<int:pk>/", views.po_detail, name="po_detail"),
    path("po/<int:po_pk>/item/add/", views.po_item_add, name="po_item_add"),
    path("po/item/<int:pk>/delete/", views.po_item_delete, name="po_item_delete"),
    # 材料別の取引履歴
    path("history/", views.purchase_history, name="purchase_history"),
    # 発注書 Excel 出力
    path("po/<int:pk>/excel/order/", views.po_excel_download, name="po_excel_order"),
    path(
        "po/<int:pk>/excel/acceptance/",
        views.po_acceptance_excel_download, name="po_excel_acceptance",
    ),
    # 発注書 PDF 出力
    path("po/<int:pk>/pdf/order/", views.po_pdf_download, name="po_pdf_order"),
    path(
        "po/<int:pk>/pdf/acceptance/",
        views.po_acceptance_pdf_download, name="po_pdf_acceptance",
    ),
    # CSV インポート
    path("po/csv-import/", views.po_csv_import, name="csv_import"),
    path("po/csv-import/<int:site_id>/", views.po_csv_import, name="csv_import_site"),
    # 納品・受領・検収
    path("po/<int:po_pk>/delivery/new/", views.delivery_create, name="delivery_create"),
    path("delivery/<int:pk>/", views.delivery_detail, name="delivery_detail"),
    path("delivery/item/<int:pk>/edit/", views.delivery_item_edit, name="delivery_item_edit"),
    path("delivery/<int:pk>/receive/", views.delivery_receive, name="delivery_receive"),
    path("delivery/<int:pk>/inspect/", views.delivery_inspect, name="delivery_inspect"),
    # 材料仕入先
    path(
        "<int:material_pk>/suppliers/",
        views.material_supplier_list, name="material_supplier_list",
    ),
    path(
        "<int:material_pk>/suppliers/add/",
        views.material_supplier_add, name="material_supplier_add",
    ),
    path("suppliers/<int:pk>/edit/", views.material_supplier_edit, name="material_supplier_edit"),
]
