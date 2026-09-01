"""入札管理のビジネスロジック。

落札→現場自動登録、ダッシュボード集計、期限アラートを担う。
将来の DRF API 移行時にもそのまま使える。
"""


from django.db.models import Count, Q, Sum

from apps.bids.models import BidProject


def create_site_from_won_bid(bid_project, created_by=None):
    """落札した案件から現場を自動作成する。

    Returns:
        Site インスタンス
    """
    from apps.sites.models import Site

    site = Site.unscoped.create(
        company=bid_project.company,
        code=f"BID-{bid_project.pk}",
        name=bid_project.title,
        address="",
        status=Site.Status.ORDERED,
        contract_amount=bid_project.our_bid_amount or bid_project.budget,
        created_by=created_by,
    )

    # 顧客をリンク
    if bid_project.client_ref:
        site.customer = bid_project.client_ref
        site.save(update_fields=["customer"])

    return site


def mark_as_won(bid_project, created_by=None):
    """案件を落札にし、現場を自動作成する。"""
    bid_project.status = BidProject.Status.WON
    bid_project.save(update_fields=["status"])

    site = create_site_from_won_bid(bid_project, created_by=created_by)

    # 通知
    from apps.accounts.models import User
    from apps.notifications.models import Notification
    from apps.notifications.services import notify_multiple

    recipients = User.objects.filter(
        company=bid_project.company, is_active=True,
    )
    notify_multiple(
        company=bid_project.company,
        recipients=recipients,
        title=f"🎉 {bid_project.title} を落札しました",
        body=f"現場「{site.name}」が自動作成されました。",
        level=Notification.Level.INFO,
        module=Notification.Module.BIDS,
        reference_url=f"/sites/{site.pk}/",
    )

    return site


def start_estimation(bid_project, created_by=None):
    """案件を見積中にし、現場を自動作成する。"""
    from apps.sites.models import Site

    bid_project.status = BidProject.Status.CONSIDERING
    bid_project.save(update_fields=["status"])

    site = Site.unscoped.create(
        company=bid_project.company,
        code=f"EST-{bid_project.pk}",
        name=bid_project.title,
        address="",
        status=Site.Status.ESTIMATING,
        contract_amount=bid_project.budget,
        created_by=created_by,
    )

    if bid_project.client_ref:
        site.customer = bid_project.client_ref
        site.save(update_fields=["customer"])

    return site


def get_dashboard_stats(company):
    """入札ダッシュボードの集計データを取得する。

    Returns:
        {
            "total_count": 全案件数,
            "won_count": 落札数,
            "lost_count": 失注数,
            "win_rate": 受注率(%),
            "total_won_amount": 受注金額合計,
            "by_status": [{"status": "...", "count": N}, ...],
            "by_region": [{"region": "...", "count": N}, ...],
            "by_month": [{"month": "2026-08", "count": N, "won": N}, ...],
        }
    """
    projects = BidProject.unscoped.filter(company=company)

    total = projects.count()
    won = projects.filter(status=BidProject.Status.WON).count()
    lost = projects.filter(status=BidProject.Status.LOST).count()
    decided = won + lost
    win_rate = round(won / decided * 100, 1) if decided > 0 else 0

    total_won_amount = (
        projects.filter(status=BidProject.Status.WON)
        .aggregate(t=Sum("our_bid_amount"))["t"]
        or 0
    )

    by_status = list(
        projects.values("status")
        .annotate(count=Count("id"))
        .order_by("status")
    )

    by_region = list(
        projects.exclude(region="")
        .values("region")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    from django.db.models.functions import TruncMonth

    by_month = list(
        projects
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(
            count=Count("id"),
            won=Count("id", filter=Q(status=BidProject.Status.WON)),
        )
        .order_by("month")
    )
    for item in by_month:
        item["month"] = item["month"].strftime("%Y-%m")

    return {
        "total_count": total,
        "won_count": won,
        "lost_count": lost,
        "win_rate": win_rate,
        "total_won_amount": total_won_amount,
        "by_status": by_status,
        "by_region": by_region,
        "by_month": by_month,
    }
