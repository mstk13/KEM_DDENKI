"""営業管理のビジネスロジック。

業界別集計、ダッシュボード、AI抽出を担う。
将来の DRF API 移行時にもそのまま使える。
"""

from django.db.models import Count, Q

from apps.sales.models import SalesVisit


def get_dashboard_stats(company):
    """営業ダッシュボードの集計データ。

    Returns:
        {
            "total": 全件数,
            "this_month": 今月の件数,
            "needs_action": 対応が必要な件数,
            "by_industry": [{"industry": "...", "count": N}, ...],
            "by_status": [{"status": "...", "count": N}, ...],
        }
    """
    from datetime import date

    visits = SalesVisit.unscoped.filter(company=company)
    today = date.today()

    total = visits.count()
    this_month = visits.filter(
        visit_date__year=today.year,
        visit_date__month=today.month,
    ).count()
    needs_action = visits.filter(
        status__in=[SalesVisit.Status.CONFIRMED, SalesVisit.Status.IN_PROGRESS],
    ).count()

    by_industry = list(
        visits.values("industry")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    by_status = list(
        visits.values("status")
        .annotate(count=Count("id"))
        .order_by("status")
    )

    return {
        "total": total,
        "this_month": this_month,
        "needs_action": needs_action,
        "by_industry": by_industry,
        "by_status": by_status,
    }


def get_companies_by_industry(company, industry):
    """業界ごとの会社一覧（重複排除）。"""
    visits = SalesVisit.unscoped.filter(
        company=company,
        industry=industry,
    ).values("company_name").annotate(
        count=Count("id"),
    ).order_by("company_name")

    return list(visits)


def search_visits(company, q="", industry="", status=""):
    """営業記録を検索する。"""
    qs = SalesVisit.unscoped.filter(company=company)

    if q:
        qs = qs.filter(
            Q(company_name__icontains=q)
            | Q(rep_name__icontains=q)
            | Q(sales_content__icontains=q)
        )
    if industry:
        qs = qs.filter(industry=industry)
    if status:
        qs = qs.filter(status=status)

    return qs.order_by("-visit_date", "-created_at")
