"""工期管理のビジネスロジック。

ガントチャートデータ生成、配置カレンダーデータ生成、
テンプレートからの工程一括作成を担う。
将来の DRF API 移行時にもそのまま使える。
"""

import re
import unicodedata
from datetime import date, timedelta

from django.db.models import F, Prefetch, Q
from django.utils import timezone

from apps.schedules.models import Assignment, Milestone, Phase, PhaseTemplate

# 比較ガントで現場ごとに色を割り当てるためのパレット数。
# style.css の .gantt-site-0 〜 .gantt-site-7 と対応させている。
COMPARISON_COLOR_COUNT = 8

# ホームの現場カードに出す「その日の参加者」（ADR-0036）。
# 行き先（note）を現場名と突き合わせる出社予定の区分。出張も、行き先に現場名が
# 書いてあればその現場の参加者に数える。
MEMBER_PLAN_KINDS = ("site", "direct", "trip")
# 現場へ出ているとみなす区分。出張はその現場と一致したときだけ現場にいるとみなす。
ON_SITE_PLAN_KINDS = ("site", "direct")
# 出社予定が無く、配置だけで参加者になった人の表示。
ASSIGNED_LABEL = "配置"

_WHITESPACE = re.compile(r"\s+")


def _average_progress(phases):
    """工程リストの平均進捗（％）。工程がなければ0。"""
    phases = list(phases)
    if not phases:
        return 0
    return sum(p.progress for p in phases) // len(phases)


def _site_span(site, phases):
    """現場の工期。現場に工期未設定なら工程の最早・最遅から補う。"""
    if site.start_date and site.end_date:
        return site.start_date, site.end_date

    dated = [p for p in phases if p.start_date and p.end_date]
    if not dated:
        return None, None
    return (
        min(p.start_date for p in dated),
        max(p.end_date for p in dated),
    )


def get_gantt_data(company):
    """全現場のガントチャートデータを生成する（frappe-gantt用JSON）。

    Returns:
        [
            {
                "id": "site-1", "name": "A現場",
                "start": "2026-08-01", "end": "2026-10-31",
                "progress": 45, "custom_class": "bar-blue",
            },
            ...
        ]
    """
    from apps.sites.models import Site

    sites = Site.unscoped.filter(
        company=company,
        status__in=["in_progress", "ordered"],
    ).order_by("start_date")

    tasks = []
    for site in sites:
        if not site.start_date or not site.end_date:
            continue

        # 現場全体の平均進捗
        avg_progress = _average_progress(Phase.unscoped.filter(site=site))

        tasks.append({
            "id": f"site-{site.pk}",
            "name": site.name,
            "start": site.start_date.isoformat(),
            "end": site.end_date.isoformat(),
            "progress": avg_progress,
            "custom_class": "bar-blue",
        })

    return tasks


def get_comparison_gantt_data(company, site_ids=None, mode="site"):
    """複数現場を並べて比較するガントチャートデータを生成する。

    Args:
        company: 対象テナント
        site_ids: 比較対象の現場PKリスト。空なら施工中・受注済の現場を対象にする。
        mode: "site" は現場単位の工期のみ。"phase" は現場の下に工程を並べる。

    Returns:
        {
            "tasks":  frappe-gantt 用のタスクJSON,
            "legend": 現場と色の対応（凡例・比較表用）,
        }
    """
    from apps.sites.models import Site

    # unscoped: サービス層はリクエスト外（バッチ・将来のAPI）からも呼べるようにするため、
    # company を引数で受けて明示的に絞る。既存の get_gantt_data と同じ方針。
    sites = Site.unscoped.filter(company=company)
    if site_ids:
        sites = sites.filter(pk__in=site_ids)
    else:
        sites = sites.filter(status__in=["in_progress", "ordered"])
    sites = sites.order_by("start_date", "pk")

    tasks = []
    legend = []

    for idx, site in enumerate(sites):
        color_class = f"gantt-site-{idx % COMPARISON_COLOR_COUNT}"
        phases = list(Phase.unscoped.filter(site=site).order_by("sort_order"))
        start, end = _site_span(site, phases)

        legend.append({
            "site_id": site.pk,
            "name": site.name,
            "color_class": color_class,
            "start": start,
            "end": end,
            # 工期日数は開始日・終了日の両端を含めて数える（1日工事なら1日）。
            "days": (end - start).days + 1 if start and end else None,
            "progress": _average_progress(phases),
            "phase_count": len(phases),
        })

        if start and end:
            tasks.append({
                "id": f"site-{site.pk}",
                "name": site.name,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "progress": _average_progress(phases),
                "custom_class": f"{color_class} gantt-row-site",
            })

        if mode != "phase":
            continue

        for phase in phases:
            if not phase.start_date or not phase.end_date:
                continue
            tasks.append({
                # 現場名を付けないと、同名の工程がどの現場のものか区別できない。
                "id": f"phase-{phase.pk}",
                "name": f"{site.name} / {phase.name}",
                "start": phase.start_date.isoformat(),
                "end": phase.end_date.isoformat(),
                "progress": phase.progress,
                "custom_class": f"{color_class} gantt-row-phase",
            })

    return {"tasks": tasks, "legend": legend}


