from django.contrib import admin
from django.http import JsonResponse
from django.urls import path


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
]
