"""同じ日に同じ人の日報が二重に入るのを止める（ADR-0079）。

日報は「現場・作業員・日付・工種」で一意なので、同じ人が同じ日に別の現場や
別の工種で登録することはできてしまう。1日に2現場へ行く日もあるので禁止はできないが、
うっかり二重に書いた場合と見分けが付かない。

そこで保存の前に「同じ日・同じ人（同姓同名を含む）の日報」を探し、
あれば画面に赤字で出して、既にある日報を見せたうえで
「このまま登録する」か「既にある日報を開く」かを選んでもらう。

同姓同名まで見るのは、作業員マスタに同じ人が二重に登録されていることがあるため。
"""

from apps.reports.models import DailyReport


def find_duplicate_reports(company, workers, report_date, *, exclude_pk=None):
    """同じ日・同じ人の日報を探す。

    Args:
        company: 会社
        workers: これから日報を作る作業員（Worker の並び）
        report_date: 日報の日付
        exclude_pk: 編集中の日報。自分自身は重複に数えない

    Returns:
        [{"worker": Worker, "reports": [DailyReport, ...]}, ...]
        重複が無ければ空。並びは workers の順。
    """
    if not report_date or not workers:
        return []

    names = {(w.name or "").strip() for w in workers if (w.name or "").strip()}
    pks = {w.pk for w in workers}

    # unscoped: 会社を明示して絞る。この関数は画面からもコマンドからも呼ぶため。
    qs = DailyReport.unscoped.filter(
        company=company, report_date=report_date,
    ).select_related("site", "work_type", "worker")
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    existing = [
        report for report in qs
        if report.worker_id in pks or (report.worker.name or "").strip() in names
    ]
    if not existing:
        return []

    found = []
    for worker in workers:
        name = (worker.name or "").strip()
        mine = [
            report for report in existing
            if report.worker_id == worker.pk or (report.worker.name or "").strip() == name
        ]
        if mine:
            found.append({"worker": worker, "reports": mine})
    return found
