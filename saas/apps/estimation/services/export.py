"""データエクスポートのガード。

S4: 製品配布用エクスポート時に、licensed/tenant データの混入を防ぐ。
この関数は今すぐ使わないが、外販判断の時点で仕分けできるよう先に用意する。
"""


class DataScopeViolation(Exception):
    """同梱不可データが含まれている場合の例外。"""

    pass


FORBIDDEN_SCOPES_FOR_PRODUCT = {"licensed", "tenant"}


def check_export_safety(queryset):
    """queryset に licensed/tenant データが含まれていないか検証する。

    含まれていれば DataScopeViolation を送出する。
    """
    leaked = queryset.filter(data_scope__in=FORBIDDEN_SCOPES_FOR_PRODUCT)
    if leaked.exists():
        raise DataScopeViolation(
            f"{leaked.count()}件の同梱不可データが含まれています"
        )
