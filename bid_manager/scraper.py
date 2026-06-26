"""入札案件のスクレイピング。

scrape_targets テーブルに登録された URL を巡回し、電気工事関連キーワードに
マッチするリンクを案件として projects テーブルに保存する（重複はスキップ）。

取得方式は2系統：
  - 既定: requests + BeautifulSoup（軽量。静的HTML向け）
  - BID_USE_PLAYWRIGHT=1: Playwright（JavaScript描画サイト向け）

実サイトは構造がまちまちなので、ここでは「ページ内アンカー（<a>）のテキストを
キーワードで絞り込む」汎用抽出を行う。サイト個別に精度を上げたい場合は
config.SITE_SELECTORS でCSSセレクタを指定する。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from urllib.parse import urljoin, urlparse

import config
import database as db

# 締め切り日らしき表記を拾うための簡易パターン（例: 2026/06/30, 2026-6-30, 令和は非対応）
_DATE_RE = re.compile(r"(\d{4})[/年.-](\d{1,2})[/月.-](\d{1,2})")


@dataclass
class ScrapedItem:
    title: str
    source_url: str
    region: Optional[str] = None
    category: Optional[str] = None
    deadline: Optional[str] = None
    budget: Optional[int] = None


@dataclass
class ScrapeResult:
    target_name: str
    found: int = 0
    saved: int = 0
    errors: list[str] = field(default_factory=list)


def _matches_keyword(text: str) -> bool:
    return any(kw in text for kw in config.KEYWORDS)


def _guess_region(text: str, fallback: Optional[str]) -> Optional[str]:
    for r in config.REGIONS:
        if r in text:
            return r
    return fallback


def _guess_category(text: str) -> Optional[str]:
    for c in config.CATEGORIES:
        if c in text:
            return c
    # キーワード単体から大まかに推定
    if "照明" in text:
        return "照明設備"
    if "受変電" in text or "幹線" in text or "動力" in text:
        return "受変電設備"
    if "弱電" in text or "配線" in text:
        return "通信・弱電"
    if _matches_keyword(text):
        return "電気工事"
    return None


def _guess_deadline(text: str) -> Optional[str]:
    m = _DATE_RE.search(text)
    if not m:
        return None
    y, mo, d = (int(g) for g in m.groups())
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _fetch_html(url: str) -> str:
    if config.USE_PLAYWRIGHT:
        return _fetch_with_playwright(url)
    return _fetch_with_requests(url)


def _fetch_with_requests(url: str) -> str:
    import requests  # 遅延インポート（未導入でも他機能は動く）

    resp = requests.get(
        url,
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.SCRAPE_TIMEOUT,
    )
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.text


def _fetch_with_playwright(url: str) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=config.USER_AGENT)
        page.goto(url, timeout=config.SCRAPE_TIMEOUT * 1000, wait_until="networkidle")
        html = page.content()
        browser.close()
    return html


def parse_items(html: str, base_url: str) -> list[ScrapedItem]:
    """HTML から案件候補を抽出する。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    domain = urlparse(base_url).netloc
    selectors = config.SITE_SELECTORS.get(domain)

    items: list[ScrapedItem] = []
    seen: set[str] = set()

    def add_from(title: str, href: Optional[str]):
        title = " ".join(title.split())
        if not title or not _matches_keyword(title):
            return
        url = urljoin(base_url, href) if href else base_url
        key = f"{title}|{url}"
        if key in seen:
            return
        seen.add(key)
        items.append(
            ScrapedItem(
                title=title[:200],
                source_url=url,
                region=_guess_region(title, None),
                category=_guess_category(title),
                deadline=_guess_deadline(title),
            )
        )

    if selectors:  # サイト個別セレクタが指定されている場合
        for node in soup.select(selectors.get("item", "a")):
            title_node = node.select_one(selectors["title"]) if "title" in selectors else node
            link_node = node.select_one(selectors["link"]) if "link" in selectors else node
            title = title_node.get_text(strip=True) if title_node else ""
            href = link_node.get("href") if link_node else None
            add_from(title, href)
    else:  # 汎用: アンカーのテキストをキーワードで絞り込む
        for a in soup.find_all("a"):
            add_from(a.get_text(strip=True), a.get("href"))

    return items


def scrape_target(target: "db.sqlite3.Row") -> ScrapeResult:
    result = ScrapeResult(target_name=target["name"])
    try:
        html = _fetch_html(target["url"])
        items = parse_items(html, target["url"])
        result.found = len(items)
        for it in items:
            pid = db.add_project(
                title=it.title,
                region=it.region or target["region"],
                category=it.category,
                deadline=it.deadline,
                budget=it.budget,
                source_url=it.source_url,
            )
            if pid is not None:
                result.saved += 1
        db.mark_target_scraped(target["id"])
    except Exception as exc:  # 1サイト失敗でも全体は止めない
        result.errors.append(f"{target['name']}: {exc}")
    return result


def scrape_all() -> list[ScrapeResult]:
    """有効な全対象を順に巡回し、新着件数などの結果を返す。"""
    db.init_db()
    results: list[ScrapeResult] = []
    targets = db.list_targets(active_only=True)
    for i, target in enumerate(targets):
        results.append(scrape_target(target))
        if i < len(targets) - 1:
            time.sleep(config.SCRAPE_INTERVAL)  # 相手サーバへの配慮
    return results


if __name__ == "__main__":
    for r in scrape_all():
        status = "OK" if not r.errors else f"ERROR: {r.errors}"
        print(f"[{r.target_name}] found={r.found} saved={r.saved} {status}")
