"""
テナント分離ミドルウェア。

認証済みユーザーの company をリクエストごとに contextvar へセットする。
"""

from apps.core.tenant_context import set_current_company


class TenantMiddleware:
    """リクエストごとにテナントコンテキストをセットするミドルウェア。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        company = None
        if hasattr(request, "user") and request.user.is_authenticated:
            company = getattr(request.user, "company", None)
        token = set_current_company(company)
        try:
            response = self.get_response(request)
        finally:
            from apps.core.tenant_context import _current_company

            _current_company.reset(token)
        return response
