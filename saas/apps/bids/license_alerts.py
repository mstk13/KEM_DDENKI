"""自社の建設業許可の期限が近づいたら知らせる（ADR-0064）。

毎朝 8 時の send_document_alerts から呼ぶ。

- 更新書類の提出期限（無ければ有効期間の終わり）の 180・90・60・30・14・7 日前と当日に知らせる
- 提出期限を過ぎたら 1 回、有効期間の最後の日に 1 回、切れたら 1 回知らせる
- 1 つの段階は 1 回だけ。止まっていた日があっても、今の段階の 1 通だけを出す
- 「更新済」の許可には出さない。有効期間の終わり・提出期限を直したら数え直す
- 知らせるのは社長・管理者（社員番号 Y）・事務員・Developer
"""

import datetime

from django.urls import reverse
from django.utils import timezone

from apps.bids.models import ConstructionLicense
from apps.notifications.models import Notification
from apps.notifications.services import notify_multiple

REFERENCE_TYPE = "bids.ConstructionLicense"
LEAD_DAYS = (180, 90, 60, 30, 14, 7)
# 期限の知らせを受け取る役職（社長・管理者・事務員のほかに）。IT 担当はシステムの管理者として含める
MANAGER_POSITIONS = ("Developer",)


def reminder_steps(lic):
    """知らせる段階を日付の順に返す。[(知らせ始める日, 種類)]。

    種類: before（期限の○日前）/ due（期限の当日）/ overdue（提出期限を過ぎた）/
    last_day（有効期間の最後の日）/ expired（切れた）
    """
    target = lic.renewal_deadline or lic.valid_until
    steps = [(target - datetime.timedelta(days=days), "before") for days in LEAD_DAYS]
    steps.append((target, "due"))
    if lic.renewal_deadline:
        overdue = lic.renewal_deadline + datetime.timedelta(days=1)
        steps.append((overdue, "overdue"))
        if lic.valid_until > overdue:
            steps.append((lic.valid_until, "last_day"))
    steps.append((lic.valid_until + datetime.timedelta(days=1), "expired"))
    steps.sort(key=lambda step: step[0])
    return steps


def current_step(lic, today):
    """今日までに来た最後の段階の番号。まだ何も来ていなければ None。"""
    reached = [i for i, (day, _kind) in enumerate(reminder_steps(lic)) if day <= today]
    return reached[-1] if reached else None


def build_message(lic, kind, today):
    """(タイトル, 本文, 重要度)。"""
    name = f"建設業許可（{lic.trade}・{lic.get_license_class_display()}）"
    if kind == "before":
        target = lic.renewal_deadline or lic.valid_until
        what = "更新書類の提出期限" if lic.renewal_deadline else "有効期限"
        days = (target - today).days
        title = f"{name}の{what}まで残り{days}日"
        level = Notification.Level.WARNING if days <= 30 else Notification.Level.INFO
    elif kind == "due":
        if lic.renewal_deadline:
            title = f"{name}の更新書類の提出期限は今日です"
        else:
            title = f"{name}の有効期限は今日までです"
        level = Notification.Level.ERROR
    elif kind == "overdue":
        days = (lic.valid_until - today).days
        title = f"🔴 {name}の更新書類の提出期限を過ぎています（有効期限まで残り{days}日）"
        level = Notification.Level.ERROR
    elif kind == "last_day":
        title = f"🔴 {name}の有効期限は今日までです"
        level = Notification.Level.ERROR
    else:
        title = f"🔴 {name}の有効期限が切れています"
        level = Notification.Level.ERROR

    body = f"{lic.full_number} / 有効期間 {lic.valid_from:%Y-%m-%d}〜{lic.valid_until:%Y-%m-%d}"
    if lic.renewal_deadline:
        body += f" / 更新書類の提出期限 {lic.renewal_deadline:%Y-%m-%d}"
    body += "\n更新の手続きが済んだら、入札参加資格の画面の建設業許可で「更新済」にしてください。"
    return title, body, level


def can_receive_license_alerts(user):
    """期限の知らせを受け取る人か。社長・管理者（社員番号 Y）・事務員・Developer。"""
    from apps.permissions.services import get_position_name, has_role, is_president

    if is_president(user) or has_role(user, "office_staff"):
        return True
    profile = getattr(user, "worker_profile", None)
    if profile is not None and (profile.employee_code or "").startswith("Y"):
        return True
    return get_position_name(user) in MANAGER_POSITIONS


def license_alert_recipients(company):
    from apps.accounts.models import User

    users = User.objects.filter(company=company, is_active=True).order_by("pk")
    return [u for u in users if can_receive_license_alerts(u)]


def check_construction_license_alerts(company, today=None):
    """期限が近い建設業許可を知らせる。作った通知の件数を返す。"""
    today = today or timezone.localdate()
    # unscoped: 定時実行はテナントの文脈が無いので、会社を明示して絞る
    licenses = ConstructionLicense.unscoped.filter(company=company, renewed=False)
    recipients = None
    created = 0
    for lic in licenses:
        step = current_step(lic, today)
        if step is None or (lic.reminder_step is not None and step <= lic.reminder_step):
            continue
        if recipients is None:
            recipients = license_alert_recipients(company)
        if not recipients:
            # 受け取る人がいなければ段階を進めない（人が増えたら今の段階を知らせる）
            continue
        kind = reminder_steps(lic)[step][1]
        title, body, level = build_message(lic, kind, today)
        created += len(notify_multiple(
            company=company,
            recipients=recipients,
            title=title,
            body=body,
            level=level,
            module=Notification.Module.BIDS,
            reference_type=REFERENCE_TYPE,
            reference_id=lic.pk,
            reference_url=reverse("bids:qualification_list") + "#licenses",
        ))
        # 段階の記録だけなので履歴を増やさないよう update で書く
        ConstructionLicense.unscoped.filter(pk=lic.pk).update(reminder_step=step)
    return created
