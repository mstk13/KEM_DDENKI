"""API使用量モニタリング。

月間コストを集計し、上限(¥4,000)に達したらAI機能を停止する。
¥1,000を超えた時点でレポート付きアラートを送信する。
"""

import logging
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from apps.ai.models import AILog

logger = logging.getLogger(__name__)

# アラート閾値
# ¥1,000固定 + 上限の80%/90%/100%
ALERT_THRESHOLDS = [
    (Decimal("1.00"), "error", "API使用量が月間上限に達しました。AI機能を停止しました"),
    (Decimal("0.90"), "warning", "API使用量が月間上限の90%に達しました。まもなく停止します"),
    (Decimal("0.80"), "info", "API使用量が月間上限の80%に達しました"),
]

# ¥1,000 を超えた時点で詳細レポート付きアラートを出す
FIRST_ALERT_JPY = 1000


def get_monthly_cost_jpy(company=None):
    """当月のAPI使用コスト（円）を取得する。"""
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


def get_monthly_cost_report(company):
    """当月のコスト内訳レポートを生成する。

    Returns:
        dict: タスク種別別、モデル別、日別、ユーザー別の集計データ
    """
    from django.db.models import Count
    from django.db.models.functions import TruncDate

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rate = getattr(settings, "AI_USD_TO_JPY_RATE", 152)

    qs = AILog.unscoped.filter(
        company=company,
        created_at__gte=month_start,
        status=AILog.Status.SUCCESS,
    )

    # タスク種別ごと
    by_task = list(
        qs.values("task_type")
        .annotate(
            call_count=Count("id"),
            total_usd=Sum("cost_usd"),
            total_tokens=Sum("input_tokens") + Sum("output_tokens"),
        )
        .order_by("-total_usd")
    )
    for row in by_task:
        row["total_jpy"] = int((row["total_usd"] or 0) * rate)
        row["task_display"] = dict(AILog.TaskType.choices).get(
            row["task_type"], row["task_type"]
        )

    # モデル別
    by_model = list(
        qs.values("model_used")
        .annotate(
            call_count=Count("id"),
            total_usd=Sum("cost_usd"),
        )
        .order_by("-total_usd")
    )
    for row in by_model:
        row["total_jpy"] = int((row["total_usd"] or 0) * rate)
        row["model_display"] = dict(AILog.ModelType.choices).get(
            row["model_used"], row["model_used"]
        )

    # 日別
    by_date = list(
        qs.annotate(date=TruncDate("created_at"))
        .values("date")
        .annotate(
            call_count=Count("id"),
            total_usd=Sum("cost_usd"),
        )
        .order_by("date")
    )
    for row in by_date:
        row["total_jpy"] = int((row["total_usd"] or 0) * rate)

    # ユーザー別
    by_user = list(
        qs.values("requested_by__first_name", "requested_by__username")
        .annotate(
            call_count=Count("id"),
            total_usd=Sum("cost_usd"),
        )
        .order_by("-total_usd")
    )
    for row in by_user:
        row["total_jpy"] = int((row["total_usd"] or 0) * rate)
        row["user_display"] = (
            row["requested_by__first_name"]
            or row["requested_by__username"]
            or "システム"
        )

    # コスト上位のリクエスト
    top_requests = list(
        qs.select_related("site", "requested_by")
        .order_by("-cost_usd")[:10]
    )

    return {
        "by_task": by_task,
        "by_model": by_model,
        "by_date": by_date,
        "by_user": by_user,
        "top_requests": top_requests,
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

    # ¥1,000超えの初回アラート（レポート付き）
    if summary["cost_jpy"] >= FIRST_ALERT_JPY:
        _send_first_alert(company, summary)

    # 上限に対する割合チェック
    usage_ratio = Decimal(str(summary["cost_jpy"])) / Decimal(str(summary["budget_jpy"]))
    for threshold, level, message in ALERT_THRESHOLDS:
        if usage_ratio >= threshold:
            _send_budget_alert(company, summary, level, message)
            break

    return True


def _send_first_alert(company, summary):
    """¥1,000超えの初回アラート。レポートページへのリンク付き。"""
    from apps.notifications.models import Notification
    from apps.permissions.models import Role, UserRole

    now = timezone.now()
    month_key = now.strftime("%Y-%m")

    # 同月の¥1,000アラートは1回だけ
    existing = Notification.unscoped.filter(
        company=company,
        module=Notification.Module.SYSTEM,
        title__contains="¥1,000超過",
        sent_at__gte=now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
    ).exists()
    if existing:
        return

    report = get_monthly_cost_report(company)

    # レポート本文を構築
    body_lines = [
        f"月間API使用量が¥{summary['cost_jpy']:,}に達しました（上限¥{summary['budget_jpy']:,}）。",
        "",
        "【コスト内訳】",
    ]
    for row in report["by_task"]:
        body_lines.append(
            f"  {row['task_display']}: ¥{row['total_jpy']:,}（{row['call_count']}回）"
        )
    body_lines.append("")
    body_lines.append("【モデル別】")
    for row in report["by_model"]:
        body_lines.append(
            f"  {row['model_display']}: ¥{row['total_jpy']:,}（{row['call_count']}回）"
        )
    body_lines.append("")
    body_lines.append("【ユーザー別】")
    for row in report["by_user"]:
        body_lines.append(
            f"  {row['user_display']}: ¥{row['total_jpy']:,}（{row['call_count']}回）"
        )
    body_lines.append("")
    body_lines.append("詳細レポート（グラフ付き）→ /ai/cost-report/")

    body = "\n".join(body_lines)

    # 社長・役員に通知
    president_roles = Role.unscoped.filter(
        company=company, code__in=["president", "executive"],
    )
    user_ids = UserRole.unscoped.filter(
        role__in=president_roles,
    ).values_list("user_id", flat=True).distinct()

    for uid in user_ids:
        Notification.unscoped.create(
            company=company,
            recipient_id=uid,
            title=f"API使用量¥1,000超過レポート（{month_key}）",
            body=body,
            level=Notification.Level.WARNING,
            module=Notification.Module.SYSTEM,
            channel=Notification.Channel.IN_APP,
            reference_url="/ai/cost-report/",
        )

    logger.info(
        "First alert (¥1,000) sent: company=%s cost_jpy=%d",
        company, summary["cost_jpy"],
    )


def _send_budget_alert(company, summary, level, message):
    """予算アラート通知を送信する（重複防止付き）。"""
    from apps.notifications.models import Notification
    from apps.permissions.models import Role, UserRole

    now = timezone.now()
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

    president_roles = Role.unscoped.filter(
        company=company, code__in=["president", "executive"],
    )
    user_ids = UserRole.unscoped.filter(
        role__in=president_roles,
    ).values_list("user_id", flat=True).distinct()

    body = (
        f"月間使用量: ¥{summary['cost_jpy']:,} / ¥{summary['budget_jpy']:,} "
        f"({summary['usage_pct']}%)\n"
        f"残り: ¥{summary['remaining_jpy']:,}\n"
        f"詳細レポート → /ai/cost-report/"
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
            reference_url="/ai/cost-report/",
        )

    logger.info(
        "API budget alert sent: company=%s level=%s cost_jpy=%d",
        company, level, summary["cost_jpy"],
    )
