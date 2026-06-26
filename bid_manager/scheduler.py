"""定期実行スクリプト。

毎朝 cron / GitHub Actions から呼ぶ想定。
  1) 全対象サイトをスクレイピング
  2) 新着案件があればメール通知

cron 例（毎朝6時）:
  0 6 * * * cd /path/to/bid_manager && /path/to/venv/bin/python scheduler.py >> scrape.log 2>&1
"""
from __future__ import annotations

import sys

import config
import database as db
import scraper
from notifier import notify_new_projects


def run(send_mail: bool = True) -> int:
    db.init_db()

    # スクレイピング前の最大IDを記録し、これより新しいものを「新着」とみなす
    before = db.list_projects(order_by="created")
    before_ids = {p["id"] for p in before}

    results = scraper.scrape_all()
    total_saved = sum(r.saved for r in results)
    for r in results:
        status = "OK" if not r.errors else f"ERROR: {'; '.join(r.errors)}"
        print(f"[{r.target_name}] found={r.found} saved={r.saved} {status}")

    after = db.list_projects(order_by="created")
    new_ids = [p["id"] for p in after if p["id"] not in before_ids]

    print(f"合計 新着 {len(new_ids)} 件 / 保存 {total_saved} 件")

    if send_mail and new_ids:
        try:
            notify_new_projects(new_ids)
            print(f"メール通知を送信しました -> {', '.join(config.EMAIL_TO)}")
        except Exception as exc:
            print(f"メール送信に失敗: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    no_mail = "--no-mail" in sys.argv
    raise SystemExit(run(send_mail=not no_mail))
