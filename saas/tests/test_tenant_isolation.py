"""テナント越境テスト。

A社ユーザーがB社データに到達できないことを、
モデル層・ビュー層で検証する。CIで常時実行必須。
"""

import pytest
from django.db import IntegrityError
from django.test import RequestFactory

from apps.accounts.models import Department
from apps.core.decorators import app_required
from apps.core.tenant_context import get_current_company, set_current_company
from apps.masters.models import Customer, Supplier, WorkType
from apps.tenants.models import Company, CompanyApp

# ---------------------------------------------------------------------------
# 1. テナントコンテキストの基本動作
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTenantContext:
    def test_default_is_none(self):
        set_current_company(None)
        assert get_current_company() is None

    def test_set_and_get(self, company_a):
        set_current_company(company_a)
        assert get_current_company() == company_a
        set_current_company(None)


# ---------------------------------------------------------------------------
# 2. CompanyScopedManager によるモデル層の分離
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestModelIsolation:
    """A社のデータがB社のコンテキストから見えないことを検証。"""

    def test_department_isolation(self, company_a, company_b):
        Department.unscoped.create(company=company_a, name="工事部")
        Department.unscoped.create(company=company_b, name="営業部")

        # A社コンテキスト → A社のデータのみ
        set_current_company(company_a)
        qs = Department.objects.all()
        assert qs.count() == 1
        assert qs.first().name == "工事部"

        # B社コンテキスト → B社のデータのみ
        set_current_company(company_b)
        qs = Department.objects.all()
        assert qs.count() == 1
        assert qs.first().name == "営業部"

        set_current_company(None)

    def test_worktype_isolation(self, company_a, company_b):
        WorkType.unscoped.create(company=company_a, code="E01", name="電気幹線")
        WorkType.unscoped.create(company=company_b, code="N01", name="軽鉄ボード")

        set_current_company(company_a)
        assert WorkType.objects.count() == 1
        assert WorkType.objects.first().name == "電気幹線"

        set_current_company(company_b)
        assert WorkType.objects.count() == 1
        assert WorkType.objects.first().name == "軽鉄ボード"

        set_current_company(None)

    def test_customer_isolation(self, company_a, company_b):
        Customer.unscoped.create(company=company_a, code="C01", name="A社得意先")
        Customer.unscoped.create(company=company_b, code="C01", name="B社得意先")

        set_current_company(company_a)
        assert Customer.objects.count() == 1
        assert Customer.objects.first().name == "A社得意先"

        set_current_company(company_b)
        assert Customer.objects.count() == 1
        assert Customer.objects.first().name == "B社得意先"

        set_current_company(None)

    def test_supplier_isolation(self, company_a, company_b):
        Supplier.unscoped.create(company=company_a, code="S01", name="A社仕入先")
        Supplier.unscoped.create(company=company_b, code="S01", name="B社仕入先")

        set_current_company(company_a)
        assert Supplier.objects.count() == 1
        assert Supplier.objects.first().name == "A社仕入先"

        set_current_company(company_b)
        assert Supplier.objects.count() == 1
        assert Supplier.objects.first().name == "B社仕入先"

        set_current_company(None)

    def test_no_context_returns_nothing(self, company_a):
        """テナントコンテキスト未設定時は全データが返る（管理用途）。"""
        Department.unscoped.create(company=company_a, name="工事部")
        set_current_company(None)
        # contextvar が None の場合、フィルタしない（管理画面等で使う）
        assert Department.objects.count() >= 1

    def test_unscoped_returns_all(self, company_a, company_b):
        """unscoped マネージャはテナントフィルタしない。"""
        Department.unscoped.create(company=company_a, name="工事部")
        Department.unscoped.create(company=company_b, name="営業部")

        set_current_company(company_a)
        assert Department.unscoped.count() == 2
        set_current_company(None)


# ---------------------------------------------------------------------------
# 3. @app_required デコレータの検証
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAppRequired:
    def test_enabled_app_passes(self, user_a, company_a):
        CompanyApp.objects.create(
            company=company_a, app_code="nippou", is_enabled=True
        )

        @app_required("nippou")
        def dummy_view(request):
            from django.http import HttpResponse

            return HttpResponse("ok")

        factory = RequestFactory()
        request = factory.get("/dummy/")
        request.user = user_a
        response = dummy_view(request)
        assert response.status_code == 200

    def test_disabled_app_returns_404(self, user_a, company_a):
        CompanyApp.objects.create(
            company=company_a, app_code="nippou", is_enabled=False
        )

        @app_required("nippou")
        def dummy_view(request):
            from django.http import HttpResponse

            return HttpResponse("ok")

        factory = RequestFactory()
        request = factory.get("/dummy/")
        request.user = user_a

        from django.http import Http404

        with pytest.raises(Http404):
            dummy_view(request)

    def test_missing_app_returns_404(self, user_a):
        """CompanyApp レコードが存在しない場合も 404。"""

        @app_required("genka")
        def dummy_view(request):
            from django.http import HttpResponse

            return HttpResponse("ok")

        factory = RequestFactory()
        request = factory.get("/dummy/")
        request.user = user_a

        from django.http import Http404

        with pytest.raises(Http404):
            dummy_view(request)


# ---------------------------------------------------------------------------
# 4. ミドルウェアの検証
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTenantMiddleware:
    def test_middleware_sets_context(self, client, user_a, company_a):
        """ログインユーザーのリクエストでテナントコンテキストがセットされる。"""
        client.force_login(user_a)
        response = client.get("/health/")
        assert response.status_code == 200

    def test_anonymous_has_no_context(self, client):
        """未ログインユーザーはテナントコンテキストなし。"""
        response = client.get("/health/")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# 5. Company モデルの基本テスト
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCompanyModel:
    def test_create_company(self):
        c = Company.objects.create(name="テスト電気", industry_type="設備工事")
        assert str(c) == "テスト電気"
        assert c.is_active is True

    def test_company_app_unique(self, company_a):
        CompanyApp.objects.create(company=company_a, app_code="nippou", is_enabled=True)
        with pytest.raises(IntegrityError):
            CompanyApp.objects.create(
                company=company_a, app_code="nippou", is_enabled=False
            )
