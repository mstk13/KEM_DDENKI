"""単価・基準の引き当てサービス。

すべての単価・率の参照を、必ずこのサービス層経由にすること。
ビューやテンプレートから直接 LaborRate.objects.filter(...) を書かない。
"""

from datetime import date

from django.db.models import Q

from apps.estimation.models import EstimationStandard, LaborRate, OverheadRule


def resolve_labor_rate(
    *, prefecture: str, occupation_code: str, reference_date: date
) -> LaborRate | None:
    """基準日時点で有効な労務単価を返す。approved のみ対象。"""
    return (
        LaborRate.objects.filter(
            prefecture=prefecture,
            occupation_code=occupation_code,
            status=LaborRate.Status.APPROVED,
            valid_from__lte=reference_date,
        )
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=reference_date))
        .order_by("-valid_from")
        .first()
    )


def resolve_standard(
    *, orderer, reference_date: date
) -> EstimationStandard | None:
    """発注者の applies_by に従って、基準日時点で有効な積算基準を返す。

    approved のみ対象。
    """
    return (
        EstimationStandard.objects.filter(
            orderer=orderer,
            status=EstimationStandard.Status.APPROVED,
            valid_from__lte=reference_date,
        )
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=reference_date))
        .order_by("-valid_from")
        .first()
    )


def resolve_overhead_rule(
    *, standard: EstimationStandard, work_category: str, cost_type: str
) -> OverheadRule | None:
    """積算基準に紐づく共通費率を返す。approved のみ対象。"""
    return (
        OverheadRule.objects.filter(
            standard=standard,
            work_category=work_category,
            cost_type=cost_type,
            status=OverheadRule.Status.APPROVED,
        )
        .first()
    )
