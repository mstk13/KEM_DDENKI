"""同じ日に同じ人の日報が二重に入るのを止める（ADR-0079・ADR-0100）。

日報は「現場・作業員・日付・工種」で一意なので、同じ人が同じ日に別の現場や
別の工種で登録することはできてしまう。うっかり二重に書いた場合と見分けが付かない。

そこで保存の前に「同じ日・同じ人（同姓同名を含む）の日報」を探す。

## 別の現場は「重複」ではない（ADR-0100）

**1日に2現場へ行く日は普通にある。** 午前は A 現場で4時間、午後は B 現場で4時間、
という書き方をしたいのに、赤字で「重複があります」と出て確認を1回挟まされると、
現場の人はエラーだと受け取って入力をやめてしまう。

そこで**現場が同じかどうかで分ける**。

| 既にある日報 | 扱い |
|---|---|
| **同じ現場** | これまでどおり「重複」として止め、確認してもらう |
| **別の現場だけ** | 止めない。その日の作業時間の内訳として見せる |

同じ現場・同じ工種は `unique_together` が弾くので、ここで止まるのは
「同じ現場の別工種」。同じ現場に1日2回書くのは、うっかりの可能性が高い。

同姓同名まで見るのは、作業員マスタに同じ人が二重に登録されていることがあるため。
"""

from decimal import Decimal

from apps.reports.models import DailyReport

# 1人1日の作業時間の上限。これを超える入力は打ち間違いとして弾く（ADR-0100）。
# 所定時間で切らないのは、残業も泊まり込みも実際にあるため。
MAX_DAILY_HOURS = 24


def format_hours(value) -> str:
    """作業時間を画面に出す形にする。8.00 → 8、8.50 → 8.5。

    小数第2位まで持つ値をそのまま出すと「8.00 時間」になって読みにくい。
    """
    text = f"{Decimal(str(value or 0)):f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _same_person(report, worker, names):
    name = (report.worker.name or "").strip()
    return report.worker_id == worker.pk or (name and name in names)


def _existing_reports(company, workers, report_date, exclude_pk=None):
    """同じ日・同じ人（同姓同名を含む）の日報。"""
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

    return [
        report for report in qs
        if report.worker_id in pks or (report.worker.name or "").strip() in names
    ]


def find_duplicate_reports(
    company, workers, report_date, *, site_name="", exclude_pk=None,
):
    """同じ日・同じ人の日報を探す。

    Args:
        company: 会社
        workers: これから日報を作る作業員（Worker の並び）
        report_date: 日報の日付
        site_name: これから書く日報の現場名。同じ現場かどうかの判定に使う
        exclude_pk: 編集中の日報。自分自身は重複に数えない

    Returns:
        [{"worker", "reports", "same_site_reports", "hours"}, ...]
        `same_site_reports` が空でなければ、うっかり二重の疑いがある（確認が要る）。
        `hours` はその日に既に入っている作業時間の合計。
        重複が無ければ空。並びは workers の順。
    """
    existing = _existing_reports(company, workers, report_date, exclude_pk)
    if not existing:
        return []

    wanted = (site_name or "").strip()
    names = {(w.name or "").strip() for w in workers if (w.name or "").strip()}

    found = []
    for worker in workers:
        mine = [r for r in existing if _same_person(r, worker, names)]
        if not mine:
            continue
        same_site = [
            r for r in mine if wanted and (r.site.name or "").strip() == wanted
        ]
        found.append({
            "worker": worker,
            "reports": mine,
            "same_site_reports": same_site,
            "hours": sum((r.work_hours or 0) for r in mine),
        })
    return found


def needs_confirmation(duplicates) -> bool:
    """確認を挟むかどうか。**同じ現場の日報があるときだけ。**

    別の現場しか無いときに止めないのは、1日2現場が普通にあるため（ADR-0100）。
    """
    return any(item["same_site_reports"] for item in duplicates)


def day_breakdown(company, reports):
    """保存した日報について、その人のその日の内訳を文にする（ADR-0100）。

    「午前A現場・午後B現場」のように分けて入れたとき、**分けた結果が
    そのとおり入ったか**を、一覧を開かずにその場で確かめられるようにする。

    Returns:
        ["電工太郎 さんの 9月10日 は合計 8.0 時間（A現場 4.0 / B現場 4.0）", ...]
        その日に1件しか無い人は出さない（分けていないので確かめることが無い）。
    """
    lines = []
    seen = set()
    for report in reports:
        key = (report.worker_id, report.report_date)
        if key in seen:
            continue
        seen.add(key)
        # unscoped: 会社を明示して絞る
        same_day = list(
            DailyReport.unscoped.filter(
                company=company, worker_id=report.worker_id,
                report_date=report.report_date,
            ).select_related("site").order_by("start_time", "pk"),
        )
        if len(same_day) < 2:
            continue
        total = sum((r.work_hours or 0) for r in same_day)
        detail = " / ".join(
            f"{r.site.name} {format_hours(r.work_hours)}" for r in same_day
        )
        day = report.report_date
        lines.append(
            f"{report.worker.name} さんの {day.month}月{day.day}日 は"
            f"合計 {format_hours(total)} 時間（{detail}）",
        )
    return lines
