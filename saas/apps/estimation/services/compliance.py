"""コンプライアンスチェックサービス。

S6: 積算結果が公契約条例の労働報酬下限額を下回っていないか検証する。
違反はブロッキングとして扱う。
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Q

from apps.estimation.models import WageFloor


@dataclass
class WageViolation:
    """下限額違反の詳細。"""

    municipality: str
    occupation_name: str
    hourly_floor: Decimal
    actual_hourly: Decimal
    worker_type: str
    ordinance_ref: str


def resolve_wage_floor(
    *, municipality: str, occupation_code: str, reference_date: date,
    worker_type: str = "regular",
) -> WageFloor | None:
    """基準日時点で有効な労働報酬下限額を返す。"""
    return (
        WageFloor.objects.filter(
            municipality=municipality,
            occupation_code=occupation_code,
            worker_type=worker_type,
            valid_from__lte=reference_date,
        )
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=reference_date))
        .order_by("-valid_from")
        .first()
    )


def check_wage_floors(
    municipality: str,
    labor_items: list[dict],
    reference_date: date,
) -> list[WageViolation]:
    """積算結果の労務費が公契約条例の下限額を下回っていないか検証する。

    labor_items: [{"occupation_code": str, "hourly_rate": Decimal}, ...]

    Returns:
        違反リスト。空なら問題なし。
    """
    violations = []

    for item in labor_items:
        floor = resolve_wage_floor(
            municipality=municipality,
            occupation_code=item["occupation_code"],
            reference_date=reference_date,
        )
        if floor is None:
            continue

        actual = item["hourly_rate"]
        if actual < floor.hourly_floor:
            violations.append(WageViolation(
                municipality=municipality,
                occupation_name=floor.occupation_name,
                hourly_floor=floor.hourly_floor,
                actual_hourly=actual,
                worker_type=floor.worker_type,
                ordinance_ref=floor.ordinance_ref,
            ))

    return violations
