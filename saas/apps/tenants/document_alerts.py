"""自社書類の更新が近づいたら知らせる（ADR-0071）。

毎朝 8 時の send_document_alerts から呼ぶ（建設業許可の知らせと同じ仕組み）。

- 更新日の 90・30・14 日前（3か月前・1か月前・2週間前）と当日、過ぎた日に知らせる
- 1つの段階は1回だけ。止まっていた日があっても、今の段階の1通だけを出す
- 知らせるのは社長・管理者（社員番号 Y）・事務員・Developer（建設業許可の知らせと同じ）
- 種類ごとにいちばん新しい書類だけを見る。入れ直した前の版では知らせない
"""

import datetime

from django.urls import reverse
from django.utils import timezone

from apps.bids.license_alerts import license_alert_recipients
from apps.notifications.models import Notification
from apps.notifications.services import notify_multiple
from apps.tenants.company_documents import renewal_documents
from apps.tenants.models import CompanyDocument

REFERENCE_TYPE = "tenants.CompanyDocument"
# 3か月前・1か月前・2週間前（プロダクトオーナー確認 2026-09-16）
LEAD_DAYS = (90, 30, 14)


def reminder_steps(document):
    """知らせる段階を日付の順に返す。[(知らせ始める日, 種類)]。"""
    target = document.renewal_on
    steps = [(target - datetime.timedelta(days=days), "before") for days in LEAD_DAYS]
    steps.append((target, "due"))
    steps.append((target + datetime.timedelta(days=1), "overdue"))
    steps.sort(key=lambda step: step[0])
    return steps


def current_step(document, today):
    """今日までに来た最後の段階の番号。まだ何も来ていなければ None。"""
    reached = [i for i, (day, _kind) in enumerate(reminder_steps(document)) if day <= today]
    return reached[-1] if reached else None


def build_message(document, kind, today):
    """(タイトル, 本文, 重要度)。"""
    if kind == "before":
        days = (document.renewal_on - today).days
        title = f"{document.name}の更新まで残り{days}日"
        level = Notification.Level.WARNING if days <= 30 else Notification.Level.INFO
    elif kind == "due":
        title = f"{document.name}の更新日は今日です"
        level = Notification.Level.ERROR
    else:
        title = f"🔴 {document.name}の更新日を過ぎています"
        level = Notification.Level.ERROR

    body = f"更新日 {document.renewal_on:%Y-%m-%d}"
    if document.issued_on:
        body += f" / 発行日 {document.issued_on:%Y-%m-%d}"
    body += "\n新しい書類を受け取ったら、自社情報の画面に登録してください。"
    return title, body, level


def check_company_document_alerts(company, today=None) -> int:
    """更新日が近い自社書類を知らせる。作った通知の件数を返す。"""
    today = today or timezone.localdate()
    recipients = None
    created = 0
    for document in renewal_documents(company):
        step = current_step(document, today)
        if step is None or (
            document.reminder_step is not None and step <= document.reminder_step
        ):
            continue
        if recipients is None:
            recipients = license_alert_recipients(company)
        if not recipients:
            # 受け取る人がいなければ段階を進めない（人が増えたら今の段階を知らせる）
            continue
        kind = reminder_steps(document)[step][1]
        title, body, level = build_message(document, kind, today)
        created += len(notify_multiple(
            company=company,
            recipients=recipients,
            title=title,
            body=body,
            level=level,
            module=Notification.Module.SYSTEM,
            reference_type=REFERENCE_TYPE,
            reference_id=document.pk,
            reference_url=reverse("tenants:company_document_detail", args=[document.pk]),
        ))
        # 段階の記録だけなので履歴を増やさないよう update で書く
        CompanyDocument.unscoped.filter(pk=document.pk).update(reminder_step=step)
    return created
