from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import JsonResponse
from django.urls import include, path

from apps.core.views import dashboard


def health_check(request):
    """DB到達性込みのヘルスチェック。"""
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "ok"})
    except Exception as e:
        return JsonResponse({"status": "error", "detail": str(e)}, status=503)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check),
    # Auth
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
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
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
