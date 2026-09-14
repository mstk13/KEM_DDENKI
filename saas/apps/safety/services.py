"""安全書類の最初の値・その日の参加者・朝の知らせ（ADR-0061）。"""

import datetime

from django.urls import reverse
from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.services import notify
from apps.safety.formats import DEFAULT_RISKS, RISK_ROWS
from apps.safety.models import EntryConfirmation, KySheet
from apps.schedules.services import site_members_on_day

# 様式に書いてある作業時間（8:00〜17:30）
DEFAULT_WORK_START = datetime.time(8, 0)
DEFAULT_WORK_END = datetime.time(17, 30)

# 朝の知らせを出す現場の状態（受注してから完工するまで）
REMINDER_SITE_STATUSES = ("ordered", "in_progress")
REMINDER_REFERENCE_TYPE = "safety.morning_reminder"

# 前の用紙から写す項目（その現場で毎日ほぼ同じになるもの）
_CARRY_OVER_FIELDS = (
    "crew_name",
    "work_start",
    "work_end",
    "leader_name",
    "work_content",
    "safety_instructions",
    "extra_check_7",
    "extra_check_8",
    "sc5_extra_5",
    "sc5_extra_6",
)


def user_display_name(user):
    """ユーザーの名前。作業員に紐づいていれば作業員の氏名。"""
    if user is None:
        return ""
    worker = getattr(user, "worker_profile", None)
    if worker is not None:
        return worker.name
    return user.get_full_name() or user.username


def blank_risks():
    """様式に初めから書いてある危険と低減措置を、RISK_ROWS 行にそろえて返す。"""
    rows = [
        {"hazard": row["hazard"], "level": "", "measure": row["measure"], "checked": False}
        for row in DEFAULT_RISKS
    ]
    while len(rows) < RISK_ROWS:
        rows.append({"hazard": "", "level": "", "measure": "", "checked": False})
    return rows


def _candidate_sites(company, extra=()):
    """行き先の突き合わせに使う現場（受注済・施工中）。

    1つの現場だけで突き合わせると、別の現場へ行く予定の人を「配置されている」だけで
    この現場の参加者に数えてしまう。朝の知らせと同じ現場の並びで突き合わせる。
    """
    from apps.sites.models import Site

    # unscoped: テナントの文脈の外（朝の知らせ）からも呼ぶので、会社で明示的に絞る
    sites = list(Site.unscoped.filter(company=company, status__in=REMINDER_SITE_STATUSES))
    known = {site.pk for site in sites}
    return sites + [site for site in extra if site.pk not in known]


def members_on_day(site, day):
    """その日にこの現場へ出る作業員（ホームの現場カードの参加者と同じ判定。ADR-0036）。"""
    sites = _candidate_sites(site.company, [site])
    return site_members_on_day(site.company, sites, day).get(site.pk, [])


def ky_initial(site, day):
    """KY用紙の最初の値。

    同じ現場の、この日より前で一番新しい用紙から、毎日ほぼ同じになる項目と危険の行を写す
    （危険度と作業中確認は写さない）。前の用紙が無ければ様式の既定値。
    作業責任者は現場担当者、予定人数はその日の参加者の数。
    """
    initial = {
        "work_start": DEFAULT_WORK_START,
        "work_end": DEFAULT_WORK_END,
        "leader_name": user_display_name(site.manager),
        "planned_headcount": len(members_on_day(site, day)) or None,
        "risks": blank_risks(),
    }
    # unscoped: 朝の知らせ（テナントの文脈の外）からも呼ぶので、現場の会社で明示的に絞る
    previous = (
        KySheet.unscoped.filter(company=site.company, site=site, work_date__lt=day)
        .order_by("-work_date")
        .first()
    )
    if previous is not None:
        for field in _CARRY_OVER_FIELDS:
            value = getattr(previous, field)
            if value not in (None, ""):
                initial[field] = value
        if previous.risks:
            initial["risks"] = [
                {**row, "level": "", "checked": False} for row in previous.risks[:RISK_ROWS]
            ]
    return initial


def experience_years_months(started_on, today):
    """経験の起算日から today までを「年・月」で返す。起算日が無ければ (None, None)。"""
    if not started_on:
        return None, None
    months = (today.year - started_on.year) * 12 + today.month - started_on.month
    if today.day < started_on.day:
        months -= 1
    months = max(months, 0)
    return months // 12, months % 12


def _with_extra(main, extra, fmt):
    return f"{main}{fmt.format(extra)}" if main and extra else main


