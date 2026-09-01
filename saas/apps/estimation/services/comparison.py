"""差分分析（CostComparison）の計算サービス。

品目ごとに「発注者基準単価 vs 自社仕入単価」を算出する。
出力は「想定粗利」として設計。
"""

from decimal import Decimal

from apps.estimation.models import (
    CostComparison,
    EstimationProject,
    PurchaseRecord,
)


def calc_own_price(estimation_item, company) -> tuple[Decimal | None, str]:
    """自社の仕入単価を算出する。

    直近の仕入実績から中央値を計算する。
    Returns:
        (単価, 算出根拠の説明文)
    """
    records = PurchaseRecord.unscoped.filter(  # unscoped: company を明示指定
        company=company,
        estimation_item=estimation_item,
    ).order_by("-purchase_date")[:20]

    if not records:
        return None, "仕入実績なし"

    prices = sorted([r.unit_price for r in records])
    n = len(prices)
    median = (prices[n // 2 - 1] + prices[n // 2]) / 2 if n % 2 == 0 else prices[n // 2]

    return Decimal(str(int(median))), f"直近{n}件の中央値"


def generate_comparisons(project: EstimationProject) -> dict:
    """積算案件の全品目について差分分析を生成する。

    内訳書（BoqLine）に紐づく品目ごとに、
    発注者基準単価と自社仕入単価を比較する。

    Returns:
        {"created": int, "updated": int, "total_diff": Decimal}
    """
    from apps.estimation.models import BoqLine

    lines = BoqLine.objects.filter(
        project=project,
        estimation_item__isnull=False,
        level="saimoku",
    ).select_related("estimation_item")

    created = 0
    updated = 0
    total_diff = Decimal("0")

    seen_items = set()

    for line in lines:
        item = line.estimation_item
        if item.pk in seen_items:
            continue
        seen_items.add(item.pk)

        own_price, basis = calc_own_price(item, project.company)

        # unscoped: company を明示指定
        comp, was_created = CostComparison.unscoped.update_or_create(
            company=project.company,
            project=project,
            estimation_item=item,
            defaults={
                "quantity": line.quantity,
                "standard_price": line.unit_price,
                "own_price": own_price,
                "own_price_basis": basis,
            },
        )
        comp.calc_diff()
        comp.save()

        if comp.diff_amount:
            total_diff += comp.diff_amount * (comp.quantity or Decimal("1"))

        if was_created:
            created += 1
        else:
            updated += 1

    return {
        "created": created,
        "updated": updated,
        "total_diff": total_diff,
    }
