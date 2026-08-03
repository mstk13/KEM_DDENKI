"""権限管理画面。社長が権限マトリクスを確認・変更する。"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import User
from apps.permissions.decorators import module_permission_required
from apps.permissions.models import ModulePermission, Role, UserRole
from apps.permissions.services import get_permission_matrix, setup_default_roles


@login_required
@module_permission_required("settings", "admin")
def permission_matrix(request):
    """ロール × モジュール 権限マトリクス画面。"""
    company = request.user.company

    # 初回アクセス時にデフォルトロールを作成
    if not Role.unscoped.filter(company=company).exists():
        setup_default_roles(company, created_by=request.user)

    if request.method == "POST":
        # マトリクスの更新
        roles = Role.unscoped.filter(company=company)
        for role in roles:
            for mod_code, _ in ModulePermission.MODULE_CHOICES:
                can_read = request.POST.get(f"{role.pk}_{mod_code}_read") == "on"
                can_write = request.POST.get(f"{role.pk}_{mod_code}_write") == "on"
                can_admin = request.POST.get(f"{role.pk}_{mod_code}_admin") == "on"

                ModulePermission.unscoped.update_or_create(
                    company=company,
                    role=role,
                    module=mod_code,
                    defaults={
                        "can_read": can_read,
                        "can_write": can_write,
                        "can_admin": can_admin,
                    },
                )
        messages.success(request, "権限を更新しました。")
        return redirect("permissions:matrix")

    data = get_permission_matrix(company)
    return render(request, "permissions/matrix.html", data)


@login_required
@module_permission_required("settings", "admin")
def user_role_list(request):
    """ユーザー × ロール 管理画面。"""
    company = request.user.company
    users = User.objects.filter(company=company, is_active=True).order_by("username")
    roles = Role.unscoped.filter(company=company).order_by("code")
    user_roles = UserRole.unscoped.filter(company=company).select_related("user", "role")

    # ユーザーごとのロールをまとめる
    user_role_map = {}
    for ur in user_roles:
        user_role_map.setdefault(ur.user_id, []).append(ur.role)

    return render(request, "permissions/user_roles.html", {
        "users": users,
        "roles": roles,
        "user_role_map": user_role_map,
    })


@login_required
@module_permission_required("settings", "admin")
def user_role_update(request, user_id):
    """ユーザーのロールを更新する。"""
    if request.method != "POST":
        return redirect("permissions:user_roles")

    company = request.user.company
    target_user = get_object_or_404(User, pk=user_id, company=company)
    roles = Role.unscoped.filter(company=company)

    # 既存のロールを全削除して再作成
    UserRole.unscoped.filter(company=company, user=target_user).delete()

    for role in roles:
        if request.POST.get(f"role_{role.pk}") == "on":
            UserRole.unscoped.create(
                company=company,
                user=target_user,
                role=role,
                granted_by=request.user,
            )

    messages.success(request, f"{target_user} のロールを更新しました。")
    return redirect("permissions:user_roles")