def entry_initial(site, worker, day):
    """安全作業確認書の最初の値。作業員の登録（ADR-0057・ADR-0059）と最新の健康診断から入れる。

    視力は矯正の値があれば矯正、無ければ裸眼。血圧・視力はそれぞれ記録のある一番新しい健康診断から。
    """
    from apps.workers.models import HealthCheckup

    postal = f"〒{worker.postal_code} " if worker.postal_code else ""
    emergency_postal = (
        f"〒{worker.emergency_contact_postal_code} "
        if worker.emergency_contact_postal_code
        else ""
    )
    initial = {
        "entry_date": day,
        "name_kana": worker.name_kana,
        "birth_date": worker.birth_date,
        "address": f"{postal}{worker.address}".strip(),
        "phone": worker.phone,
        "emergency_contact_name": _with_extra(
            worker.emergency_contact_name,
            worker.emergency_contact_relationship,
            "（{}）",
        ),
        "emergency_contact_address": (
            f"{emergency_postal}{worker.emergency_contact_address}".strip()
        ),
        "emergency_contact_phone": worker.emergency_contact_phone,
        "blood_type": worker.blood_type,
    }
    years, months = experience_years_months(worker.experience_started_on, day)
    initial["experience_years"] = years
    initial["experience_months"] = months

    # unscoped: 作業員の会社で明示的に絞る
    checkups = list(
        HealthCheckup.unscoped.filter(company=worker.company, worker=worker).order_by(
            "-checkup_date",
            "-pk",
        )
    )
    vision = next((c for c in checkups if c.has_vision), None)
    if vision is not None:
        for side in ("right", "left"):
            corrected = getattr(vision, f"vision_{side}_corrected")
            naked = getattr(vision, f"vision_{side}_naked")
            value = corrected if corrected is not None else naked
            initial[f"vision_{side}"] = "" if value is None else HealthCheckup._vision_text(value)
    pressure = next((c for c in checkups if c.has_blood_pressure), None)
    if pressure is not None:
        initial["blood_pressure_high"] = pressure.blood_pressure_high
        initial["blood_pressure_low"] = pressure.blood_pressure_low
    return initial


def workers_without_entry(site, workers):
    """workers のうち、この現場の安全作業確認書をまだ書いていない人。"""
    workers = list(workers)
    # unscoped: 朝の知らせ（テナントの文脈の外）からも呼ぶので、現場の会社で明示的に絞る
    done = set(
        EntryConfirmation.unscoped.filter(
            company=site.company,
            site=site,
            worker__in=workers,
        ).values_list("worker_id", flat=True)
    )
    return [worker for worker in workers if worker.pk not in done]


def send_morning_reminders(company, day=None):
    """その日に現場へ出る人に、KY用紙の記入を知らせる（毎朝8時。ADR-0061）。

    宛先はホームの現場カードの参加者と同じ（出社予定の行き先がその現場の人と、配置されている人）。
    安全作業確認書をまだ書いていない人には、それもあわせて知らせる。
    同じ日・同じ現場・同じ人には1回だけ（朝の処理が2回走っても重ねない）。
    ログインのアカウントが無い作業員には出せないので飛ばす。

    Returns: 作った通知の数
    """
    from apps.sites.models import Site

    day = day or timezone.localdate()
    sites = list(
        Site.unscoped.filter(company=company, status__in=REMINDER_SITE_STATUSES).order_by("name")
    )
    if not sites:
        return 0
    members = site_members_on_day(company, sites, day)
    created = 0
    for site in sites:
        workers = members.get(site.pk, [])
        if not workers:
            continue
        missing = {worker.pk for worker in workers_without_entry(site, workers)}
        url = reverse("safety:ky_sheet", kwargs={"site_pk": site.pk, "day": day})
        for worker in workers:
            user = worker.user
            if user is None or not user.is_active:
                continue
            # 送った日ではなく「どの日の用紙の知らせか」で重ねない（URL に日付が入っている）
            already = Notification.unscoped.filter(
                company=company,
                recipient=user,
                reference_type=REMINDER_REFERENCE_TYPE,
                reference_id=site.pk,
                reference_url=url,
            ).exists()
            if already:
                continue
            body = (
                "今日の KY 用紙（安全作業指示書）に、"
                "自分の行（サイン・健康状態・検電器）を記入してください。"
            )
            if worker.pk in missing:
                body += "\nこの現場の安全作業確認書がまだです。あわせて記入してください。"
            notify(
                company=company,
                recipient=user,
                title=f"【{site.name}】今日のKY用紙を記入してください",
                body=body,
                module=Notification.Module.SAFETY,
                reference_type=REMINDER_REFERENCE_TYPE,
                reference_id=site.pk,
                reference_url=url,
            )
            created += 1
    return created
