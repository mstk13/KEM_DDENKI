from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from apps.core.views import audit_log, dashboard


def _deployed_version():
    """自動デプロイが書き出した稼働中バージョンを読む。

    コンテナには saas/ しかマウントされておらず .git を読めないため、
    tools/autodeploy/autodeploy.sh が反映のたびにこのファイルを更新している。
    手元で docker compose up した場合はファイルが無いので空を返す。
    """
    path = settings.BASE_DIR / "deployed_version.txt"
    try:
        commit, branch, deployed_at = path.read_text(encoding="utf-8").strip().split("|", 2)
        return {"commit": commit, "branch": branch, "deployed_at": deployed_at}
    except (OSError, ValueError):
        return {"commit": None, "branch": None, "deployed_at": None}


def health_check(request):
    """DB到達性込みのヘルスチェック。稼働中のコミットも返す。

    「push した変更がもうサーバーに入っているか」をここで確認できる。
    """
    from django.db import connection

    payload = {"status": "ok", **_deployed_version()}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse(payload)
    except Exception as e:
        payload.update(status="error", detail=str(e))
        return JsonResponse(payload, status=503)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check),
    # Auth
    path("login/", include("apps.accounts.urls")),
    path("logout/", include("apps.accounts.urls_logout")),
    # Dashboard
    path("", dashboard, name="dashboard"),
    # Apps
    path("sites/", include("apps.sites.urls")),
    path("reports/", include("apps.reports.urls")),
    path("costs/", include("apps.costs.urls")),
    path("materials/", include("apps.materials.urls")),
    path("workers/", include("apps.workers.urls")),
    path("masters/", include("apps.masters.urls")),
    path("dev/", include("apps.devkanri.urls")),
    path("schedules/", include("apps.schedules.urls")),
    path("bids/", include("apps.bids.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("settings/permissions/", include("apps.permissions.urls")),
    path("sales/", include("apps.sales.urls")),
    path("attendance/", include("apps.attendance.urls")),
    path("evaluation/", include("apps.evaluation.urls")),
    path("ai/", include("apps.ai.urls")),
    path("estimation/", include("apps.estimation.urls")),
    path("audit-log/", audit_log, name="audit_log"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
