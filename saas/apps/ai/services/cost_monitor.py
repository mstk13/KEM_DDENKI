"""API使用量モニタリング。

月間コストを集計し、上限(9,900円)に達したらAI機能を停止する。
上限に近づいたら通知を送信する。
"""

import logging
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from apps.ai.models import AILog

logger = logging.getLogger(__name__)

# アラート閾値（上限に対する割合）
ALERT_THRESHOLDS = [
    (Decimal("0.80"), "info", "API使用量が月間上限の80%に達しました"),
    (Decimal("0.90"), "warning", "API使用量が月間上限の90%に達しました。まもなく停止します"),
    (Decimal("1.00"), "error", "API使用量が月間上限に達しました。AI機能を停止しました"),
]


def get_monthly_cost_jpy(company=None):
    """当月のAPI使用コスト（円）を取得する。

    Returns:
        dict: {
            "cost_usd": Decimal,
            "cost_jpy": int,
            "budget_jpy": int,
            "usage_pct": int,
            "is_over_budget": bool,
            "remaining_jpy": int,
        }
    """
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    qs = AILog.unscoped.filter(
        created_at__gte=month_start,
        status=AILog.Status.SUCCESS,
    )
    if company:
        qs = qs.filter(company=company)

    total_usd = qs.aggregate(t=Sum("cost_usd"))["t"] or Decimal("0")
    rate = getattr(settings, "AI_USD_TO_JPY_RATE", 152)
    budget_jpy = getattr(settings, "AI_MONTHLY_BUDGET_JPY", 4000)

    cost_jpy = int(total_usd * rate)
    usage_pct = int(cost_jpy / budget_jpy * 100) if budget_jpy > 0 else 0

    return {
        "cost_usd": total_usd,
        "cost_jpy": cost_jpy,
        "budget_jpy": budget_jpy,
        "usage_pct": min(usage_pct, 999),
        "is_over_budget": cost_jpy >= budget_jpy,
        "remaining_jpy": max(budget_jpy - cost_jpy, 0),
    }


def check_budget_and_notify(company, user=None):
    """予算チェックし、閾値を超えていたら通知を送信する。

    Returns:
        True: 実行可能
        False: 予算超過で実行不可
    """
    summary = get_monthly_cost_jpy(company)

    if summary["is_over_budget"]:
        _send_budget_alert(company, summary, "error",
                           "API使用量が月間上限に達しました。AI機能を停止しました")
        return False

    # 閾値チェックして通知
    usage_ratio = Decimal(str(summary["cost_jpy"])) / Decimal(str(summary["budget_jpy"]))
    for threshold, level, message in ALERT_THRESHOLDS:
        if usage_ratio >= threshold:
            _send_budget_alert(company, summary, level, message)
            break  # 最も高い閾値の通知のみ送信

    return True


def _send_budget_alert(company, summary, level, message):
    """予算アラート通知を送信する（重複防止付き）。"""
    from apps.notifications.models import Notification
    from apps.permissions.models import Role, UserRole

    now = timezone.now()
    # 同日の同レベル通知は重複送信しない
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    existing = Notification.unscoped.filter(
        company=company,
        module=Notification.Module.SYSTEM,
        title__contains="API使用量",
        level=level,
        sent_at__gte=today_start,
    ).exists()
    if existing:
        return

    # 社長・役員ロールのユーザーに通知
    president_roles = Role.unscoped.filter(
        company=company, code__in=["president", "executive"],
    )
    user_ids = UserRole.unscoped.filter(
        role__in=president_roles,
    ).values_list("user_id", flat=True).distinct()

    body = (
        f"月間使用量: ¥{summary['cost_jpy']:,} / ¥{summary['budget_jpy']:,} "
        f"({summary['usage_pct']}%)\n"
        f"残り: ¥{summary['remaining_jpy']:,}"
    )

    for uid in user_ids:
        Notification.unscoped.create(
            company=company,
            recipient_id=uid,
            title=f"API使用量アラート: {message}",
            body=body,
            level=level,
            module=Notification.Module.SYSTEM,
            channel=Notification.Channel.IN_APP,
        )

    logger.info(
        "API budget alert sent: company=%s level=%s cost_jpy=%d",
        company, level, summary["cost_jpy"],
    )