def get_site_gantt_data(site):
    """現場内の工程別ガントチャートデータ（frappe-gantt用JSON）。"""
    phases = Phase.unscoped.filter(site=site).order_by("sort_order")
    milestones = Milestone.unscoped.filter(site=site)

    tasks = []
    for phase in phases:
        if not phase.start_date or not phase.end_date:
            continue
        tasks.append({
            "id": f"phase-{phase.pk}",
            "name": phase.name,
            "start": phase.start_date.isoformat(),
            "end": phase.end_date.isoformat(),
            "progress": phase.progress,
            "custom_class": "bar-custom",
        })

    for ms in milestones:
        if not ms.target_date:
            continue
        tasks.append({
            "id": f"ms-{ms.pk}",
            "name": f"◆ {ms.name}",
            "start": ms.target_date.isoformat(),
            "end": ms.target_date.isoformat(),
            "progress": 100 if ms.completed else 0,
            "custom_class": "bar-milestone",
        })

    return tasks


def get_calendar_data(company, start_date, end_date):
    """配置カレンダーデータを生成する（FullCalendar用JSON）。

    Returns:
        [
            {
                "title": "田中太郎",
                "start": "2026-08-01", "end": "2026-08-05",
                "color": "#3b82f6", "extendedProps": {"site": "A現場"},
            },
            ...
        ]
    """
    assignments = Assignment.unscoped.filter(
        company=company,
        start_date__lte=end_date,
    ).filter(
        # end_dateがNULL（無期限）or end_date >= start_date
        **{"end_date__gte": start_date}
    ).select_related("worker", "site") | Assignment.unscoped.filter(
        company=company,
        start_date__lte=end_date,
        end_date__isnull=True,
    ).select_related("worker", "site")

    colors = ["#3b82f6", "#ef4444", "#f59e0b", "#10b981", "#8b5cf6", "#ec4899", "#06b6d4"]
    site_colors = {}
    color_idx = 0

    events = []
    for a in assignments.distinct():
        if a.site_id not in site_colors:
            site_colors[a.site_id] = colors[color_idx % len(colors)]
            color_idx += 1

        events.append({
            "title": f"{a.worker.name} → {a.site.name}",
            "start": a.start_date.isoformat(),
            "end": (a.end_date + timedelta(days=1)).isoformat() if a.end_date else None,
            "color": site_colors[a.site_id],
            "extendedProps": {
                "worker": a.worker.name,
                "site": a.site.name,
            },
        })

    return events


def apply_template(site, template_id, base_date=None):
    """工程テンプレートを現場に適用して Phase を一括作成する。

    Args:
        site: Site インスタンス
        template_id: PhaseTemplate の PK
        base_date: 基準日（デフォルト: 今日）
    """
    template = PhaseTemplate.unscoped.get(pk=template_id)
    if base_date is None:
        base_date = date.today()

    created = []
    for item in template.items.order_by("sort_order"):
        phase = Phase.unscoped.create(
            company=site.company,
            site=site,
            name=item.name,
            start_date=base_date + timedelta(days=item.offset_days_start),
            end_date=base_date + timedelta(days=item.offset_days_end),
            sort_order=item.sort_order,
            color=item.color,
        )
        created.append(phase)

    return created


def week_bounds(ref_date):
    """ref_date を含む週の月曜日と日曜日を返す。"""
    week_start = ref_date - timedelta(days=ref_date.weekday())
    return week_start, week_start + timedelta(days=6)


def normalize_place(value):
    """現場名・行き先を突き合わせ用に揃える（ADR-0036）。

    NFKC で全角英数・全角空白を半角にし、空白（全角を含む）をすべて除いてから
    casefold する。「Ａ社　ビル」「a社 ビル」「A社ビル」を同じ文字列にするため。
    """
    text = unicodedata.normalize("NFKC", value or "").strip()
    return _WHITESPACE.sub("", text).casefold()


