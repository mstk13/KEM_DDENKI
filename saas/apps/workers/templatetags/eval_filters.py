from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """辞書から変数キーで値を取得する。"""
    if isinstance(dictionary, dict):
        return dictionary.get(str(key))
    return None
