from django.urls import path

from apps.permissions import views

app_name = "permissions"

urlpatterns = [
    path("", views.permission_matrix, name="matrix"),
    path("users/", views.user_role_list, name="user_roles"),
    path("users/<int:user_id>/update/", views.user_role_update, name="user_role_update"),
]
