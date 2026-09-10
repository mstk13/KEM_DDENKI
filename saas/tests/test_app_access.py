"""permissions.AppAccess — 機能別の利用者リストとアプリキー一覧（ADR-0030）。

expand の段階。ミドルウェア・ナビはまだ has_app_access を使っていないので、
ここではレジストリが今のミドルウェアと食い違わないことと、モデル・判定関数の
約束だけを固定する。
"""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.core.middleware import _PATH_TO_APP
from apps.core.tenant_context import set_current_company
from apps.permissions.app_registry import APP_CHOICES, APPS, app_key_for_path, get_app
from apps.permissions.models import AppAccess
from apps.permissions.services import can_approve_app, has_app_access
from apps.workers.models import Worker


def _middleware_app_code(path):
    """AppPermissionMiddleware が今 path をどのアプリコードに解決するか。

    ミドルウェアは解決を関数に切り出していないので、同じ手順をここに写す。
    _PATH_TO_APP を直接読むので、あちらの表が変わればこのテストが気づく。
    """
    for prefix, code in _PATH_TO_APP.items():
        if path.startswith(prefix):
            if code == "workers" and "/evaluations/" in path:
                return "evaluations"
            return code
    return None


def _worker(company, name="作業員", user=None):
    return Worker.unscoped.create(company=company, user=user, name=name, hourly_cost=3000)


def _superuser(company):
    return User.objects.create_superuser(
        username="admin_test", password="testpass123", company=company,
    )


class TestAppRegistry:
    def test_キーが重複していない(self):
        keys = [app.key for app in APPS]
        assert len(keys) == len(set(keys))

    def test_前置きが二つの機能にまたがっていない(self):
        prefixes = [prefix for app in APPS for prefix in app.path_prefixes]
        assert len(prefixes) == len(set(prefixes))

    def test_ミドルウェアのアプリコードはすべて登録されている(self):
        registered = {app.key for app in APPS}
        assert set(_PATH_TO_APP.values()) | {"evaluations"} <= registered

    def test_モデルの選択肢はレジストリの並びどおり(self):
        assert [key for key, _label in APP_CHOICES] == [app.key for app in APPS]

    @pytest.mark.parametrize(
        "path",
        [
            "/sites/1/",
            "/reports/",
            "/schedules/",
            "/costs/1/",
            "/materials/orders/",
            "/workers/",
            "/workers/1/",
            "/workers/evaluations/",
            "/workers/1/evaluations/",
            "/bids/",
            "/dev/projects/",
            "/masters/customers/",
            "/sales/",
            "/notifications/",
            "/settings/permissions/",
            "/evaluation/",
            "/evaluation/assignments/",
        ],
    )
    def test_今のミドルウェアと同じ機能に解決する(self, path):
        assert _middleware_app_code(path) is not None
        assert app_key_for_path(path) == _middleware_app_code(path)

    @pytest.mark.parametrize(
        ("path", "key"),
        [
            ("/attendance/plans/", "attendance"),
            ("/estimation/projects/", "estimation"),
            ("/ai/", "ai"),
            ("/audit-log/", "settings"),
        ],
    )
    def test_ミドルウェアに無い前置きも解決する(self, path, key):
        assert _middleware_app_code(path) is None
        assert app_key_for_path(path) == key

    def test_書類アラートは作業員管理から分けて解決する(self):
        """ミドルウェアは今 workers として扱う。切り替えの PR でここが分かれる。"""
        path = "/workers/document-alerts/"
        assert _middleware_app_code(path) == "workers"
        assert app_key_for_path(path) == "document_alerts"

    @pytest.mark.parametrize("path", ["/", "/login/", "/admin/", "/health/", "/evaluations/"])
    def test_どの機能にも属さないパスはNone(self, path):
        assert app_key_for_path(path) is None

    def test_承認リストを持つのは日報と原価だけ(self):
        assert {app.key for app in APPS if app.approvable} == {"reports", "costs"}

    def test_未登録のキーはValueError(self):
        with pytest.raises(ValueError):
            get_app("report")


