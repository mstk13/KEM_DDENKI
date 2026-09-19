"""
権限チェックデコレータ。ビュー関数に付けてモジュール単位のアクセス制御を行う。

使い方:
    @module_permission_required("costs", "read")
    def cost_dashboard(request):
        ...

    @module_permission_required("costs", "admin")
    def budget_edit(request, pk):
        ...
"""

from functools import wraps

from django.core.exceptions import PermissionDenied

from apps.permissions.services import has_module_permission


def module_permission_required(module: str, level: str = "read"):
    """モジュール権限チェックデコレータ。

    Args:
        module: モジュールコード（例: 'costs', 'reports'）
        level: 'read', 'write', 'admin'
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.shortcuts import redirect

                return redirect("login")

            if not has_module_permission(request.user, module, level):
                raise PermissionDenied(
                    f"「{module}」モジュールへの{level}権限が必要です。"
                )

            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def settings_admin_required(view_func):
    """権限管理の画面を開ける人だけ通す（ADR-0102）。

    settings の admin 権限に加えて、**社長と IT** を明示的に通す。
    ロールだけで見ていたため IT が開けなかった（developer ロールは本番で0件。
    ADR-0039 に同じ問題が日報承認で起きたことが書いてある）。
    アクセス権限を IT が管理できるようにする、というのが今回の指示。
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.shortcuts import redirect

            return redirect("login")

        from apps.permissions.services import can_open_settings_admin

        if can_open_settings_admin(request.user):
            return view_func(request, *args, **kwargs)

        raise PermissionDenied("権限管理の画面は社長と IT のみが開けます。")

    return _wrapped
