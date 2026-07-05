"""Playwright で Cloudflare 保護サイトにログイン（Cookie 保存）。

初回: ブラウザが開く → Cloudflare チャレンジを手動で通過 → Cookie が保存される。
2回目以降: 保存された Cookie を使って自動アクセスできる。

使い方 (Windows側で実行):
    python pw_login.py                       # Cookie 保存（初回/更新時）
    python pw_login.py --check               # Cookie が有効か確認
    python pw_login.py --scrape              # 保存済み Cookie で案件収集

Cookie は browser_data/ フォルダに永続化される。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BROWSER_DATA = Path(__file__).parent / "browser_data"
TARGETS_FILE = Path(__file__).parent / "pw_targets.json"

# デフォルトのターゲット（scrape_targets に連動させたい場合は pw_targets.json を編集）
DEFAULT_TARGETS = [
    {
        "name": "防衛省 航空自衛隊 調達情報",
        "url": "https://www.mod.go.jp/asdf/choutatsu/",
    },
    {
        "name": "防衛省 海上自衛隊 横須賀 入札",
        "url": "https://www.mod.go.jp/msdf/bukei/y6/nyusatsu.html",
    },
]


def get_targets() -> list[dict]:
    if TARGETS_FILE.exists():
        return json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    return DEFAULT_TARGETS


def login(targets: list[dict] | None = None) -> None:
    """ブラウザを開いて Cloudflare を手動通過させ、Cookie を保存する。"""
    from playwright.sync_api import sync_playwright

    targets = targets or get_targets()
    print(f"ブラウザを開きます。Cloudflare チャレンジを通過してください。")
    print(f"全サイト通過後、ブラウザを閉じると Cookie が保存されます。\n")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(BROWSER_DATA),
            headless=False,
            accept_downloads=True,
            locale="ja-JP",
        )
        page = context.pages[0] if context.pages else context.new_page()

        for t in targets:
            print(f"  → {t['name']}: {t['url']}")
            page.goto(t["url"], timeout=60000, wait_until="domcontentloaded")
            # Cloudflare 通過を待つ
            print(f"    Cloudflare チャレンジを通過してください...")
            try:
                page.wait_for_function(
                    "document.title !== 'Just a moment...' && !document.title.includes('moment')",
                    timeout=120000,
                )
                print(f"    ✅ 通過しました: {page.title()}")
            except Exception:
                print(f"    ⚠️ タイムアウト。手動でページが表示されるまで待ってください。")
                input("    ページが表示されたら Enter を押してください...")

        print(f"\n全サイト完了。ブラウザを閉じてください（または Enter で自動終了）...")
        input()
        context.close()

    print(f"✅ Cookie を {BROWSER_DATA} に保存しました。")


def check() -> bool:
    """保存済み Cookie でアクセスできるか確認する。"""
    from playwright.sync_api import sync_playwright

    if not BROWSER_DATA.exists():
        print("❌ Cookie が保存されていません。先に `python pw_login.py` を実行してください。")
        return False

    targets = get_targets()
    print("保存済み Cookie でアクセスを確認中...\n")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(BROWSER_DATA),
            headless=True,
            locale="ja-JP",
        )
        page = context.pages[0] if context.pages else context.new_page()
        all_ok = True

        for t in targets:
            try:
                page.goto(t["url"], timeout=30000, wait_until="domcontentloaded")
                page.wait_for_timeout(5000)
                title = page.title()
                if "moment" in title.lower() or "challenge" in title.lower():
                    print(f"  ❌ {t['name']}: Cloudflare ブロック中（Cookie 期限切れ）")
                    all_ok = False
                else:
                    print(f"  ✅ {t['name']}: {title}")
            except Exception as e:
                print(f"  ❌ {t['name']}: エラー ({e})")
                all_ok = False

        context.close()

    if all_ok:
        print("\n✅ 全サイト OK — 自動巡回可能です。")
    else:
        print("\n⚠️ 一部サイトで Cookie が無効です。`python pw_login.py` で再ログインしてください。")
    return all_ok


def scrape() -> None:
    """保存済み Cookie を使って案件ページを取得し、DB に保存する。"""
    from playwright.sync_api import sync_playwright
    from bs4 import BeautifulSoup

    # database モジュールをインポート（同じフォルダにある前提）
    sys.path.insert(0, str(Path(__file__).parent))
    import config
    import database as db

    if not BROWSER_DATA.exists():
        print("❌ Cookie が保存されていません。先に `python pw_login.py` を実行してください。")
        return

    db.init_db()
    targets = get_targets()
    print("保存済み Cookie で案件を収集中...\n")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(BROWSER_DATA),
            headless=True,
            locale="ja-JP",
        )
        page = context.pages[0] if context.pages else context.new_page()

        for t in targets:
            print(f"  [{t['name']}] {t['url']}")
            try:
                page.goto(t["url"], timeout=30000, wait_until="domcontentloaded")
                page.wait_for_timeout(5000)
                title = page.title()

                if "moment" in title.lower():
                    print(f"    ❌ Cloudflare ブロック — スキップ")
                    continue

                html = page.content()
                soup = BeautifulSoup(html, "html.parser")

                found = 0
                saved = 0
                for a in soup.find_all("a"):
                    text = " ".join(a.get_text(strip=True).split())
                    href = a.get("href", "")
                    if not text or len(text) < 5:
                        continue
                    if not any(kw in text for kw in config.KEYWORDS):
                        continue

                    from urllib.parse import urljoin
                    full_url = urljoin(t["url"], href) if href else t["url"]
                    found += 1
                    pid = db.add_project(
                        title=text[:200],
                        client=t["name"],
                        source_url=full_url,
                    )
                    if pid is not None:
                        saved += 1

                print(f"    ✅ {title[:40]} — 検出 {found} 件 / 新規 {saved} 件")

            except Exception as e:
                print(f"    ❌ エラー: {e}")

        context.close()

    print("\n完了。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Playwright Cookie管理 + スクレイピング")
    parser.add_argument("--check", action="store_true", help="Cookie の有効性を確認")
    parser.add_argument("--scrape", action="store_true", help="保存済み Cookie で案件収集")
    args = parser.parse_args()

    if args.check:
        check()
    elif args.scrape:
        scrape()
    else:
        login()
