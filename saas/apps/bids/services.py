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


# ===================================================================
# 入札案件自動取得
# ===================================================================


def run_scrape(target, company):
    """1つの ScrapeTarget に対してスクレイピングを実行する。

    Returns:
        {"new": int, "skipped": int, "errors": list[str]}
    """
    import logging

    from django.utils import timezone

    # レジストリからスクレイパーを取得（import時に各モジュールが登録される）
    from apps.bids.scrapers import get_scraper
    from apps.bids.scrapers import shigaku, mod_msdf, mod_gsdf, mod_asdf  # noqa: F401
    from apps.bids.scrapers import kanagawa_thk, kanagawa_ebid, kanagawa_swf  # noqa: F401
    from apps.bids.scrapers import npb, geps  # noqa: F401

    logger = logging.getLogger(__name__)

    scraper = get_scraper(target.site_key)
    if not scraper:
        return {"new": 0, "skipped": 0, "errors": [f"未対応のsite_key: {target.site_key}"]}

    try:
        bid_infos = scraper.scrape()
    except Exception as e:
        logger.error(f"[{target.site_key}] スクレイプエラー: {e}")
        target.error_count += 1
        target.last_error = str(e)[:500]
        target.last_scraped_at = timezone.now()
        target.save(update_fields=[
            "error_count", "last_error", "last_scraped_at", "updated_at",
        ])
        return {"new": 0, "skipped": 0, "errors": [str(e)]}

    new_count = 0
    skipped = 0
    errors = []

    for info in bid_infos:
        # 工事種別フィルタ
        if target.category_filter:
            filters = [f.strip() for f in target.category_filter.split(",")]
            if info.category and not any(f in info.category for f in filters):
                skipped += 1
                continue

        # 重複チェック: source_url で判定
        if info.source_url:
            exists = BidProject.unscoped.filter(  # unscoped: company を明示指定
                company=company,
                source_url=info.source_url,
            ).exists()
            if exists:
                skipped += 1
                continue

        # タイトル+発注者でも補助的に重複チェック
        if info.title:
            exists = BidProject.unscoped.filter(  # unscoped: company を明示指定
                company=company,
                title=info.title,
                client=info.client,
            ).exists()
            if exists:
                skipped += 1
                continue

        try:
            BidProject.unscoped.create(  # unscoped: company を明示指定
                company=company,
                title=info.title,
                client=info.client,
                region=info.region or target.region,
                category=info.category,
                deadline=info.deadline,
                budget=info.budget or 0,
                source_type=BidProject.SourceType.SCRAPING,
                source_url=info.source_url,
                status=BidProject.Status.NEW,
            )
            new_count += 1
        except Exception as e:
            errors.append(f"{info.title}: {e}")

    # ターゲットの状態更新
    target.last_scraped_at = timezone.now()
    target.error_count = 0
    target.last_error = ""
    target.last_result = f"新規{new_count}件, スキップ{skipped}件"
    if errors:
        target.last_result += f", エラー{len(errors)}件"
    target.save(update_fields=[
        "last_scraped_at", "error_count", "last_error",
        "last_result", "updated_at",
    ])

    return {"new": new_count, "skipped": skipped, "errors": errors}


def run_all_scrapes(company):
    """全アクティブターゲットをスクレイピングする。

    Returns:
        {"total_new": int, "targets_processed": int, "errors": list[str]}
    """
    from django.utils import timezone

    from apps.bids.models import ScrapeTarget

    targets = ScrapeTarget.unscoped.filter(  # unscoped: company を明示指定
        company=company,
        is_active=True,
    )

    total_new = 0
    processed = 0
    all_errors = []

    for target in targets:
        # 巡回間隔チェック
        if target.last_scraped_at:
            from datetime import timedelta
            next_scrape = target.last_scraped_at + timedelta(
                hours=target.scrape_interval_hours,
            )
            if timezone.now() < next_scrape:
                continue

        result = run_scrape(target, company)
        total_new += result["new"]
        processed += 1
        all_errors.extend(result["errors"])

    # 新着があれば通知
    if total_new > 0:
        _notify_new_bids(company, total_new)

    return {
        "total_new": total_new,
        "targets_processed": processed,
        "errors": all_errors,
    }


def _notify_new_bids(company, count):
    """新着入札案件を全社員に通知する。"""
    from apps.accounts.models import User
    from apps.notifications.models import Notification
    from apps.notifications.services import notify_multiple

    # 直近の新着案件タイトルを取得（通知本文用）
    recent = BidProject.unscoped.filter(  # unscoped: company を明示指定
        company=company,
        source_type=BidProject.SourceType.SCRAPING,
        status=BidProject.Status.NEW,
    ).order_by("-created_at")[:5]

    body_lines = [f"- {p.title}" for p in recent]
    if count > 5:
        body_lines.append(f"  ...他 {count - 5}件")
    body = "\n".join(body_lines)

    recipients = User.objects.filter(
        company=company, is_active=True,
    )
    notify_multiple(
        company=company,
        recipients=recipients,
        title=f"新着入札案件: {count}件",
        body=body,
        level=Notification.Level.INFO,
        module=Notification.Module.BIDS,
        reference_url="/bids/?status=new",
    )
