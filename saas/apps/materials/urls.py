from django.urls import path

from apps.materials import views

app_name = "materials"

urlpatterns = [
    path("", views.material_list, name="list"),
    path("new/", views.material_create, name="create_material"),
    path("po/new/", views.po_create, name="create_po"),
]
