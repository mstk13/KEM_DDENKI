"""
テナント分離ミドルウェア + キャッシュ制御。

認証済みユーザーの company をリクエストごとに contextvar へセットする。
"""

from django.core.exceptions import PermissionDenied

from apps.core.tenant_context import set_current_company


class NoCacheMiddleware:
    """HTMLレスポンスにキャッシュ無効化ヘッダーを付与する。

    動的データを常にDBから取得させるため、ブラウザキャッシュを防ぐ。
    静的ファイル（CSS/JS/画像）はwhitenoiseが配信するため影響しない。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        content_type = response.get("Content-Type", "")
        if "text/html" in content_type:
            response["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
        return response

# URLパスの先頭 → アプリコード のマッピング
_PATH_TO_APP = {
    "/sites/": "sites",
    "/reports/": "reports",
    "/schedules/": "schedules",
    "/costs/": "costs",
    "/materials/": "materials",
    "/workers/": "workers",
    "/bids/": "bids",
    "/dev/": "devkanri",
    "/masters/": "masters",
    "/sales/": "sales",
    "/notifications/": "notifications",
    "/settings/": "settings",
    # 人事評価。/workers/evaluations/ の「人材評価」とは別アプリなので
    # コードも分けている（あちらは下の分岐で "evaluations" になる）。
    # ここに載せるまでは /evaluation/ 配下が権限チェックを素通りしていた。
    "/evaluation/": "hr_evaluation",
}

# 権限チェック不要のパス
_EXEMPT_PREFIXES = ("/admin/", "/login/", "/logout/", "/health/", "/static/", "/media/")


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


class AppPermissionMiddleware:
    """作業員ごとのアプリ権限を強制するミドルウェア。

    allowed_apps が空リストの場合は制限なし（全アプリアクセス可）。
    管理者（社員番号Y始まり / superuser）は常にアクセス可。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not hasattr(request, "user") or not request.user.is_authenticated:
            return self.get_response(request)

        path = request.path

        # 免除パス
        if path == "/" or any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return self.get_response(request)

        # 管理者はスキップ
        if request.user.is_superuser:
            return self.get_response(request)
        profile = getattr(request.user, "worker_profile", None)
        if profile and profile.employee_code and profile.employee_code.startswith("Y"):
            return self.get_response(request)

        # アプリコード判定
        app_code = None
        for prefix, code in _PATH_TO_APP.items():
            if path.startswith(prefix):
                app_code = code
                break

        if app_code is None:
            return self.get_response(request)

        # 評価系URLの判定
        if app_code == "workers" and "/evaluations/" in path:
            app_code = "evaluations"

        # 役職による制限。allowed_apps を設定していない人にも効かせたいので、
        # 個別設定より先に見る。
        from apps.permissions.services import can_use_app

        if not can_use_app(request.user, app_code):
            raise PermissionDenied("この機能は担当の役職の方のみが利用できます。")

        # 権限チェック
        if profile and profile.allowed_apps and app_code not in profile.allowed_apps:
            raise PermissionDenied("このアプリへのアクセスが許可されていません。")

        return self.get_response(request)
