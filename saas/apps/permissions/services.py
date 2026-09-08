"""
権限管理のビジネスロジック。

views.py / middleware / decorators から呼ぶ。
将来の DRF API 移行時にもそのまま使える。
"""

from apps.permissions.models import ModulePermission, Role

# 役職で利用を絞るアプリ。ここに載っていないアプリは従来どおり全員が使える。
#
# 「載せたものだけ絞る」形にしているのは、役職 × 全アプリの表を先に作ると
# 未記入のマスに引っかかって既存の画面が突然閉じるため。制限したいものを
# 1行足していくほうが、閉じた範囲がそのまま読める。
#
# 値は workers.Position の名前と一致させる。Position は本番で全員に入って
# おり（社長/役員/正社員/シニア/ジュニア/試用期間/パート/Developer/
# アルバイト）、役職を判定できる唯一の項目になっている。
# permissions の Role は本番で0件のため、ここでは使えない。
POSITION_RESTRICTED_APPS = {
    # 人事評価（/evaluation/）は役員と Developer のみ。社長は上位職として通す。
    "hr_evaluation": ("社長", "役員", "Developer"),
}


def get_position_name(user):
    """ログインユーザーの役職名を返す。作業員が紐づいていなければ空文字。"""
    profile = getattr(user, "worker_profile", None)
    if not profile or not profile.position:
        return ""
    return profile.position.name


def can_use_app(user, app_code: str) -> bool:
    """役職から見て、そのアプリを使ってよいかを判定する。

    POSITION_RESTRICTED_APPS に無いアプリは常に True。
    Worker.allowed_apps による個別の制限は AppPermissionMiddleware が
    別に見ているので、ここでは役職だけを判断する。
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    allowed_positions = POSITION_RESTRICTED_APPS.get(app_code)
    if allowed_positions is None:
        return True

    # 社員番号 Y 始まり（管理者）は AppPermissionMiddleware でも素通しに
    # しているので、判定をそちらに合わせる。
    profile = getattr(user, "worker_profile", None)
    if profile and profile.employee_code and profile.employee_code.startswith("Y"):
        return True

    return get_position_name(user) in allowed_positions


def get_user_roles(user):
    """ユーザーのロール一覧を取得する。"""
    return Role.unscoped.filter(
        user_roles__user=user,
    ).distinct()


def has_role(user, *codes) -> bool:
    """ユーザーが指定ロールコードのいずれかを持つかチェック。

    superuser は常に True。
    """
    if user.is_superuser:
        return True
    # unscoped: ロールはユーザー本人に紐づくためテナント横断で引く
    from apps.permissions.models import UserRole

    return UserRole.unscoped.filter(user=user, role__code__in=codes).exists()


def is_president(user) -> bool:
    """社長かどうかを判定する。

    permissions の president ロール、または Worker の役職名「社長」で判定する。
    """
    if user.is_superuser:
        return True
    if has_role(user, "president"):
        return True
    profile = getattr(user, "worker_profile", None)
    return bool(profile and profile.position and profile.position.name == "社長")


def can_approve_report(user) -> bool:
    """日報を承認できるユーザーかどうかを判定する。

    承認できるのは社長と IT（developer ロール）のみ。
    """
    return is_president(user) or has_role(user, "developer")


def can_delete_report(user, report) -> bool:
    """日報を削除できるかどうかを判定する。

    ログインしていれば誰でも削除できる。ただし承認済の日報は削除できない
    （承認時に労務費を計上済みで、消すと原価との整合が崩れるため）。
    """
    from apps.reports.models import DailyReport

    return report.status != DailyReport.Status.APPROVED


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

    # 原価モジュールは専用のアクセス制御を使う
    if module == "costs":
        return _has_cost_access(user, level)

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


def _has_cost_access(user, level: str = "read") -> bool:
    """原価・予実モジュールの専用アクセスチェック。

    以下のいずれかに該当する場合にアクセスを許可する:
    1. 社長ロールを持つユーザー
    2. 社員番号が G で始まるユーザー
    3. CostAccessGrant で個別に許可されたユーザー

    write/admin 権限は社長ロール or 既存の ModulePermission で判定する。
    """
    from apps.costs.models import CostAccessGrant

    # 1. 社長ロール → 全レベルOK
    is_president = Role.unscoped.filter(
        code="president",
        user_roles__user=user,
    ).exists()
    if is_president:
        return True

    # 2. 役員・developer ロール → read/write OK
    is_executive_or_dev = Role.unscoped.filter(
        code__in=["executive", "developer"],
        user_roles__user=user,
    ).exists()
    if is_executive_or_dev and level in ("read", "write"):
        return True

    # read レベルのみ: 社員番号G始まり or 個別許可
    if level == "read":
        # 3. 社員番号が G で始まる
        if user.employee_no and user.employee_no.upper().startswith("G"):
            return True

        # 4. 管理者が個別に許可したユーザー
        if CostAccessGrant.unscoped.filter(user=user).exists():
            return True

    # write/admin: 従来の ModulePermission に従う
    field_map = {
        "read": "can_read",
        "write": "can_write",
        "admin": "can_admin",
    }
    field = field_map.get(level, "can_read")

    return ModulePermission.unscoped.filter(
        role__user_roles__user=user,
        module="costs",
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
