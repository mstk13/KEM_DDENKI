"""Discord Webhook通知。"""

import logging
import threading
from urllib.request import Request, urlopen
import json

logger = logging.getLogger(__name__)


def _send_webhook(webhook_url, payload):
    """Webhookを非同期で送信（レスポンスをブロックしない）。"""
    def _post():
        try:
            data = json.dumps(payload).encode("utf-8")
            req = Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urlopen(req, timeout=10)
        except Exception:
            logger.exception("Discord webhook送信に失敗: %s", webhook_url)

    threading.Thread(target=_post, daemon=True).start()


def notify_task_assigned(task, assigned_by):
    """タスクが担当者に割り当てられた際にDiscord通知を送信。"""
    webhook_url = task.project.discord_webhook_url
    if not webhook_url or not task.assignee:
        return

    priority_emoji = {
        "low": "",
        "medium": "",
        "high": "!",
        "critical": "!!",
    }
    p_mark = priority_emoji.get(task.priority, "")
    priority_label = task.get_priority_display()
    category_label = task.get_category_display()
    status_label = task.get_status_display()
    due = str(task.due_date) if task.due_date else "未設定"

    embed = {
        "title": f"#{task.pk} {task.title}",
        "color": 0x1A2744,
        "fields": [
            {"name": "担当者", "value": task.assignee.get_full_name() or task.assignee.username, "inline": True},
            {"name": "優先度", "value": f"{priority_label} {p_mark}", "inline": True},
            {"name": "カテゴリ", "value": category_label, "inline": True},
            {"name": "ステータス", "value": status_label, "inline": True},
            {"name": "期限", "value": due, "inline": True},
            {"name": "プロジェクト", "value": task.project.name, "inline": True},
        ],
        "footer": {"text": f"割当者: {assigned_by.get_full_name() or assigned_by.username}"},
    }

    if task.description:
        embed["description"] = task.description[:200]

    payload = {
        "content": f"**タスクが割り当てられました**",
        "embeds": [embed],
    }
    _send_webhook(webhook_url, payload)


def notify_task_status_changed(task, changed_by, old_status):
    """タスクのステータスが変更された際にDiscord通知を送信。"""
    webhook_url = task.project.discord_webhook_url
    if not webhook_url:
        return

    old_label = dict(task.Status.choices).get(old_status, old_status)
    new_label = task.get_status_display()
    assignee_name = (
        task.assignee.get_full_name() or task.assignee.username
    ) if task.assignee else "未割当"

    embed = {
        "title": f"#{task.pk} {task.title}",
        "color": 0x2C4A7C,
        "fields": [
            {"name": "ステータス変更", "value": f"{old_label} → {new_label}", "inline": False},
            {"name": "担当者", "value": assignee_name, "inline": True},
            {"name": "変更者", "value": changed_by.get_full_name() or changed_by.username, "inline": True},
        ],
    }

    payload = {
        "content": f"**ステータスが変更されました**",
        "embeds": [embed],
    }
    _send_webhook(webhook_url, payload)
