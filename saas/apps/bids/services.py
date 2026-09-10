"""入札管理のビジネスロジック。

落札→現場自動登録、ダッシュボード集計、期限アラートを担う。
将来の DRF API 移行時にもそのまま使える。
"""


from django.db import transaction
from django.db.models import Count, Q, Sum

from apps.bids.models import BidProject, SkippedBid, is_excluded_category


def _lock_bid(bid_project):
    """案件の行をロックして状態と現場を読み直す。

    二度押しや同時操作で、同じ案件から現場が2つできないようにする。
    transaction.atomic() の中で呼ぶこと。
    """
    bid_project.refresh_from_db(
        # unscoped: 呼び出し元が取得済みの案件を読み直すだけ
        from_queryset=BidProject.unscoped.select_for_update(),
        fields=["status", "site"],
    )


def create_site_from_won_bid(bid_project, created_by=None):
    """落札した案件から現場を自動作成する。

    Returns:
        Site インスタンス
    """
    from apps.sites.models import Site

    return Site.unscoped.create(  # unscoped: company を明示指定
        company=bid_project.company,
        code=f"BID-{bid_project.pk}",
        name=bid_project.title,
        address="",
        status=Site.Status.ORDERED,
        contract_amount=bid_project.our_bid_amount or bid_project.budget,
        customer=bid_project.client_ref,
        created_by=created_by,
    )


def apply_won_bid_to_site(site, bid_project):
    """登録済みの現場に落札を反映する。

    状態は見積中のときだけ受注済に進める（施工中などを戻さない）。
    受注金額・顧客は空のときだけ埋め、現場コードや画面で入れた値は変えない。
    """
    from apps.sites.models import Site

    changed = []
    if site.status == Site.Status.ESTIMATING:
        site.status = Site.Status.ORDERED
        changed.append("status")
    amount = bid_project.our_bid_amount or bid_project.budget
    if not site.contract_amount and amount:
        site.contract_amount = amount
        changed.append("contract_amount")
    if site.customer_id is None and bid_project.client_ref_id:
        site.customer_id = bid_project.client_ref_id
        changed.append("customer")
    if changed:
        site.save(update_fields=[*changed, "updated_at"])


def mark_as_won(bid_project, created_by=None):
    """案件を落札にし、現場を受注済にする。

    積算開始で現場ができていればそれを使い、無ければ作る（ADR-0031）。
    何度呼んでも現場は1つで、通知は落札に変わったときだけ出す。

    Returns:
        (Site, created)。created は現場を新しく作ったとき True
    """
    with transaction.atomic():
        _lock_bid(bid_project)
        newly_won = bid_project.status != BidProject.Status.WON

        created = bid_project.site_id is None
        if created:
            site = create_site_from_won_bid(bid_project, created_by=created_by)
        else:
            site = bid_project.site
            apply_won_bid_to_site(site, bid_project)

        bid_project.status = BidProject.Status.WON
        bid_project.site = site
        bid_project.save(update_fields=["status", "site", "updated_at"])

        if newly_won:
            _notify_won(bid_project, site, created)

    return site, created


def _notify_won(bid_project, site, created):
    """落札を全社員に通知する。"""
    from apps.accounts.models import User
    from apps.notifications.models import Notification
    from apps.notifications.services import notify_multiple

    recipients = User.objects.filter(
        company=bid_project.company, is_active=True,
    )
    if created:
        body = f"現場「{site.name}」が自動作成されました。"
    else:
        body = f"登録済みの現場「{site.name}」に落札を反映しました。"
    notify_multiple(
        company=bid_project.company,
        recipients=recipients,
        title=f"🎉 {bid_project.title} を落札しました",
        body=body,
        level=Notification.Level.INFO,
        module=Notification.Module.BIDS,
        reference_url=f"/sites/{site.pk}/",
    )


def start_estimation(bid_project, created_by=None):
    """案件を検討中にし、見積中の現場を用意する。

    現場が既にあればそれを使い、作り直さない（ADR-0031）。何度呼んでも現場は1つ。

    Returns:
        (Site, created)。created は現場を新しく作ったとき True
    """
    from apps.sites.models import Site

    with transaction.atomic():
        _lock_bid(bid_project)

        created = bid_project.site_id is None
        if created:
            site = Site.unscoped.create(  # unscoped: company を明示指定
                company=bid_project.company,
                code=f"EST-{bid_project.pk}",
                name=bid_project.title,
                address="",
                status=Site.Status.ESTIMATING,
                contract_amount=bid_project.budget,
                customer=bid_project.client_ref,
                created_by=created_by,
            )
        else:
            site = bid_project.site

        bid_project.status = BidProject.Status.CONSIDERING
        bid_project.site = site
        bid_project.save(update_fields=["status", "site", "updated_at"])

    return site, created


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
    ("document_urls", None),
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
        if isinstance(value, list):
            # document_urls はスクレイパーがリストで返す。1行1URLで持つ
            value = "\n".join(value)
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


