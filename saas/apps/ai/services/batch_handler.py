"""17時以降のAIリクエストをバッチ処理に回す。

17時以降にリクエストされた場合、ユーザーに確認を取り、
「翌日でOK」なら AIBatchRequest に保存してバッチ実行する。
"""

import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

EVENING_HOUR = 17  # この時刻以降はバッチ確認を表示


def is_after_hours():
    """現在時刻が17時以降かどうか。"""
    now = timezone.localtime()
    return now.hour >= EVENING_HOUR


def get_next_business_morning():
    """翌営業日の朝9時を取得する。"""
    now = timezone.localtime()
    tomorrow = now + timedelta(days=1)

    # 土日をスキップ
    while tomorrow.weekday() >= 5:  # 5=土, 6=日
        tomorrow += timedelta(days=1)

    return tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)


def create_batch_request(company, site, task_type, model_key, user):
    """バッチリクエストを作成する。"""
    from apps.ai.models import AIBatchRequest

    scheduled = get_next_business_morning()

    batch = AIBatchRequest.unscoped.create(
        company=company,
        site=site,
        task_type=task_type,
        model_key=model_key,
        requested_by=user,
        scheduled_for=scheduled,
        created_by=user,
    )

    # 通知を送信
    from apps.notifications.models import Notification
    Notification.unscoped.create(
        company=company,
        recipient=user,
        title=f"AI分析をバッチ予約しました",
        body=(
            f"{site.name} の{batch.get_task_type_display()}を "
            f"{scheduled:%m/%d %H:%M} に実行予定です。"
        ),
        level=Notification.Level.INFO,
        module=Notification.Module.SYSTEM,
        channel=Notification.Channel.IN_APP,
    )

    return batch


def process_pending_batches():
    """待機中のバッチリクエストを実行する。マネジメントコマンドから呼ぶ。"""
    from apps.ai.models import AIBatchRequest
    from apps.ai.services.llm_advisor import (
        get_cost_optimization,
        get_schedule_risk_analysis,
        get_schedule_suggestion,
    )

    now = timezone.now()
    pending = AIBatchRequest.unscoped.filter(
        status=AIBatchRequest.Status.PENDING,
        scheduled_for__lte=now,
    ).select_related("site", "requested_by")

    task_handlers = {
        "cost_optimization": get_cost_optimization,
        "schedule_suggest": get_schedule_suggestion,
        "schedule_risk": get_schedule_risk_analysis,
    }

    processed = 0
    for batch in pending:
        handler = task_handlers.get(batch.task_type)
        if not handler:
            batch.status = AIBatchRequest.Status.FAILED
            batch.error_message = f"未対応のタスク種別: {batch.task_type}"
            batch.save(update_fields=["status", "error_message"])
            continue

        batch.status = AIBatchRequest.Status.PROCESSING
        batch.save(update_fields=["status"])

        try:
            result = handler(
                batch.site,
                user=batch.requested_by,
                model_key=batch.model_key,
            )
            batch.status = AIBatchRequest.Status.COMPLETED
            if result.get("ai_log_id"):
                from apps.ai.models import AILog
                batch.result_log = AILog.unscoped.filter(pk=result["ai_log_id"]).first()
            batch.save(update_fields=["status", "result_log"])

            # 完了通知
            from apps.notifications.models import Notification
            Notification.unscoped.create(
                company=batch.company,
                recipient=batch.requested_by,
                title=f"AI分析が完了しました: {batch.site.name}",
                body=f"{batch.get_task_type_display()}のバッチ処理が完了しました。",
                level=Notification.Level.INFO,
                module=Notification.Module.SYSTEM,
                channel=Notification.Channel.IN_APP,
            )
            processed += 1

        except Exception as e:
            logger.exception("Batch processing failed: batch=%d", batch.pk)
            batch.status = AIBatchRequest.Status.FAILED
            batch.error_message = str(e)
            batch.save(update_fields=["status", "error_message"])

    return processed