@pytest.mark.django_db
class TestAppAccessModel:
    def test_他社の利用者リストは見えない(self, company_a, company_b):
        AppAccess.unscoped.create(
            company=company_a, worker=_worker(company_a, "A社の人"), app_key="reports",
        )
        AppAccess.unscoped.create(
            company=company_b, worker=_worker(company_b, "B社の人"), app_key="reports",
        )

        set_current_company(company_a)
        try:
            names = list(AppAccess.objects.values_list("worker__name", flat=True))
        finally:
            set_current_company(None)

        assert names == ["A社の人"]

    def test_同じ作業員と機能の組は二重に登録できない(self, company_a):
        worker = _worker(company_a)
        AppAccess.unscoped.create(company=company_a, worker=worker, app_key="reports")

        with pytest.raises(IntegrityError), transaction.atomic():
            AppAccess.unscoped.create(company=company_a, worker=worker, app_key="reports")

    def test_変更履歴が残る(self, company_a):
        access = AppAccess.unscoped.create(
            company=company_a, worker=_worker(company_a), app_key="costs",
        )

        assert access.history.count() == 1


@pytest.mark.django_db
class TestHasAppAccess:
    """テナントコンテキストを張らずに呼ぶ。ミドルウェアから使う形に合わせている。"""

    def test_未ログインは使えない(self):
        assert has_app_access(AnonymousUser(), "reports") is False

    def test_superuserはリストに無くても使える(self, company_a):
        assert has_app_access(_superuser(company_a), "reports") is True

    def test_作業員が紐づいていなければ使えない(self, user_a):
        assert has_app_access(user_a, "reports") is False

    def test_リストに入っていれば使える(self, company_a, user_a):
        worker = _worker(company_a, user=user_a)
        AppAccess.unscoped.create(company=company_a, worker=worker, app_key="reports")

        assert has_app_access(user_a, "reports") is True

    def test_リストに入っていない機能は使えない(self, company_a, user_a):
        worker = _worker(company_a, user=user_a)
        AppAccess.unscoped.create(company=company_a, worker=worker, app_key="reports")

        assert has_app_access(user_a, "costs") is False

    def test_他社の行では開かない(self, company_a, company_b, user_a):
        worker = _worker(company_a, user=user_a)
        # 会社の食い違った行と、他社の別人への付与。どちらも自社の判定に効かない。
        AppAccess.unscoped.create(company=company_b, worker=worker, app_key="reports")
        AppAccess.unscoped.create(
            company=company_b, worker=_worker(company_b, "B社の人"), app_key="reports",
        )

        assert has_app_access(user_a, "reports") is False

    def test_未登録のキーは誰であってもValueError(self, company_a, user_a):
        for user in (AnonymousUser(), user_a, _superuser(company_a)):
            with pytest.raises(ValueError):
                has_app_access(user, "report")


@pytest.mark.django_db
class TestCanApproveApp:
    def test_承認フラグがあれば承認できる(self, company_a, user_a):
        worker = _worker(company_a, user=user_a)
        AppAccess.unscoped.create(
            company=company_a, worker=worker, app_key="reports", can_approve=True,
        )

        assert can_approve_app(user_a, "reports") is True

    def test_利用者でも承認フラグが無ければ承認できない(self, company_a, user_a):
        worker = _worker(company_a, user=user_a)
        AppAccess.unscoped.create(company=company_a, worker=worker, app_key="reports")

        assert has_app_access(user_a, "reports") is True
        assert can_approve_app(user_a, "reports") is False

    def test_承認のない機能はフラグがあっても承認できない(self, company_a, user_a):
        worker = _worker(company_a, user=user_a)
        AppAccess.unscoped.create(
            company=company_a, worker=worker, app_key="sites", can_approve=True,
        )

        assert can_approve_app(user_a, "sites") is False

    def test_superuserは承認のある機能だけ承認できる(self, company_a):
        admin = _superuser(company_a)

        assert can_approve_app(admin, "costs") is True
        assert can_approve_app(admin, "sites") is False

    def test_未ログインや作業員なしは承認できない(self, user_a):
        assert can_approve_app(AnonymousUser(), "reports") is False
        assert can_approve_app(user_a, "reports") is False

    def test_他社の行では承認できない(self, company_a, company_b, user_a):
        worker = _worker(company_a, user=user_a)
        AppAccess.unscoped.create(
            company=company_b, worker=worker, app_key="costs", can_approve=True,
        )

        assert can_approve_app(user_a, "costs") is False

    def test_未登録のキーはValueError(self, user_a):
        with pytest.raises(ValueError):
            can_approve_app(user_a, "cost")
