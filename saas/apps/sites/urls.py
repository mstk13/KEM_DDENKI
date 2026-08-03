from django.urls import path

from apps.sites import views

app_name = "sites"

urlpatterns = [
    path("", views.site_list, name="list"),
    path("new/", views.site_create, name="create"),
    path("<int:pk>/", views.site_detail, name="detail"),
    path("<int:pk>/edit/", views.site_edit, name="edit"),
    path("<int:pk>/delete/", views.site_delete, name="delete"),
]