def _place_matches(note, site_name):
    """揃えた行き先 note が、揃えた現場名 site_name を指しているか。

    完全一致、行き先（2文字以上）が現場名に含まれる、現場名が行き先に含まれる、のどれか。
    行き先1文字の部分一致は「A」「東」のような書きかけで別の現場に当たりやすいので採らない。
    """
    if not note or not site_name:
        return False
    return (
        note == site_name
        or (len(note) >= 2 and note in site_name)
        or site_name in note
    )


def _worker_sort_key(member):
    worker = member["worker"]
    return (worker.employee_code or "", worker.name, worker.pk)


def _member(worker, plan, labels, is_away):
    """現場カードに並べる参加者1人ぶん。予定があれば区分・時刻、無ければ「配置」。"""
    return {
        "worker": worker,
        "kind": plan.kind if plan else "",
        "label": labels.get(plan.kind, "") if plan else ASSIGNED_LABEL,
        "time_label": plan.time_label if plan else "",
        "is_away": is_away,
    }


def _attach_site_members(company, entries, day):
    """現場カード（entries）に day の参加者 "members" を足し、現場と一致しない予定を返す。

    参加者は次の2つを合わせ、作業員ごとに1人にまとめる（ADR-0036）。

      * 配置（Assignment）… 期間が day を含むもの。終了日なしは続いているとみなす
      * 出社予定（AttendPlan）… 区分が現場・直行直帰・出張で、行き先（note）が
        現場名と一致するもの。一致の判定は normalize_place と _place_matches。
        並んでいる現場のうち2つ以上に一致する行き先は、どれにも一致しないものとする

    表示は予定を優先する。配置されている人でも、その日の予定が
      * 別の現場と一致していれば、この現場には出さない（その日はそちらへ行く）
      * 現場へ出る区分でなければ（有休・休み・在宅など）、区分を付けて控えめに出す
        （is_away=True。配置の期間中でも、その日は現場にいないと分かるように）

    どの現場とも一致しない予定（行き先が空・一致なし・複数に一致）は捨てずに返し、
    ホームで1行にまとめて見せる。退職者は配置・予定とも出さない。

    出社予定は1人1日に複数件ありうる（1日を時間で分けた予定、ADR-0038）。
    予定ごとに突き合わせるので、午前 A・午後 B なら両方の現場カードに
    それぞれの時間で出る。同じ現場へ2回行くなら時間を並べて1人にまとめる。

    クエリは現場数によらず配置・予定の各1回。
    """
    from apps.attendance.models import AttendPlan

    labels = dict(AttendPlan.Kind.choices)
    site_names = {entry["site_id"]: normalize_place(entry["name"]) for entry in entries}
    members = {site_id: {} for site_id in site_names}

    # unscoped: 他のサービス関数と同じく company を引数で受けて明示的に絞る。
    # 1人1日に複数件ありうるので、作業員ごとに開始の早い順で持つ。
    plans = {}
    for plan in (
        AttendPlan.unscoped.filter(company=company, plan_date=day, worker__is_active=True)
        .select_related("worker")
        .order_by("start_time", "pk")
    ):
        plans.setdefault(plan.worker_id, []).append(plan)

    matched = set()  # 予定の行き先がどこかの現場と一致した作業員
    unmatched = []
    for worker_plans in plans.values():
        for plan in worker_plans:
            if plan.kind not in MEMBER_PLAN_KINDS:
                continue
            note = normalize_place(plan.note)
            hits = [
                site_id for site_id, name in site_names.items() if _place_matches(note, name)
            ]
            if len(hits) != 1:
                unmatched.append({
                    **_member(plan.worker, plan, labels, is_away=False),
                    "note": plan.note.strip(),
                    "is_ambiguous": len(hits) > 1,
                })
                continue
            matched.add(plan.worker_id)
            site_members = members[hits[0]]
            member = site_members.get(plan.worker_id)
            if member is None:
                site_members[plan.worker_id] = _member(plan.worker, plan, labels, is_away=False)
            elif plan.time_label:
                # 同じ現場へ1日に2回行く（午前と夕方など）。1人にまとめて時間を並べる
                member["time_label"] = "・".join(
                    label for label in (member["time_label"], plan.time_label) if label
                )

    if site_names:
        # unscoped: 上と同じ理由。表示する現場の分だけを1クエリで引く。
        assignments = (
            Assignment.unscoped.filter(
                company=company,
                site_id__in=list(site_names),
                start_date__lte=day,
                worker__is_active=True,
            )
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=day))
            .select_related("worker")
        )
        for assignment in assignments:
            worker_id = assignment.worker_id
            site_members = members[assignment.site_id]
            if worker_id in site_members or worker_id in matched:
                # 予定の行き先で決まっている（この現場なら予定の区分・時刻を出し済み）
                continue
            worker_plans = plans.get(worker_id, [])
            # 現場へ出る予定が1件でもあれば控えめにせず、その予定の区分・時刻を出す
            on_site = [p for p in worker_plans if p.kind in ON_SITE_PLAN_KINDS]
            plan = (on_site or worker_plans or [None])[0]
            is_away = bool(worker_plans) and not on_site
            site_members[worker_id] = _member(assignment.worker, plan, labels, is_away)

    for entry in entries:
        entry["members"] = sorted(members[entry["site_id"]].values(), key=_worker_sort_key)
    return sorted(unmatched, key=_worker_sort_key)


