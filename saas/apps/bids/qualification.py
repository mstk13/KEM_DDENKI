"""入札案件と自社資格の照合ユーティリティ。"""
from apps.bids.models import Qualification


def check_qualifications_for_projects(projects, company):
    """複数案件の受注可否を一括判定する。

    Args:
        projects: BidProject の QuerySet またはリスト
        company: Company インスタンス

    Returns:
        dict: {project.pk: {"eligible": bool|None, "reason": str, "matched_qual": obj|None}}
    """
    # 自社の有効な資格を一括取得（N+1 防止）
    qualifications = list(
        Qualification.unscoped.filter(company=company)
    )

    results = {}
    for project in projects:
        results[project.pk] = project.check_qualification(qualifications)

    return results
