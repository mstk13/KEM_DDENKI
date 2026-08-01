"""
アプリケーション有効化チェックデコレータ。

テナントごとに無効化されたアプリの URL を 404 にする。
"""

from functools import wraps

from django.http import Http404


def app_required(app_code):
    """指定 app_code がテナントで有効でなければ 404 を返す。"""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not hasattr(request, "user") or not request.user.is_authenticated:
                raise Http404
            company = getattr(request.user, "company", None)
            if company is None:
                raise Http404
            from apps.tenants.models import CompanyApp

            # unscoped: 管理テーブルはテナント横断で参照する必要がある
            if not CompanyApp.unscoped.filter(
                company=company,
                app_code=app_code,
                is_enabled=True,
            ).exists():
                raise Http404
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
