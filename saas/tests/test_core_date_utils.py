"""apps.core.date_utils — 月・年加算の境界。

健診期限アラートが本番で ModuleNotFoundError（dateutil 未同梱）で落ちていたため、
dateutil.relativedelta を置き換えた。relativedelta と同じ丸め方であることを固定する。
"""

from datetime import date

from apps.core.date_utils import add_months, add_years


def test_月内の単純な加算():
    assert add_months(date(2026, 8, 15), 2) == date(2026, 10, 15)


def test_年をまたぐ加算():
    assert add_months(date(2026, 11, 30), 2) == date(2027, 1, 30)


def test_加算先に同じ日が無ければ月末に丸める():
    assert add_months(date(2026, 12, 31), 2) == date(2027, 2, 28)
    assert add_months(date(2026, 8, 31), 1) == date(2026, 9, 30)


def test_閏年の2月29日は非閏年で2月28日になる():
    assert add_years(date(2028, 2, 29), 1) == date(2029, 2, 28)


def test_閏年から閏年への加算は日付が保たれる():
    assert add_years(date(2028, 2, 29), 4) == date(2032, 2, 29)


def test_1年後の加算():
    assert add_years(date(2026, 8, 15), 1) == date(2027, 8, 15)


def test_負の加算():
    assert add_months(date(2026, 1, 31), -1) == date(2025, 12, 31)
    assert add_months(date(2026, 3, 31), -1) == date(2026, 2, 28)


def test_ゼロ加算は同じ日付():
    assert add_months(date(2026, 8, 15), 0) == date(2026, 8, 15)
