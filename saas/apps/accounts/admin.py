from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import Department, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "company", "employee_no", "department", "is_active")
    list_filter = ("is_active", "is_staff", "groups", "company")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("テナント情報", {"fields": ("company", "employee_no", "department")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("テナント情報", {"fields": ("company", "employee_no", "department")}),
    )


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "is_active")
    list_filter = ("is_active", "company")
