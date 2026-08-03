from django.urls import path

from apps.materials import views

app_name = "materials"

urlpatterns = [
    # 材料マスタ
    path("", views.material_list, name="list"),
    path("new/", views.material_create, name="create_material"),
    path("<int:pk>/edit/", views.material_edit, name="edit_material"),
    # 発注
    path("po/", views.po_list, name="po_list"),
    path("po/new/", views.po_create, name="create_po"),
    path("po/<int:pk>/", views.po_detail, name="po_detail"),
    # 見積
    path("quotations/", views.quotation_list, name="quotation_list"),
    path("quotations/new/", views.quotation_create, name="quotation_create"),
    path("quotations/compare/", views.quotation_compare, name="quotation_compare"),
    # 納品・検収
    path("po/<int:po_pk>/delivery/new/", views.delivery_create, name="delivery_create"),
    path("delivery/<int:pk>/inspect/", views.delivery_inspect, name="delivery_inspect"),
    # 在庫
    path("inventory/", views.inventory_list, name="inventory_list"),
]
