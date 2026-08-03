from django.urls import path

from apps.masters import views

app_name = "masters"

urlpatterns = [
    path("", views.worktype_list, name="worktypes"),
    path("customers/", views.customer_list, name="customer_list"),
    path("customers/new/", views.customer_create, name="customer_create"),
    path("customers/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("customers/<int:pk>/edit/", views.customer_edit, name="customer_edit"),
    path("suppliers/", views.supplier_list, name="supplier_list"),
    path("suppliers/new/", views.supplier_create, name="supplier_create"),
    path("suppliers/<int:pk>/", views.supplier_detail, name="supplier_detail"),
    path("suppliers/<int:pk>/edit/", views.supplier_edit, name="supplier_edit"),
    path("suppliers/<int:supplier_pk>/evaluate/", views.supplier_eval_create, name="supplier_eval_create"),
    path("cards/new/", views.business_card_create, name="card_create"),
]
