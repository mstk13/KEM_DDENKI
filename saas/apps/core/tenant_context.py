"""
contextvar によるテナントコンテキスト管理。

リクエストごとにミドルウェアがセットし、CompanyScopedManager が参照する。
"""

from contextvars import ContextVar

_current_company: ContextVar = ContextVar("current_company", default=None)


def get_current_company():
    return _current_company.get()


def set_current_company(company):
    return _current_company.set(company)
