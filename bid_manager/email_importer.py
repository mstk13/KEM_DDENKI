"""GEPS 調達情報通知メールを Gmail から取得し、案件として DB に登録する。

GEPS（政府電子調達）の通知機能で届くメールを IMAP で取得し、
案件情報をパースして projects テーブルに保存する。

前提:
  - GEPS で「調達情報通知」の条件を設定済み（電気工事等のキーワードで）
  - Gmail の .env に GMAIL_USER / GMAIL_PASSWORD を設定済み
  - Gmail で IMAP を有効化済み
  - GMAIL_PASSWORD は「アプリパスワード」（2段階認証が必要）

使い方:
    python email_importer.py                 # 未読の GEPS 通知を取り込み
    python email_importer.py --days 7        # 過去7日分を取り込み
    python email_importer.py --dry-run       # DB保存せずプレビューのみ
"""
from __future__ import annotations

import argparse
import email
import imaplib
import re
from datetime import date, datetime, timedelta
from email.header import decode_header
from typing import Optional

import config
import database as db


def _decode_subject(msg: email.message.Message) -> str:
    """メールの Subject をデコードする。"""
    raw = msg.get("Subject", "")
    parts = decode_header(raw)
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _decode_body(msg: email.message.Message) -> str:
    """メール本文をテキストとして取得する。"""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return ""


def _parse_geps_body(body: str) -> list[dict]:
    """GEPS 通知メール本文から案件情報を抽出する。

    GEPS の通知メール形式（想定）:
    ─────────────────
    調達案件名: ○○電気設備改修工事
    調達機関: 防衛省
    所在地: 東京都
    入札方式: 一般競争入札
    締切日: 2026/08/15
    URL: https://...
    ─────────────────
    """
    records: list[dict] = []
    current: dict = {}

    # パターン1: GEPS 通知の典型的なフィールド
    field_patterns = {
        "title": re.compile(r"(?:調達案件名|件名|案件名)\s*[:：]\s*(.+)"),
        "client": re.compile(r"(?:調達機関|発注機関|機関名)\s*[:：]\s*(.+)"),
        "region": re.compile(r"(?:所在地|地域|エリア|履行場所)\s*[:：]\s*(.+)"),
        "category": re.compile(r"(?:業種|種目|工種)\s*[:：]\s*(.+)"),
        "deadline": re.compile(r"(?:締切日|入札日|開札日|提出期限)\s*[:：]\s*(.+)"),
        "url": re.compile(r"(?:URL|詳細|リンク)\s*[:：]\s*(https?://\S+)"),
    }

    # 区切り線パターン
    separator = re.compile(r"^[-─━=]{3,}$")

    for line in body.splitlines():
        line = line.strip()

        # 区切り線で新しいレコード
        if separator.match(line):
            if current.get("title"):
                records.append(current)
            current = {}
            continue

        for field, pattern in field_patterns.items():
            m = pattern.match(line)
            if m:
                current[field] = m.group(1).strip()
                break

    # 最後のレコード
    if current.get("title"):
        records.append(current)

    # パターン2: 本文にURLが含まれる場合、全体を1件として扱う
    if not records:
        urls = re.findall(r"https?://\S+", body)
        # 電気工事関連のキーワードを含む行を案件名候補にする
        for line in body.splitlines():
            line = line.strip()
            if any(kw in line for kw in config.KEYWORDS) and len(line) > 5:
                records.append({
                    "title": line[:200],
                    "url": urls[0] if urls else None,
                })
                break

    # 締切日のパース
    date_re = re.compile(r"(\d{4})[/年.-](\d{1,2})[/月.-](\d{1,2})")
    for rec in records:
        raw_deadline = rec.pop("deadline", None)
        if raw_deadline:
            m = date_re.search(raw_deadline)
            if m:
                try:
                    rec["deadline"] = date(
                        int(m.group(1)), int(m.group(2)), int(m.group(3))
                    ).isoformat()
                except ValueError:
                    pass

        # region をエリアリストと照合
        raw_region = rec.get("region", "")
        rec["region"] = None
        for r in config.REGIONS:
            if r in raw_region:
                rec["region"] = r
                break

        # URL フィールド名を source_url に変換
        if "url" in rec:
            rec["source_url"] = rec.pop("url")

    return records


def fetch_geps_emails(
    days: int = 1,
    mark_read: bool = True,
) -> list[dict]:
    """Gmail から GEPS 通知メールを取得し、案件リストを返す。"""
    if not config.EMAIL_FROM or not config.EMAIL_PASSWORD:
        raise RuntimeError(
            "GMAIL_USER / GMAIL_PASSWORD が .env に設定されていません。"
        )

    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")

    print(f"Gmail に IMAP 接続中...")
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(config.EMAIL_FROM, config.EMAIL_PASSWORD)
    mail.select("INBOX")

    # GEPS からのメールを検索
    # 送信元や件名に「調達」「GEPS」「p-portal」を含むメールを探す
    search_queries = [
        f'(SINCE {since} SUBJECT "調達")',
        f'(SINCE {since} FROM "geps")',
        f'(SINCE {since} FROM "p-portal")',
        f'(SINCE {since} SUBJECT "入札")',
    ]

    msg_ids: set[bytes] = set()
    for query in search_queries:
        try:
            _, data = mail.search(None, query)
            if data[0]:
                msg_ids.update(data[0].split())
        except Exception:
            pass

    print(f"  対象メール: {len(msg_ids)} 件\n")

    all_records: list[dict] = []

    for mid in sorted(msg_ids):
        _, data = mail.fetch(mid, "(RFC822)")
        raw = data[0][1]
        msg = email.message_from_bytes(raw)

        subject = _decode_subject(msg)
        body = _decode_body(msg)
        from_addr = msg.get("From", "")

        print(f"  📧 {subject}")
        print(f"     From: {from_addr}")

        records = _parse_geps_body(body)
        if records:
            print(f"     → {len(records)} 件の案件を検出")
            for rec in records:
                rec.setdefault("client", subject[:50])
                all_records.append(rec)
        else:
            print(f"     → 案件情報なし（スキップ）")

        if mark_read:
            mail.store(mid, "+FLAGS", "\\Seen")

    mail.close()
    mail.logout()

    return all_records


def import_from_email(days: int = 1, dry_run: bool = False) -> int:
    """GEPS メールから案件を取得して DB に保存する。"""
    db.init_db()
    records = fetch_geps_emails(days=days, mark_read=not dry_run)

    if not records:
        print("取り込み対象の案件はありませんでした。")
        return 0

    saved = 0
    for rec in records:
        title = rec.get("title", "")
        if not title:
            continue

        if dry_run:
            print(f"  [DRY-RUN] {title}")
            print(f"            {rec}")
            continue

        pid = db.add_project(
            title=title,
            client=rec.get("client"),
            region=rec.get("region"),
            category=rec.get("category"),
            deadline=rec.get("deadline"),
            source_url=rec.get("source_url"),
        )
        if pid:
            saved += 1
            print(f"  ✅ 保存: {title} (ID: {pid})")
        else:
            print(f"  ⏭️ 重複: {title}")

    print(f"\n完了: {saved} 件を新規保存しました。")
    return saved


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GEPS 通知メールから案件を取り込み")
    parser.add_argument("--days", type=int, default=1, help="過去何日分を取得（デフォルト: 1）")
    parser.add_argument("--dry-run", action="store_true", help="DB保存せずプレビューのみ")
    args = parser.parse_args()

    import_from_email(days=args.days, dry_run=args.dry_run)
