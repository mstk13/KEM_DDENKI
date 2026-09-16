"""積算案件の結果（受注・失注）を確定する（ADR-0076）。

入札案件 → 積算案件 → 現場管理 という流れの、最後の切り替え。

受注したら現場を受注済にして現場管理へ渡す。現場は積算開始の時点で
積算中として作ってあるので、ここで作り直さない（ADR-0031。案件は現場を
中心に束ねる）。

失注したら、誰にいくらで負けたかを競合ごとに残す。差額は保存せず
表示のたびに引くので、積算をやり直して応札額が動いても食い違わない。
"""
from __future__ import annotations

import datetime

from django.db import transaction

from apps.estimation.models import EstimationProject


def _sync_bid_status(project: EstimationProject, status) -> None:
    """引っ越し元の入札案件にも結果を反映する。

    入札案件は「積算中」のまま残っている。結果を書き戻さないと、
    入札ダッシュボードの受注率が積算に移した案件を数え落とす。
    """
    bid = project.bid_project
    if bid is None or bid.status == status:
        return
    bid.status = status
    bid.save(update_fields=["status", "updated_at"])


@transaction.atomic
def mark_won(project: EstimationProject, award_amount=None, decided_on=None,
             created_by=None):
    """積算案件を受注にし、現場を受注済にして現場管理へ渡す。

    Returns:
        (Site, created)。created は現場を新しく作ったとき True。
        入札案件を経ていない案件で現場が無ければ、ここで作る。
    """
    from apps.bids.services import apply_won_bid_to_site, create_site_from_won_bid
    from apps.sites.models import Site

    site = project.site
    created = False

    if site is None and project.bid_project is not None:
        # 入札から来た案件。入札側の値を使って現場を起こす
        site = create_site_from_won_bid(project.bid_project, created_by=created_by)
        created = True
    elif site is None:
        # 入札を経ない案件（民間の相対見積など）。積算案件の値で起こす
        site = Site.unscoped.create(  # unscoped: company を明示指定
            company=project.company,
            code=f"EST{project.pk}",
            name=project.name,
            address="",
            status=Site.Status.ORDERED,
            contract_amount=award_amount or project.bid_amount or 0,
            customer=project.orderer.customer,
            created_by=created_by,
        )
        created = True
    elif project.bid_project is not None:
        apply_won_bid_to_site(site, project.bid_project)
    elif site.status == Site.Status.ESTIMATING:
        site.status = Site.Status.ORDERED
        site.save(update_fields=["status", "updated_at"])

    # 落札額を入れた場合は現場の受注金額にも通す。
    # 現場側で既に手で入れてあるときは触らない（画面で入れた値を優先）。
    if award_amount is not None and not site.contract_amount:
        site.contract_amount = award_amount
        site.save(update_fields=["contract_amount", "updated_at"])

    project.site = site
    project.status = EstimationProject.Status.WON
    project.decided_on = decided_on or datetime.date.today()
    if award_amount is not None:
        project.award_amount = award_amount
    project.save(update_fields=[
        "site", "status", "decided_on", "award_amount", "updated_at",
    ])

    from apps.bids.models import BidProject
    _sync_bid_status(project, BidProject.Status.WON)

    return site, created


@transaction.atomic
def mark_lost(project: EstimationProject, reason="", note="", decided_on=None):
    """積算案件を失注にする。競合は EstimationCompetitor 側で別に記録する。

    積算中として作った現場は中止にする。受注していない現場が施工の一覧に
    残り続けると、稼働中の現場を数えるときに紛れ込むため。
    施工中より先に進んでいる現場は触らない（あり得ないが、戻さない）。
    """
    from apps.sites.models import Site

    project.status = EstimationProject.Status.LOST
    project.lost_reason = reason or ""
    project.lost_note = note or ""
    project.decided_on = decided_on or datetime.date.today()
    project.save(update_fields=[
        "status", "lost_reason", "lost_note", "decided_on", "updated_at",
    ])

    site = project.site
    if site is not None and site.status == Site.Status.ESTIMATING:
        site.status = Site.Status.CANCELLED
        site.save(update_fields=["status", "updated_at"])

    from apps.bids.models import BidProject
    _sync_bid_status(project, BidProject.Status.LOST)

    return project
