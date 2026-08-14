"""入札管理のビジネスロジック。

落札→現場自動登録、ダッシュボード集計、期限アラートを担う。
将来の DRF API 移行時にもそのまま使える。
"""


from django.db.models import Count, Q, Sum

from apps.bids.models import BidProject, is_excluded_category


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


# 取り込み結果 → BidProject のフィールド。値の長さ上限も持つ。
_IMPORT_FIELDS = [
    ("agency_dept", 200),
    ("location", 400),
    ("category", 100),
    ("bid_method", 200),
    ("design_no", 100),
    ("electronic_bid", 50),
    ("source_url", 500),
    ("summary", None),
    ("required_grade", None),
    ("required_category", None),
    ("required_issuer_type", None),
    ("announced_on", None),
    ("opening_on", None),
    ("deadline", None),
    ("budget", None),
    ("region", None),
]


def find_existing_project(company, rec):
    """取り込み済みの同じ案件を探す。無ければ None。

    発注機関を「機関」と「担当部・事務所」に分けて保存するようにしたため、
    旧形式（`機関 ／ 担当部` を client に入れていた）で保存された案件とも
    突き合わせる。ここで取りこぼすと同じ案件が二重登録される。
    """
    source_url = rec.get("source_url", "")
    if source_url:
        hit = BidProject.unscoped.filter(  # unscoped: company を明示指定
            company=company, source_url=source_url,
        ).first()
        if hit:
            return hit

    title = rec.get("title", "")
    if not title:
        return None

    client = rec.get("client", "")
    agency_dept = rec.get("agency_dept", "")
    legacy_client = f"{client} ／ {agency_dept}" if agency_dept else client

    candidates = BidProject.unscoped.filter(  # unscoped: company を明示指定
        company=company, title=title,
    )
    for candidate in candidates:
        if candidate.client in ("", client, legacy_client):
            return candidate
    return None


def fill_missing_fields(project, rec, default_region=""):
    """既存案件の空いている項目だけを取り込み結果で埋める。

    画面で手直しした値を上書きしないよう、既に値がある項目には触らない。
    変更があれば True を返す。
    """
    changed = []

    # 旧形式の「機関 ／ 担当部」は、分割済みの値に置き換える
    client = rec.get("client", "")
    if client and "／" in project.client and project.client.startswith(client):
        project.client = client[:200]
        changed.append("client")

    for name, max_length in _IMPORT_FIELDS:
        value = rec.get(name)
        if name == "region":
            value = value or default_region
        if value in (None, "", 0):
            continue
        if getattr(project, name) not in (None, "", 0):
            continue
        if max_length and isinstance(value, str):
            value = value[:max_length]
        setattr(project, name, value)
        changed.append(name)

    if not changed:
        return False

    project.save(update_fields=[*changed, "updated_at"])
    return True


def fill_announcement(project) -> bool:
    """1案件の情報源URLから工事概要・参加要件を取り込む。

    画面で書き換えた内容を消さないよう、空いている項目だけを埋める。
    埋まれば True。
    """
    import logging

    from apps.bids.announcement import extract_from_url

    logger = logging.getLogger(__name__)

    if not project.source_url:
        return False
    if project.work_outline and project.requirements:
        return False

    result = extract_from_url(project.source_url)
    changed = []
    if result["work_outline"] and not project.work_outline:
        project.work_outline = result["work_outline"]
        changed.append("work_outline")
    if result["requirements"] and not project.requirements:
        project.requirements = result["requirements"]
        changed.append("requirements")
    if result["required_grade"] and not project.required_grade:
        project.required_grade = result["required_grade"]
        changed.append("required_grade")
    if result["required_grades"] and not project.required_grades:
        project.required_grades = result["required_grades"]
        changed.append("required_grades")
    if result["required_score"] and project.required_score is None:
        project.required_score = result["required_score"]
        changed.append("required_score")

    if not changed:
        if result["garbled"]:
            logger.info(
                "公告PDFの文字が読めないため取り込めません: %s (%s)",
                project.title, project.source_url,
            )
        return False

    project.save(update_fields=[*changed, "updated_at"])
    logger.info("公告から取り込み: %s → %s", project.title[:30], ", ".join(changed))
    return True


def fill_announcements(projects, limit=None) -> int:
    """複数案件の公告を順に取り込む。埋まった件数を返す。

    公告を取れなくても取り込み自体は成功として扱う。相手は官公庁サイトで、
    落ちていたり証明書が古かったりするのを案件取得の失敗にはしない。
    """
    import logging

    logger = logging.getLogger(__name__)

    filled = 0
    for i, project in enumerate(projects):
        if limit is not None and i >= limit:
            logger.info("公告の取り込みを%d件で打ち切りました", limit)
            break
        try:
            filled += bool(fill_announcement(project))
        except Exception as e:
            logger.warning("公告の取り込みに失敗: %s (%s)", project.title[:30], e)
    return filled


