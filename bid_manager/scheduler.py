"""定期実行スクリプト。

毎朝 cron / タスクスケジューラ から呼ぶ想定。
  1) 全対象サイトをスクレイピング（requests/BS4）
  2) GEPS 通知メールから案件を取り込み
  3) 新着案件があればメール通知（資格期限アラート含む）

cron 例（毎朝6時）:
  0 6 * * * cd /path/to/bid_manager && /path/to/venv/bin/python scheduler.py >> scrape.log 2>&1

Windows タスクスケジューラ:
  python scheduler.py
  python scheduler.py --with-playwright   # Cloudflare サイトも巡回
"""
from __future__ import annotations

import sys

import config
import database as db
import scraper
from notifier import notify_new_projects


def run(send_mail: bool = True, with_playwright: bool = False) -> int:
    db.init_db()

    # スクレイピング前の最大IDを記録し、これより新しいものを「新着」とみなす
    before = db.list_projects(order_by="created")
    before_ids = {p["id"] for p in before}

    # --- 1) 通常のスクレイピング ---
    results = scraper.scrape_all()
    total_saved = sum(r.saved for r in results)
    for r in results:
        status = "OK" if not r.errors else f"ERROR: {'; '.join(r.errors)}"
        print(f"[scraper] [{r.target_name}] found={r.found} saved={r.saved} {status}")

    # --- 2) GEPS メール取り込み ---
    try:
        import email_importer
        email_saved = email_importer.import_from_email(days=1, dry_run=False)
        print(f"[email] GEPS メールから {email_saved} 件を新規保存")
    except Exception as exc:
        print(f"[email] メール取り込み失敗（スキップ）: {exc}")

    # --- 3) Playwright で Cloudflare サイト巡回（オプション）---
    if with_playwright:
        try:
            import pw_login
            pw_login.scrape()
        except Exception as exc:
            print(f"[playwright] 巡回失敗（スキップ）: {exc}")

    # --- 新着判定 ---
    after = db.list_projects(order_by="created")
    new_ids = [p["id"] for p in after if p["id"] not in before_ids]

    print(f"\n合計 新着 {len(new_ids)} 件")

    # --- 4) メール通知 ---
    if send_mail and (new_ids or db.list_qualifications_expiring(within_days=60)):
        try:
            notify_new_projects(new_ids)
            print(f"メール通知を送信しました -> {', '.join(config.EMAIL_TO)}")
        except Exception as exc:
            print(f"メール送信に失敗: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    no_mail = "--no-mail" in sys.argv
    pw = "--with-playwright" in sys.argv
    raise SystemExit(run(send_mail=not no_mail, with_playwright=pw))
