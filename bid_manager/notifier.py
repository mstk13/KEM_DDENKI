"""メール通知（Gmail SMTP）。

スクレイピング後に、新着案件の一覧と締め切り間近アラートをメール送信する。
認証情報は .env（GMAIL_USER / GMAIL_PASSWORD）から読む。
"""
from __future__ import annotations

import smtplib
import sqlite3
from email.mime.text import MIMEText
from typing import Sequence

import config
import database as db


def _format_project_line(p: sqlite3.Row) -> str:
    budget = f"{p['budget']:,}円" if p["budget"] else "予定価格未記載"
    deadline = p["deadline"] or "締切未定"
    return (
        f"・{p['title']}\n"
        f"    発注機関: {p['client'] or '不明'} / エリア: {p['region'] or '不明'}\n"
        f"    締切: {deadline} / {budget}\n"
        f"    {p['source_url'] or ''}"
    )


def build_body(new_projects: Sequence[sqlite3.Row]) -> str:
    lines: list[str] = []
    lines.append(f"本日の新着入札案件: {len(new_projects)} 件\n")

    if new_projects:
        lines.append("■ 新着案件一覧")
        lines.extend(_format_project_line(p) for p in new_projects)
        lines.append("")

    # 締め切り間近アラート
    soon = db.list_projects(within_days=config.DEADLINE_ALERT_DAYS, order_by="deadline")
    soon = [p for p in soon if p["status"] in config.OPEN_STATUSES]
    if soon:
        lines.append(f"■ 締め切り {config.DEADLINE_ALERT_DAYS} 日以内の要対応案件")
        lines.extend(_format_project_line(p) for p in soon)

    return "\n".join(lines) if lines else "本日の新着案件はありませんでした。"


def send_email(subject: str, body: str) -> None:
    if not (config.EMAIL_FROM and config.EMAIL_PASSWORD and config.EMAIL_TO):
        raise RuntimeError(
            "メール設定が不足しています（GMAIL_USER / GMAIL_PASSWORD / BID_EMAIL_TO を .env に設定）"
        )
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = ", ".join(config.EMAIL_TO)

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
        server.starttls()
        server.login(config.EMAIL_FROM, config.EMAIL_PASSWORD)
        server.sendmail(config.EMAIL_FROM, config.EMAIL_TO, msg.as_string())


def notify_new_projects(new_project_ids: Sequence[int]) -> str:
    """新着案件IDのリストから本文を作って送信。本文を返す（ログ用）。"""
    rows = [db.get_project(pid) for pid in new_project_ids]
    rows = [r for r in rows if r is not None]
    body = build_body(rows)
    send_email(config.EMAIL_SUBJECT, body)
    return body


if __name__ == "__main__":
    # 直近の新着（未処理）案件でプレビュー送信
    recent = db.list_projects(status="新着", order_by="created")
    print(build_body(recent))
