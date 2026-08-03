from django import template

register = template.Library()


@register.filter(name="get_nested")
def get_nested(d, key):
    """辞書からキーで値を取得する。テンプレートでネストした辞書にアクセスするため。"""
    if isinstance(d, dict):
        return d.get(key, {})
    return {}
