from django.conf import settings

from apps.core.navigation import build_navigation, build_section_tabs


def branding(request):
    return {
        "APP_NAME": getattr(settings, "APP_NAME", "KEC"),
        "APP_NAME_FULL": getattr(settings, "APP_NAME_FULL", "KEC 業務管理システム"),
        "APP_SUBTITLE": getattr(settings, "APP_SUBTITLE", "業務管理プラットフォーム"),
        "APP_THEME_COLOR": getattr(settings, "APP_THEME_COLOR", "#1a2744"),
    }


def navigation(request):
    """サイドバーの項目と active 状態、画面上部のタブ。

    resolver_match は 404 / 500 ページでは None になる。その場合は
    どこも active にせず、リンクだけを出す（タブは出さない）。

    user を渡すのは、役職で使えない項目を出さないため
    （人事評価は役員・Developer のみ）。
    """
    match = getattr(request, "resolver_match", None)
    view_name = match.view_name if match else None
    return {
        "nav": build_navigation(view_name, getattr(request, "user", None)),
        "section_tabs": build_section_tabs(view_name),
    }
