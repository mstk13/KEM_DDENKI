from django.urls import path

from apps.permissions import views

app_name = "permissions"

urlpatterns = [
    path("", views.permission_matrix, name="matrix"),
    # ADR-0082: 作業員 × 機能 のチェック表
    path("apps/", views.app_access_matrix, name="app_access"),
    path("users/", views.user_role_list, name="user_roles"),
    path("users/<int:user_id>/update/", views.user_role_update, name="user_role_update"),
]
