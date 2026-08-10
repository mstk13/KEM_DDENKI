from django.conf import settings


def branding(request):
    return {
        "APP_NAME": getattr(settings, "APP_NAME", "KEC"),
        "APP_NAME_FULL": getattr(settings, "APP_NAME_FULL", "KEC 業務管理システム"),
        "APP_SUBTITLE": getattr(settings, "APP_SUBTITLE", "業務管理プラットフォーム"),
        "APP_THEME_COLOR": getattr(settings, "APP_THEME_COLOR", "#1a2744"),
    }
