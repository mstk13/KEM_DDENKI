from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.permissions.models import AppAccess, ModulePermission, Role, UserRole


class ModulePermissionInline(admin.TabularInline):
    model = ModulePermission
    extra = 0


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "company", "is_system"]
    list_filter = ["is_system"]
    inlines = [ModulePermissionInline]


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ["user", "role", "granted_by", "created_at"]
    list_filter = ["role"]


@admin.register(AppAccess)
class AppAccessAdmin(SimpleHistoryAdmin):
    list_display = ("worker", "app_key", "can_approve", "company")
    list_filter = ("app_key", "can_approve")
    search_fields = ("worker__name",)
    autocomplete_fields = ("worker",)