def announcement_candidates(project) -> list[str]:
    """公告として読みに行くURLを、公告らしい順に返す。

    1案件に複数の公開文書がぶら下がり、先頭が公告とは限らない。
    実際「立川防災合同庁舎（２６）電気設備改修工事」は先頭が
    「技術資料収集に係る掲示」で、しかも文字が読めないPDFだった。
    """
    from apps.bids.announcement import alternate_urls

    urls = [u.strip() for u in (project.document_urls or "").splitlines() if u.strip()]
    if project.source_url and project.source_url not in urls:
        urls.insert(0, project.source_url)

    # 案内されているホストが引けない発注機関がある。代替URLを後ろに足す。
    # 読めたURLが情報源として保存されるので、画面のリンクも生きたものになる。
    for url in list(urls):
        urls.extend(alt for alt in alternate_urls(url) if alt not in urls)
    return urls


def _extract_garbled_with_llm(project, garbled_urls):
    """(cid) 化して読めない公告PDFを Claude に読ませる。

    Returns:
        (result, used_url)。読めなければ (None, "")。
    """
    import logging

    from apps.bids.announcement import fetch_document
    from apps.bids.announcement_llm import extract_with_llm, is_available

    logger = logging.getLogger(__name__)

    if not is_available():
        return None, ""

    for url in garbled_urls:
        data = fetch_document(url)
        result = extract_with_llm(data, company=project.company)
        if result and (result["work_outline"] or result["requirements"]):
            logger.info(
                "文字が読めない公告をLLMで取り込みました: %s (%s)",
                project.title[:30], url,
            )
            return result, url
    return None, ""


def fill_announcement(project) -> bool:
    """1案件の公開文書から工事概要・参加要件を取り込む。

    候補URLを順に試し、要件が読めたものを情報源URLにする。
    画面で書き換えた内容を消さないよう、空いている項目だけを埋める。
    埋まれば True。
    """
    import logging

    from apps.bids.announcement import extract_from_url

    logger = logging.getLogger(__name__)

    if project.work_outline and project.requirements:
        return False

    candidates = announcement_candidates(project)
    if not candidates:
        return False

    result = None
    used_url = ""
    garbled_urls = []
    for url in candidates:
        candidate = extract_from_url(url)
        if candidate["garbled"]:
            garbled_urls.append(url)
        if candidate["work_outline"] or candidate["requirements"]:
            result, used_url = candidate, url
            break

    if result is None and garbled_urls:
        # 文字が (cid) 化していて決定論的には読めないPDF。
        # ここだけ Claude に読ませる（費用と月間予算のチェックは呼び先が行う）。
        result, used_url = _extract_garbled_with_llm(project, garbled_urls)

    if result is None:
        if garbled_urls:
            logger.info(
                "公告PDFの文字が読めないため取り込めません: %s (%s)",
                project.title, garbled_urls[0],
            )
        return False

    changed = []
    if used_url and project.source_url != used_url:
        # 実際に要件が読めた文書を情報源として残す
        project.source_url = used_url[:500]
        changed.append("source_url")
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
    if result.get("required_issuer_type") and not project.required_issuer_type:
        project.required_issuer_type = result["required_issuer_type"]
        changed.append("required_issuer_type")
    if result.get("required_category") and not project.required_category:
        project.required_category = result["required_category"]
        changed.append("required_category")
    if result.get("bid_schedule") and not project.bid_schedule:
        project.bid_schedule = result["bid_schedule"]
        changed.append("bid_schedule")
    if result.get("bid_deadline") and not project.deadline:
        from datetime import datetime as _dt
        try:
            project.deadline = _dt.fromisoformat(result["bid_deadline"])
        except (ValueError, TypeError):
            pass
        else:
            changed.append("deadline")

    if not changed:
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
        elif target.site_key.startswith(("msdf_", "gsdf_", "asdf_")):
            # 防衛省基地スクレイパー（Playwright + Cloudflare突破）
            from apps.bids.scrapers.mod_base import scrape_mod_base
            raw_results = scrape_mod_base(target)
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
    ineligible = 0  # 資格を満たさず見送った件数（only_eligible のとき）
    unknown = 0  # 公告が読めず判定できなかった件数（only_eligible のとき）
    errors = []
    touched = []  # 公告PDFを見に行く対象（このターゲットで新規・更新した案件）
    qualifications = None

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

        # 件名フィルタ: 明らかに公告でないものを除外
        _skip_titles = (
            "仕様書", "低入札", "様式", "押印", "発注予定", "月分",
            "契約結果", "落札結果", "結果一覧", "見積結果", "売払",
            "共通仕様", "提出資料", "実施要領", "心得", "規格表",
            "施策", "説明資料", "同等品申請", "お知らせ", "事務連絡",
            "参加申込受付", "入札要領", "入札関係", "取消",
            "不用パソコン", "鉄屑", "廃油",
        )
        if any(kw in title for kw in _skip_titles):
            excluded += 1
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

        # 資格を満たす案件だけ登録する設定なら、登録前に公告を読んで判定する。
        # 判定できない（公告が読めない・要件が書かれていない）案件は見送る。
        if target.only_eligible:
            if qualifications is None:
                from apps.bids.models import Qualification

                # unscoped: company を明示指定
                qualifications = list(Qualification.unscoped.filter(company=company))
            verdict = _judge_before_register(rec, company, target, qualifications)
            if verdict is not True:
                if verdict is False:
                    ineligible += 1
                else:
                    unknown += 1
                _record_skipped(rec, company, target, verdict)
                continue
            # 判定で公告の種類・業種に置き換わっていれば、それを登録に使う
            category = rec.get("category", category)
            # 以前は見送っていた案件が（資格の追加などで）通ったら記録を消す
            if source_url:
                SkippedBid.unscoped.filter(company=company, source_url=source_url).delete()

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
                document_urls="\n".join(rec.get("document_urls") or []),
                summary=rec.get("summary", ""),
                status=BidProject.Status.NEW,
                required_grade=rec.get("required_grade", ""),
                required_category=rec.get("required_category", ""),
                required_issuer_type=rec.get("required_issuer_type", ""),
                required_grades=rec.get("required_grades", ""),
                required_score=rec.get("required_score"),
                work_outline=rec.get("work_outline", ""),
                requirements=rec.get("requirements", ""),
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
    if ineligible:
        target.last_result += f", 資格不足{ineligible}件"
    if unknown:
        target.last_result += f", 判定不能{unknown}件"
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
        "ineligible": ineligible,
        "unknown": unknown,
        "outlined": outlined,
        "errors": errors,
    }


