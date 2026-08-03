"""開発管理のビジネスロジック。

Discord webhook通知、タスク統計を担う。
将来の DRF API 移行時にもそのまま使える。
"""

import json
import logging
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


def send_discord_webhook(webhook_url: str, title: str, body: str, color: int = 0x3B82F6):
    """Discord webhookにEmbedメッセージを送信する。

    Args:
        webhook_url: Discord Webhook URL
        title: Embedタイトル
        body: Embed本文
        color: Embed色（16進数）
    """
    if not webhook_url:
        return

    payload = {
        "embeds": [
            {
                "title": title,
                "description": body,
                "color": color,
            }
        ]
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urlopen(req, timeout=5)
    except Exception:
        logger.warning("Discord webhook送信に失敗: %s", webhook_url, exc_info=True)


def notify_task_assigned(task):
    """タスク割当時にDiscord通知を送る。"""
    project = task.project
    if not project.discord_webhook_url:
        return

    assignee = task.assignee.get_full_name() if task.assignee else "未割当"
    send_discord_webhook(
        project.discord_webhook_url,
        title=f"📋 タスク割当: {task.title}",
        body=(
            f"**担当者:** {assignee}\n"
            f"**優先度:** {task.get_priority_display()}\n"
            f"**期限:** {task.due_date or '未設定'}\n"
            f"**カテゴリ:** {task.get_category_display()}"
        ),
        color=0x3B82F6,
    )


def notify_task_status_changed(task, old_status: str):
    """タスクステータス変更時にDiscord通知を送る。"""
    project = task.project
    if not project.discord_webhook_url:
        return

    status_colors = {
        "open": 0x6B7280,
        "in_progress": 0x3B82F6,
        "review": 0xF59E0B,
        "done": 0x10B981,
        "closed": 0x6B7280,
    }

    send_discord_webhook(
        project.discord_webhook_url,
        title=f"🔄 ステータス変更: {task.title}",
        body=f"**{old_status}** → **{task.get_status_display()}**",
        color=status_colors.get(task.status, 0x3B82F6),
    )
