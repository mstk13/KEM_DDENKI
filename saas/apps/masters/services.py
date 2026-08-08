"""取引先管理のビジネスロジック。

取引履歴、評価集計を担う。
将来の DRF API 移行時にもそのまま使える。
"""

from django.db.models import Avg

from apps.masters.models import SupplierEvaluation


def get_supplier_rating_summary(supplier):
    """仕入先の評価平均を取得する。"""
    evals = SupplierEvaluation.unscoped.filter(supplier=supplier)
    if not evals.exists():
        return None

    avg = evals.aggregate(
        price=Avg("price_rating"),
        delivery=Avg("delivery_rating"),
        quality=Avg("quality_rating"),
    )
    overall = round(
        (avg["price"] + avg["delivery"] + avg["quality"]) / 3, 1
    )
    return {
        "price": round(avg["price"], 1),
        "delivery": round(avg["delivery"], 1),
        "quality": round(avg["quality"], 1),
        "overall": overall,
        "count": evals.count(),
    }


def get_customer_site_history(customer):
    """得意先の現場一覧（取引履歴）を取得する。"""
    return customer.sites.order_by("-created_at")