def _judge_before_register(rec, company, target, qualifications):
    """取り込み前に公告を読み、自社の資格で参加できるかを判定する。

    Returns:
        True  … 参加できる（rec に公告の要件を書き足す）
        False … 資格を満たさない
        None  … 判定できない（公告が読めない・要件が書かれていない）
    """
    import logging

    from apps.bids.announcement import extract_from_url
    from apps.bids.qualification import check_project

    logger = logging.getLogger(__name__)

    url = rec.get("source_url", "")
    if not url:
        return None
    try:
        info = extract_from_url(url)
    except Exception as e:  # noqa: BLE001 - 相手サイト起因の失敗は判定不能として扱う
        logger.info("公告を読めないため判定不能: %s (%s)", rec.get("title", "")[:30], e)
        return None
    if info.get("garbled") or not info.get("required_issuer_type"):
        return None

    for key in (
        "required_issuer_type", "required_category", "required_grade",
        "required_grades", "required_score", "work_outline", "requirements",
    ):
        if info.get(key):
            rec[key] = info[key]
    # スクレイパーが「物品・役務」のような大枠しか付けていなければ、公告の業種で置き換える
    if info.get("required_category") and (
        not rec.get("category") or rec.get("category") == "物品・役務"
    ):
        rec["category"] = info["required_category"]

    probe = BidProject(  # 保存しない。判定に使う項目だけ持たせる
        company=company,
        title=rec.get("title", ""),
        client=rec.get("client", ""),
        category=rec.get("category", ""),
        required_issuer_type=rec.get("required_issuer_type", ""),
        required_category=rec.get("required_category", ""),
        required_grade=rec.get("required_grade", ""),
        required_grades=rec.get("required_grades", ""),
        required_score=rec.get("required_score"),
    )
    verdict = check_project(probe, qualifications)
    logger.info(
        "資格判定 %s: %s → %s", "参加可" if verdict["eligible"] else "見送り",
        rec.get("title", "")[:30], verdict["reason"][:60],
    )
    rec["_judge_reason"] = verdict["reason"]
    return verdict["eligible"]


def _record_skipped(rec, company, target, verdict):
    """見送った案件を理由付きで残す（同じ情報源URLなら上書き）。"""
    source_url = rec.get("source_url", "")
    if not source_url:
        return
    reason = rec.get("_judge_reason") or (
        "公告に資格要件が見つからないか、公告が読めないため判定できません。"
    )
    SkippedBid.unscoped.update_or_create(  # unscoped: company を明示指定
        company=company, source_url=source_url[:500],
        defaults={
            "target": target,
            "title": rec.get("title", "")[:300],
            "client": rec.get("client", "")[:200],
            "category": rec.get("category", "")[:100],
            "deadline": rec.get("deadline"),
            "verdict": (
                SkippedBid.Verdict.INELIGIBLE if verdict is False
                else SkippedBid.Verdict.UNKNOWN
            ),
            "reason": reason,
            "required_issuer_type": rec.get("required_issuer_type", "")[:200],
            "required_category": rec.get("required_category", "")[:100],
            "required_grade": rec.get("required_grade", "")[:10],
            "required_grades": rec.get("required_grades", "")[:20],
            "required_score": rec.get("required_score"),
            "requirements": rec.get("requirements", ""),
        },
    )


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
