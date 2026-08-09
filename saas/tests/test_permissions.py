"""権限管理のテスト。"""

import pytest
from django.db import IntegrityError

from apps.permissions.models import ModulePermission, Role, UserRole
from apps.permissions.services import (
    get_user_roles,
    has_module_permission,
    setup_default_roles,
)


@pytest.mark.django_db
class TestRoleModel:
    def test_create_role(self, company):
        role = Role.unscoped.create(
            company=company,
            code="president",
            name="社長",
        )
        assert role.pk is not None
        assert str(role) == "社長"

    def test_unique_code_per_company(self, company):
        Role.unscoped.create(company=company, code="test", name="テスト")
        # unique_together(company, code) 違反であることまで確かめる
        # （Exception だと想定外のエラーでもテストが通ってしまう）
        with pytest.raises(IntegrityError):
            Role.unscoped.create(company=company, code="test", name="テスト2")


@pytest.mark.django_db
class TestModulePermission:
    def test_create_permission(self, company):
        role = Role.unscoped.create(company=company, code="admin", name="管理者")
        perm = ModulePermission.unscoped.create(
            company=company,
            role=role,
            module="costs",
            can_read=True,
            can_write=False,
            can_admin=False,
        )
        assert "R" in str(perm)
        assert "W" not in str(perm)


@pytest.mark.django_db
class TestSetupDefaultRoles:
    def test_creates_6_roles(self, company):
        setup_default_roles(company)
        roles = Role.unscoped.filter(company=company)
        assert roles.count() == 6

    def test_president_has_all_permissions(self, company):
        setup_default_roles(company)
        president = Role.unscoped.get(company=company, code="president")
        perms = ModulePermission.unscoped.filter(role=president)
        for perm in perms:
            assert perm.can_read is True
            assert perm.can_write is True
            assert perm.can_admin is True

    def test_site_manager_cannot_access_costs(self, company):
        setup_default_roles(company)
        site_mgr = Role.unscoped.get(company=company, code="site_manager")
        cost_perm = ModulePermission.unscoped.filter(
            role=site_mgr, module="costs",
        ).first()
        assert cost_perm is None  # 現場担当者には原価権限なし

    def test_idempotent(self, company):
        setup_default_roles(company)
        setup_default_roles(company)  # 2回目
        assert Role.unscoped.filter(company=company).count() == 6


@pytest.mark.django_db
class TestHasModulePermission:
    def test_superuser_always_permitted(self, company, user):
        user.is_superuser = True
        user.save()
        assert has_module_permission(user, "costs", "admin") is True

    def test_no_role_no_permission(self, company, user):
        setup_default_roles(company)
        assert has_module_permission(user, "costs", "read") is False

    def test_president_can_read_costs(self, company, user):
        setup_default_roles(company)
        president_role = Role.unscoped.get(company=company, code="president")
        UserRole.unscoped.create(
            company=company, user=user, role=president_role,
        )
        assert has_module_permission(user, "costs", "read") is True
        assert has_module_permission(user, "costs", "admin") is True

    def test_site_manager_cannot_read_costs(self, company, user):
        setup_default_roles(company)
        site_mgr = Role.unscoped.get(company=company, code="site_manager")
        UserRole.unscoped.create(
            company=company, user=user, role=site_mgr,
        )
        assert has_module_permission(user, "costs", "read") is False
        assert has_module_permission(user, "reports", "write") is True


@pytest.mark.django_db
class TestGetUserRoles:
    def test_get_roles(self, company, user):
        setup_default_roles(company)
        role = Role.unscoped.get(company=company, code="site_manager")
        UserRole.unscoped.create(company=company, user=user, role=role)

        roles = get_user_roles(user)
        assert roles.count() == 1
        assert roles.first().code == "site_manager"

    def test_multiple_roles(self, company, user):
        setup_default_roles(company)
        r1 = Role.unscoped.get(company=company, code="site_manager")
        r2 = Role.unscoped.get(company=company, code="developer")
        UserRole.unscoped.create(company=company, user=user, role=r1)
        UserRole.unscoped.create(company=company, user=user, role=r2)

        roles = get_user_roles(user)
        assert roles.count() == 2
