"""共通テストフィクスチャ。

2社（company_a / company_b）+ 各社ユーザーを作成し、
テナント越境テストの基盤とする。
"""

import pytest
from django.contrib.auth.models import Group

from apps.accounts.models import User
from apps.core.tenant_context import set_current_company
from apps.tenants.models import Company


@pytest.fixture
def company_a(db):
    return Company.objects.create(name="A社電気工事", industry_type="設備工事")


@pytest.fixture
def company_b(db):
    return Company.objects.create(name="B社内装工事", industry_type="内装工事")


@pytest.fixture
def user_a(company_a):
    user = User.objects.create_user(
        username="user_a",
        password="testpass123",
        company=company_a,
    )
    group, _ = Group.objects.get_or_create(name="worker")
    user.groups.add(group)
    return user


@pytest.fixture
def user_b(company_b):
    user = User.objects.create_user(
        username="user_b",
        password="testpass123",
        company=company_b,
    )
    group, _ = Group.objects.get_or_create(name="worker")
    user.groups.add(group)
    return user


@pytest.fixture
def company(company_a):
    """汎用 company フィクスチャ（company_a のエイリアス）。"""
    return company_a


@pytest.fixture
def user(user_a):
    """汎用 user フィクスチャ（user_a のエイリアス）。"""
    return user_a


@pytest.fixture
def user2(company_a):
    """2人目のユーザー（同一会社）。"""
    user = User.objects.create_user(
        username="user_a2",
        password="testpass123",
        company=company_a,
    )
    group, _ = Group.objects.get_or_create(name="worker")
    user.groups.add(group)
    return user


@pytest.fixture
def tenant_context_a(company_a):
    """テナントコンテキストをA社に設定するフィクスチャ。"""
    set_current_company(company_a)
    yield company_a
    set_current_company(None)


@pytest.fixture
def tenant_context_b(company_b):
    """テナントコンテキストをB社に設定するフィクスチャ。"""
    set_current_company(company_b)
    yield company_b
    set_current_company(None)


@pytest.fixture
def user_a_is_office_staff(company_a, user_a):
    """user_a に事務員ロールを付ける（ADR-0102）。

    他人の日報・勤怠を直せるのは社長・IT・事務員だけになった。勤怠の予定表や
    日報の編集画面は**事務員が全員ぶんを入力する**前提の画面なので、
    それらのテストはこのフィクスチャを autouse で使い、事務員として動かす。

    権限そのもの（誰が通って誰が 403 か）は
    tests/test_others_work_records_permission.py で見る。
    """
    from apps.permissions.models import Role, UserRole

    role, _ = Role.unscoped.get_or_create(
        company=company_a, code="office_staff", defaults={"name": "事務員"},
    )
    UserRole.unscoped.get_or_create(company=company_a, user=user_a, role=role)
    return user_a
