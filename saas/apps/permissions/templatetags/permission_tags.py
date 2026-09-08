from django import template

from apps.permissions.services import can_use_app

register = template.Library()


@register.filter(name="can_use")
def can_use(user, app_code):
    """役職から見てそのアプリを使えるか。サイドバーの出し分けに使う。

    ミドルウェアと同じ判定を通すので、「メニューには出るのに押すと403」に
    ならない。判定の実体は permissions.services.can_use_app にある。
    """
    return can_use_app(user, app_code)


@register.filter(name="get_nested")
def get_nested(d, key):
    """辞書からキーで値を取得する。テンプレートでネストした辞書にアクセスするため。"""
    if isinstance(d, dict):
        return d.get(key, {})
    return {}