def run_scrape(target, company):
    """1つの ScrapeTarget に対してスクレイピングを実行する。

    site_key が 'ippi' または空の場合は i-ppi.jp スクレイパーを使用。
    それ以外は個別サイトスクレイパーを使用。

    Returns:
        {"new": int, "skipped": int, "errors": list[str]}
    """
    import logging

    from django.utils import timezone

    logger = logging.getLogger(__name__)

    # --- スクレイピング実行 ---
    try:
        if not target.site_key or target.site_key == "ippi":
            # i-ppi.jp スクレイパー（Playwright）
            from apps.bids.scraper import scrape_ippi
            raw_results = scrape_ippi(target)
        else:
            # 個別サイトスクレイパー（requests + BS4）
            from apps.bids.scrapers import (  # noqa: F401 レジストリ登録
                get_scraper,
                kanagawa_swf,
                kanagawa_thk,
                shigaku,
            )

            scraper = get_scraper(target.site_key)
            if not scraper:
                return {
                    "new": 0, "updated": 0, "skipped": 0, "excluded": 0, "outlined": 0,
                    "errors": [f"未対応: {target.site_key}"],
                }
            bid_infos = scraper.scrape()
            # BidInfo → dict に変換（i-ppi と同じ形式に統一）
            from apps.bids.scraper import _empty_record

            raw_results = []
            for b in bid_infos:
                rec = _empty_record()
                rec.update({
                    "title": b.title, "client": b.client, "region": b.region,
                    "category": b.category, "deadline": b.deadline,
                    "budget": int(b.budget) if b.budget else 0,
                    "source_url": b.source_url,
                })
                raw_results.append(rec)
    except Exception as e:
        logger.error(f"[{target.site_key or 'ippi'}] スクレイプエラー: {e}")
        target.error_count += 1
        target.last_error = str(e)[:500]
        target.last_scraped_at = timezone.now()
        target.save(update_fields=[
            "error_count", "last_error", "last_scraped_at", "updated_at",
        ])
        return {
            "new": 0, "updated": 0, "skipped": 0,
            "excluded": 0, "outlined": 0, "errors": [str(e)],
        }

    # --- 結果をBidProjectに登録 ---
    new_count = 0
    updated = 0
    skipped = 0
    excluded = 0
    errors = []
    touched = []  # 公告PDFを見に行く対象（このターゲットで新規・更新した案件）

    for rec in raw_results:
        title = rec.get("title", "")
        if not title:
            continue

        source_url = rec.get("source_url", "")
        client = rec.get("client", "")
        category = rec.get("category", "")

        # 取得対象外の工事種別（土木・舗装系）を落とす
        if is_excluded_category(category):
            excluded += 1
            logger.debug("対象外の工事種別のため除外: %s (%s)", title, category)
            continue

        # 工事種別フィルタ
        if target.category_filter:
            filters = [f.strip() for f in target.category_filter.split(",")]
            if category and not any(f in category for f in filters):
                skipped += 1
                continue

        # 既に取り込み済みなら、空いている項目だけ埋める。
        # 取得項目を増やしても既存案件は「重複」で弾かれ続けて永久に空のままになる。
        existing = find_existing_project(company, rec)
        if existing is not None:
            if fill_missing_fields(existing, rec, default_region=target.region):
                updated += 1
            else:
                skipped += 1
            touched.append(existing)
            continue

        try:
            project = BidProject.unscoped.create(  # unscoped: company を明示指定
                company=company,
                title=title[:300],
                client=client[:200],
                agency_dept=rec.get("agency_dept", "")[:200],
                region=rec.get("region", "") or target.region,
                location=rec.get("location", "")[:400],
                category=category[:100],
                bid_method=rec.get("bid_method", "")[:200],
                design_no=rec.get("design_no", "")[:100],
                electronic_bid=rec.get("electronic_bid", "")[:50],
                announced_on=rec.get("announced_on"),
                opening_on=rec.get("opening_on"),
                deadline=rec.get("deadline"),
                budget=rec.get("budget") or 0,
                source_type=BidProject.SourceType.SCRAPING,
                source_url=source_url[:500],
                summary=rec.get("summary", ""),
                status=BidProject.Status.NEW,
                required_grade=rec.get("required_grade", ""),
                required_category=rec.get("required_category", ""),
                required_issuer_type=rec.get("required_issuer_type", ""),
            )
            new_count += 1
            touched.append(project)
        except Exception as e:
            errors.append(f"{title}: {e}")

    # 公告PDFから工事概要・参加要件を取り込む（取れなくても取り込み自体は成功扱い）
    outlined = fill_announcements(touched)

    # ターゲットの状態更新
    target.last_scraped_at = timezone.now()
    target.error_count = 0
    target.last_error = ""
    target.last_result = f"新規{new_count}件, 更新{updated}件, スキップ{skipped}件"
    if outlined:
        target.last_result += f", 公告{outlined}件"
    if excluded:
        target.last_result += f", 対象外{excluded}件"
    if errors:
        target.last_result += f", エラー{len(errors)}件"
    target.save(update_fields=[
        "last_scraped_at", "error_count", "last_error",
        "last_result", "updated_at",
    ])

    return {
        "new": new_count,
        "updated": updated,
        "skipped": skipped,
        "excluded": excluded,
        "outlined": outlined,
        "errors": errors,
    }


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
