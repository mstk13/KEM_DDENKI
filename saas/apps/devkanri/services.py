"""開発管理のビジネスロジック。

Discord webhook通知、タスク統計、ガントチャートのデータ生成を担う。
将来の DRF API 移行時にもそのまま使える。
"""

import datetime
import json
import logging
from urllib.request import Request, urlopen

from django.urls import reverse

logger = logging.getLogger(__name__)

# 日付が何も分からないプロジェクトのバーの長さ（日）。
# 0日だと frappe-gantt が描画しないため、最低限の幅を与える。
DEFAULT_SPAN_DAYS = 7

DONE_STATUSES = ("done", "closed")


def resolve_project_period(project, task_due_dates=None):
    """プロジェクトの表示期間を決める。

    開始日・期限は任意入力で、実際には未設定のプロジェクトが多い。
    そこだけガントから消えると全体像が見えないので、分かる材料で補う。

      開始日 … start_date → タスク期限の最小 → 作成日
      期限   … due_date  → タスク期限の最大 → 開始日 + DEFAULT_SPAN_DAYS

    Returns:
        (start: date, end: date, inferred: bool)
        inferred は補完した日付を含むか。画面では「推定」と分かるように出す。
    """
    dues = sorted(d for d in (task_due_dates or []) if d)

    start = project.start_date
    if not start:
        start = dues[0] if dues else _created_date(project)

    end = project.due_date
    if not end:
        end = dues[-1] if dues else None
    if not end or end < start:
        end = start + datetime.timedelta(days=DEFAULT_SPAN_DAYS)

    inferred = not (project.start_date and project.due_date)
    return start, end, inferred


def _created_date(project):
    """作成日時から日付を取り出す。created_at が無い場合は本日。"""
    created = getattr(project, "created_at", None)
    if not created:
        return datetime.date.today()
    return created.date() if hasattr(created, "date") else created


def calc_progress(project, tasks) -> int:
    """タスクの完了割合（％）。タスクが無ければステータスから決める。"""
    total = len(tasks)
    if total == 0:
        return 100 if project.status == "completed" else 0
    done = sum(1 for t in tasks if t.status in DONE_STATUSES)
    return int(done / total * 100)


def get_project_gantt_data(projects) -> list[dict]:
    """開発プロジェクトのガントチャートデータ（frappe-gantt用）。

    Args:
        projects: DevProject の iterable。tasks を prefetch しておくと
            クエリが1回で済む。

    Returns:
        frappe-gantt に渡す dict のリスト。期間の早い順。
    """
    rows = []
    for project in projects:
        tasks = list(project.tasks.all())
        start, end, inferred = resolve_project_period(
            project, [t.due_date for t in tasks]
        )
        css = [f"bar-dev-{project.status}"]
        if inferred:
            css.append("bar-dev-inferred")

        rows.append({
            "id": f"project-{project.pk}",
            "name": project.name,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "progress": calc_progress(project, tasks),
            "custom_class": " ".join(css),
            # 以下はポップアップ表示用。frappe-gantt は未知のキーを保持する。
            "assignee": str(project.assignee) if project.assignee else "未割当",
            "status_label": project.get_status_display(),
            "inferred": inferred,
            "task_total": len(tasks),
            "task_done": sum(1 for t in tasks if t.status in DONE_STATUSES),
            "url": reverse("devkanri:project_detail", args=[project.pk]),
        })

    rows.sort(key=lambda r: (r["start"], r["end"]))
    return rows


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
