"""入札案件から積算案件を起こす（ADR-0070）。

入札案件（bids.BidProject）で積算を始めると、ここが積算案件
（EstimationProject）と、その日程（EstimationPhase）を用意する。

日程は公告の手続き期限から起こす。入札公告には「申請書の提出期限」
「入札書の受領期限」「開札の日時」といった日付が並んでおり、
積算の段取りはこの期限から逆算して決まる。ゼロから打ち直す必要はない。

公告を取り直しても手で直した日程を潰さないよう、取り込みは
source_label（公告側の項目名）をキーにした1回限りとする。
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.estimation.models import EstimationPhase, EstimationProject, Orderer

# 公告の段階ごとのバーの色。積算の流れが一目で追えるよう、
# 手前（情報収集）を薄く、開札に近づくほど濃くする。
_STAGE_COLORS = {
    "入札説明書の入手": "#94a3b8",
    "質問受付": "#60a5fa",
    "参加申請": "#3b82f6",
    "見積提出": "#6366f1",
    "入札書提出": "#4f46e5",
    "開札・落札者決定": "#dc2626",
    "配置技術者の専任": "#0d9488",
}
_DEFAULT_COLOR = "#3b82f6"


def resolve_orderer(bid_project, created_by=None) -> Orderer:
    """入札案件の発注者に対応する発注機関を返す。無ければ作る。

    EstimationProject.orderer は必須（PROTECT）なので、引っ越しのたびに
    人手でマスタを選ばせると積算を始められない。公告の発注者名で引き当て、
    無ければ最低限の1件を作る。種別・積算体系は後から画面で直す前提の既定値。

    Orderer は (company, name) で一意なので、名前が同じものは1件に寄る。
    """
    name = (bid_project.client or "").strip() or "発注者未設定"
    # unscoped: company を明示指定して作るため
    orderer, _created = Orderer.unscoped.get_or_create(
        company=bid_project.company,
        name=name,
        defaults={
            "customer": bid_project.client_ref,
            "notes": "入札案件から自動作成。種別と積算体系を確認してください",
            "created_by": created_by,
        },
    )
    return orderer


def _phase_rows(bid_project) -> list[dict]:
    """公告の手続きスケジュールを、積算工程の行に変換する。

    日付の解釈（締切をバーに引き延ばす、案件ごとの手直しを当てる）は
    入札側の bids.gantt に既にある。二重に実装せず、その結果を borrow する。
    """
    from apps.bids.gantt import build_bid_gantt

    data = build_bid_gantt(bid_project)
    rows = []
    for idx, row in enumerate(data.get("rows") or []):
        start, end = row.get("start"), row.get("end")
        if not end:
            continue
        stage = row.get("stage") or row.get("label") or ""
        # 公告の日時は aware。「9月17日 正午」を日付にするとき UTC のまま
        # .date() を取ると前日になることがあるので、必ず現地時刻に直す。
        rows.append({
            "name": stage,
            "source_label": row.get("label") or stage,
            "start_date": timezone.localtime(start).date() if start else None,
            "end_date": timezone.localtime(end).date(),
            "sort_order": idx * 10,
            "color": _STAGE_COLORS.get(stage, _DEFAULT_COLOR),
            "memo": row.get("detail", "") or "",
        })
    return rows


def import_phases_from_bid(project: EstimationProject, bid_project, created_by=None) -> int:
    """公告の手続き期限を積算工程として取り込む。

    既に同じ公告項目から作った工程があれば飛ばす。日付を手で直したあとに
    もう一度取り込んでも、直した内容が上書きされないようにするため。

    Returns:
        新しく作った工程の件数
    """
    existing = set(
        # unscoped: company は project から引き継ぐので絞り込み済み
        EstimationPhase.unscoped.filter(project=project)
        .exclude(source_label="")
        .values_list("source_label", flat=True)
    )
    created = 0
    for row in _phase_rows(bid_project):
        if row["source_label"] in existing:
            continue
        EstimationPhase.unscoped.create(  # unscoped: company を明示指定
            company=project.company,
            project=project,
            created_by=created_by,
            progress=0,
            **row,
        )
        created += 1
    return created


def create_estimation_project_from_bid(bid_project, site=None, created_by=None):
    """入札案件に対応する積算案件を用意する。既にあればそれを返す。

    Returns:
        (EstimationProject, created)
    """
    with transaction.atomic():
        # unscoped: company を明示指定して引き当てるため
        existing = (
            EstimationProject.unscoped
            .filter(company=bid_project.company, bid_project=bid_project)
            .first()
        )
        if existing:
            if site is not None and existing.site_id is None:
                existing.site = site
                existing.save(update_fields=["site", "updated_at"])
            import_phases_from_bid(existing, bid_project, created_by=created_by)
            return existing, False

        project = EstimationProject.unscoped.create(  # unscoped: company を明示指定
            company=bid_project.company,
            created_by=created_by,
            name=bid_project.title,
            orderer=resolve_orderer(bid_project, created_by=created_by),
            site=site,
            bid_project=bid_project,
            status=EstimationProject.Status.ESTIMATING,
            bid_announcement_date=bid_project.announced_on,
            bid_opening_date=bid_project.opening_on,
            notes=bid_project.work_outline or "",
        )
        import_phases_from_bid(project, bid_project, created_by=created_by)
        return project, True