def get_active_sites_with_week_schedule(
    company, ref_date=None, limit=None, include_amounts=False, members_date=None,
):
    """施工中の現場と、基準日を含む週（月〜日）の工程・マイルストーンを返す（ホーム用）。

    工程は開始日・終了日の両方があり、週と1日でも重なるもの。マイルストーンは
    目標日が週内のもの。日付の無いものはガントチャートと同じく対象外にする。
    現場は工期終了が近い順（未設定は最後）、同日なら現場名順。

    Args:
        company: 対象テナント
        ref_date: 基準日。省略時は timezone.localdate()
        limit: 返す現場数の上限。None なら全件
        include_amounts: True のときだけ受注金額を載せる。原価を見られない人の
            コンテキストに金額を渡さないため、既定は載せない
        members_date: 指定した日の参加者（配置と出社予定）を現場ごとに載せる
            （ADR-0036、_attach_site_members）。週は ref_date のまま変えない

    Returns:
        {
            "week_start": date, "week_end": date,
            "sites": [
                {
                    "site_id", "name", "customer_name", "start_date", "end_date",
                    "contract_amount"（include_amounts のときだけ）,
                    "phases": [Phase, ...], "milestones": [Milestone, ...],
                    "members"（members_date のときだけ）:
                        [{"worker", "kind", "label", "time_label", "is_away"}, ...],
                },
                ...
            ],
            # 以下は members_date のときだけ
            "members_date": date,
            "unmatched_plans": [{"worker", "kind", "label", "time_label", "is_away",
                                 "note", "is_ambiguous"}, ...],
        }
    """
    from apps.sites.models import Site

    if ref_date is None:
        ref_date = timezone.localdate()
    week_start, week_end = week_bounds(ref_date)

    # unscoped: 他のサービス関数と同じく company を引数で受けて明示的に絞る。
    # 工程・マイルストーンは Prefetch で現場数によらず各1クエリにまとめる。
    week_phases = Phase.unscoped.filter(
        company=company,
        start_date__lte=week_end,
        end_date__gte=week_start,
    ).order_by("start_date", "sort_order", "pk")
    week_milestones = Milestone.unscoped.filter(
        company=company,
        target_date__range=(week_start, week_end),
    ).order_by("target_date", "pk")

    sites = (
        Site.unscoped.filter(company=company, status=Site.Status.IN_PROGRESS)
        .select_related("customer")
        .prefetch_related(
            Prefetch("phases", queryset=week_phases, to_attr="week_phases"),
            Prefetch("milestones", queryset=week_milestones, to_attr="week_milestones"),
        )
        .order_by(F("end_date").asc(nulls_last=True), "name", "pk")
    )
    if limit is not None:
        sites = sites[:limit]

    entries = []
    for site in sites:
        entry = {
            "site_id": site.pk,
            "name": site.name,
            "customer_name": site.customer.name if site.customer else "",
            "start_date": site.start_date,
            "end_date": site.end_date,
            "phases": site.week_phases,
            "milestones": site.week_milestones,
        }
        if include_amounts:
            entry["contract_amount"] = site.contract_amount
        entries.append(entry)

    result = {"week_start": week_start, "week_end": week_end, "sites": entries}
    if members_date is not None:
        result["members_date"] = members_date
        result["unmatched_plans"] = _attach_site_members(company, entries, members_date)
    return result
