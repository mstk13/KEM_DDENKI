from django.urls import path

from apps.estimation import views

app_name = "estimation"

urlpatterns = [
    # 品目マスタ
    path("items/", views.item_list, name="item_list"),
    path("items/new/", views.item_create, name="item_create"),
    path("items/<int:pk>/", views.item_detail, name="item_detail"),
    path("items/<int:pk>/edit/", views.item_edit, name="item_edit"),
    # 名寄せレビュー
    path("aliases/", views.alias_list, name="alias_list"),
    path("aliases/<int:pk>/review/", views.alias_review, name="alias_review"),
    path("aliases/bulk-approve/", views.alias_bulk_approve, name="alias_bulk_approve"),
    # 発注機関
    path("orderers/", views.orderer_list, name="orderer_list"),
    path("orderers/new/", views.orderer_create, name="orderer_create"),
    path("orderers/<int:pk>/", views.orderer_detail, name="orderer_detail"),
    path("orderers/<int:pk>/edit/", views.orderer_edit, name="orderer_edit"),
    # データソース管理（官公庁ごとのデータ差異）
    path("datasources/", views.datasource_matrix, name="datasource_matrix"),
    path("orderers/<int:orderer_pk>/datasources/new/", views.datasource_create, name="datasource_create"),
    path("datasources/<int:pk>/edit/", views.datasource_edit, name="datasource_edit"),
    # M2: 労務単価
    path("labor-rates/", views.labor_rate_list, name="labor_rate_list"),
    path("labor-rates/import/", views.labor_rate_import, name="labor_rate_import"),
    # M2: 積算基準
    path("standards/", views.standard_list, name="standard_list"),
    path("standards/new/", views.standard_create, name="standard_create"),
    path("standards/<int:pk>/", views.standard_detail, name="standard_detail"),
    path("standards/<int:pk>/edit/", views.standard_edit, name="standard_edit"),
    # M2: 歩掛
    path("standards/<int:standard_pk>/workrates/new/", views.workrate_create, name="workrate_create"),
    path("workrates/<int:pk>/edit/", views.workrate_edit, name="workrate_edit"),
    # M3: 積算案件・内訳書
    path("projects/", views.project_list, name="project_list"),
    path("projects/new/", views.project_create, name="project_create"),
    path("projects/<int:pk>/", views.project_detail, name="project_detail"),
    path("projects/<int:pk>/edit/", views.project_edit, name="project_edit"),
    path("projects/<int:pk>/boq-export/", views.boq_export, name="boq_export"),
    path("projects/<int:project_pk>/boqlines/new/", views.boqline_create, name="boqline_create"),
    path("boqlines/<int:pk>/edit/", views.boqline_edit, name="boqline_edit"),
    # M4: 差分分析・仕入実績
    path("projects/<int:pk>/compare/", views.generate_comparison, name="generate_comparison"),
    path("purchases/", views.purchase_list, name="purchase_list"),
    path("purchases/new/", views.purchase_create, name="purchase_create"),
    path("purchases/csv-import/", views.purchase_csv_import, name="purchase_csv_import"),
]
