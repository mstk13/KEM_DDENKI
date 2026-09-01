"""日付の月・年加算。

`dateutil.relativedelta` と同じ用途だが、python-dateutil は本番イメージに
入っていない（pyproject の依存に無く、ローカルの .venv にだけ他パッケージ経由で
入っていた）。そのため健診期限アラートが本番で毎日 ModuleNotFoundError で
落ちていた。依存追加は ADR 必須のため、必要な2演算だけ stdlib で用意する。

月末の扱いは relativedelta と同じ「存在しない日は月末に丸める」。
  2026-12-31 + 2ヶ月 → 2027-02-28
  2028-02-29 + 1年   → 2029-02-28
"""

import calendar
from datetime import date


def add_months(value: date, months: int) -> date:
    """月を加算する。加算先に同じ日が無ければ月末に丸める。"""
    total = value.month - 1 + months
    year = value.year + total // 12
    month = total % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def add_years(value: date, years: int) -> date:
    """年を加算する。2月29日は非閏年では2月28日に丸める。"""
    return add_months(value, years * 12)
