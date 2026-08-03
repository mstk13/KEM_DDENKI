"""
権限管理のビジネスロジック。

views.py / middleware / decorators から呼ぶ。
将来の DRF API 移行時にもそのまま使える。
"""

from apps.permissions.models import ModulePermission, Role, UserRole


def get_user_roles(user):
    """ユーザーのロール一覧を取得する。"""
    return Role.unscoped.filter(
        user_roles__user=user,
    ).distinct()


def has_module_permission(user, module: str, level: str = "read") -> bool:
    """ユーザーが指定モジュールの指定レベルの権限を持つかチェック。

    Args:
        user: Userインスタンス
        module: モジュールコード（例: 'costs', 'reports'）
        level: 'read', 'write', 'admin'

    Returns:
        True if permitted
    """
    # superuser は常に全権限
    if user.is_superuser:
        return True

    field_map = {
        "read": "can_read",
        "write": "can_write",
        "admin": "can_admin",
    }
    field = field_map.get(level, "can_read")

    return ModulePermission.unscoped.filter(
        role__user_roles__user=user,
        module=module,
        **{field: True},
    ).exists()


def get_permission_matrix(company):
    """会社のロール × モジュール 権限マトリクスを取得する。

    Returns:
        {
            "roles": [Role, ...],
            "modules": [("code", "label"), ...],
            "matrix": {role_id: {module: {"read": bool, "write": bool, "admin": bool}}},
        }
    """
    roles = list(Role.unscoped.filter(company=company).order_by("code"))
    modules = ModulePermission.MODULE_CHOICES

    matrix = {}
    for role in roles:
        perms = ModulePermission.unscoped.filter(role=role)
        matrix[role.pk] = {}
        for mod_code, _mod_label in modules:
            perm = perms.filter(module=mod_code).first()
            matrix[role.pk][mod_code] = {
                "read": perm.can_read if perm else False,
                "write": perm.can_write if perm else False,
                "admin": perm.can_admin if perm else False,
            }

    return {
        "roles": roles,
        "modules": modules,
        "matrix": matrix,
    }


def setup_default_roles(company, created_by=None):
    """テナントのデフォルトロールと権限を作成する。

    新規会社登録時に呼ぶ。
    """
    defaults = [
        {
            "code": "president",
            "name": "社長",
            "description": "全機能アクセス、権限付与",
            "permissions": {
                mod: {"read": True, "write": True, "admin": True}
                for mod, _ in ModulePermission.MODULE_CHOICES
            },
        },
        {
            "code": "executive",
            "name": "役員",
            "description": "社長が付与した範囲",
            "permissions": {
                "reports": {"read": True, "write": True, "admin": False},
                "costs": {"read": True, "write": False, "admin": False},
                "materials": {"read": True, "write": True, "admin": False},
                "bids": {"read": True, "write": True, "admin": False},
                "schedules": {"read": True, "write": True, "admin": False},
                "workers": {"read": True, "write": True, "admin": False},
                "masters": {"read": True, "write": True, "admin": False},
                "notifications": {"read": True, "write": False, "admin": False},
            },
        },
        {
            "code": "site_manager",
            "name": "現場担当者",
            "description": "日報入力、工期閲覧等",
            "permissions": {
                "reports": {"read": True, "write": True, "admin": False},
                "materials": {"read": True, "write": False, "admin": False},
                "schedules": {"read": True, "write": False, "admin": False},
                "workers": {"read": True, "write": False, "admin": False},
                "masters": {"read": True, "write": False, "admin": False},
                "notifications": {"read": True, "write": False, "admin": False},
            },
        },
        {
            "code": "office_staff",
            "name": "事務員",
            "description": "日報代理入力、材料発注等",
            "permissions": {
                "reports": {"read": True, "write": True, "admin": False},
                "materials": {"read": True, "write": True, "admin": False},
                "bids": {"read": True, "write": False, "admin": False},
                "schedules": {"read": True, "write": False, "admin": False},
                "workers": {"read": True, "write": True, "admin": False},
                "masters": {"read": True, "write": True, "admin": False},
                "notifications": {"read": True, "write": False, "admin": False},
            },
        },
        {
            "code": "partner_worker",
            "name": "協力会社",
            "description": "制限付きアクセス",
            "permissions": {
                "reports": {"read": True, "write": True, "admin": False},
                "schedules": {"read": True, "write": False, "admin": False},
                "notifications": {"read": True, "write": False, "admin": False},
            },
        },
        {
            "code": "developer",
            "name": "開発者",
            "description": "開発管理モジュールのみ",
            "permissions": {
                "devkanri": {"read": True, "write": True, "admin": True},
                "notifications": {"read": True, "write": False, "admin": False},
            },
        },
    ]

    for role_def in defaults:
        role, _ = Role.unscoped.get_or_create(
            company=company,
            code=role_def["code"],
            defaults={
                "name": role_def["name"],
                "description": role_def["description"],
                "is_system": True,
                "created_by": created_by,
            },
        )

        for mod_code, perms in role_def.get("permissions", {}).items():
            ModulePermission.unscoped.update_or_create(
                company=company,
                role=role,
                module=mod_code,
                defaults={
                    "can_read": perms.get("read", False),
                    "can_write": perms.get("write", False),
                    "can_admin": perms.get("admin", False),
                },
            )
