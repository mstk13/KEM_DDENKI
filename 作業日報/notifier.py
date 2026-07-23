"""メール通知（Gmail SMTP）。

指定日の日報（1現場×1日で1枚）をまとめて送信する。新着が無ければ送信しない。

    python notifier.py                 # 本日分の日報サマリを送信
    python notifier.py --date 2026-07-01

前提: .env に GMAIL_USER / GMAIL_PASSWORD（アプリパスワード） / NIPPOU_EMAIL_TO を設定。
"""
from __future__ import annotations

import smtplib
import sys
from datetime import date
from email.mime.text import MIMEText

import config
import database as db


def build_summary(target_date: str) -> tuple[str, int]:
    reports = db.list_reports(date_from=target_date, date_to=target_date)
    if not reports:
        return "", 0

    total_hours = sum(r["total_hours"] for r in reports)
    total_people = sum(r["worker_count"] + r["sub_headcount"] for r in reports)
    wd = config.weekday_jp(target_date)
    lines = [
        f"■ {config.COMPANY_NAME} 作業日報サマリ",
        f"日付: {target_date}（{wd}）",
        f"日報: {len(reports)} 枚 / のべ {total_people} 名 / 総作業時間 {total_hours:.1f} 時間",
        "",
        "―" * 20,
    ]
    for r in reports:
        workers = db.get_report_workers(r["id"])
        subs = db.get_report_subcontractors(r["id"])
        lines.append(f"【{r['site_name']}】発注先: {r['client'] or '-'} / 責任者: {r['manager'] or '-'}")
        names = "、".join(w["worker_name"] for w in workers) or "-"
        lines.append(f"  自社: {names}（作業時間 {r['total_hours']:.1f}h・残業 {r['total_overtime']:.1f}h）")
        if subs:
            for s in subs:
                lines.append(f"  協力: {s['company_name']} {s['worker_name']}（{s['headcount']}名）")
        if r["work_content"]:
            lines.append(f"  作業内容: {r['work_content']}")
        lines.append(f"  交通費合計: {r['total_transport_cost']:,} 円")
        lines.append("")
    return "\n".join(lines), len(reports)


def send_email(subject: str, body: str) -> None:
    if not (config.EMAIL_FROM and config.EMAIL_PASSWORD and config.EMAIL_TO):
        raise RuntimeError(
            "メール設定が未完了です。.env に GMAIL_USER / GMAIL_PASSWORD / NIPPOU_EMAIL_TO を設定してください。"
        )
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = ", ".join(config.EMAIL_TO)
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
        server.starttls()
        server.login(config.EMAIL_FROM, config.EMAIL_PASSWORD)
        server.sendmail(config.EMAIL_FROM, config.EMAIL_TO, msg.as_string())


def notify(target_date: str | None = None) -> int:
    target_date = target_date or date.today().isoformat()
    body, count = build_summary(target_date)
    if count == 0:
        print(f"{target_date} の日報はありません。送信をスキップします。")
        return 0
    send_email(f"{config.EMAIL_SUBJECT}（{target_date}）", body)
    print(f"{target_date} の日報 {count} 枚を {', '.join(config.EMAIL_TO)} に送信しました。")
    return count


if __name__ == "__main__":
    args = sys.argv[1:]
    d = args[args.index("--date") + 1] if "--date" in args else None
    notify(d)
