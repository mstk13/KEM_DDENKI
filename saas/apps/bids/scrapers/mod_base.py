"""防衛省（自衛隊基地）の入札公告スクレイパー。

Cloudflare対策としてPlaywright（headless Chromium）を使用。
各基地の入札公告ページからテーブルを解析し、案件を取得する。

対象例:
- 海自横須賀: https://www.mod.go.jp/msdf/bukei/t2/nyusatsu.html
"""

import logging
import re
import time
from datetime import date, datetime

from apps.bids.scrapers import BidInfo, register

logger = logging.getLogger(__name__)

# 基地ごとのURL設定
MOD_BASE_URLS = {
    # 海上自衛隊
    "msdf_hokyuhonbu": {
        "url": "https://www.mod.go.jp/msdf/bukei/t2/nyusatsu.html",
        "client": "海上自衛隊 補給本部",
        "region": "東京都",
    },
    "msdf_yokosuka": {
        "url": "https://www.mod.go.jp/msdf/bukei/y0/nyusatsu.html",
        "client": "海上自衛隊 横須賀基地",
        "region": "神奈川県",
    },
    "msdf_chichijima": {
        "url": "https://www.mod.go.jp/msdf/bukei/yt/nyusatsu.html",
        "client": "海上自衛隊 父島基地",
        "region": "東京都",
    },
    "msdf_atsugi": {
        "url": "https://www.mod.go.jp/msdf/bukei/y6/nyuusatsu/ns-list.htm",
        "client": "海上自衛隊 厚木航空基地隊",
        "region": "神奈川県",
        "frameset": True,
    },
}


def _parse_date_dot(text: str) -> date | None:
    """「2026.09.01」「R9.3.26」形式の日付をパースする。"""
    if not text:
        return None
    text = text.strip()
    # 西暦: 2026.09.01
    m = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    # 令和短縮: R9.3.26 or R09.03.26
    m = re.match(r"[Rr](\d{1,2})\.(\d{1,2})\.(\d{1,2})", text)
    if m:
        try:
            return date(2018 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def scrape_mod_base(target) -> list[dict]:
    """防衛省基地の入札公告ページをスクレイピングする。

    Playwright で Cloudflare を突破し、テーブルから案件を抽出する。

    Args:
        target: ScrapeTarget インスタンス

    Returns:
        list[dict]: 案件のリスト（i-ppi と同じ形式）
    """
    from playwright.sync_api import sync_playwright

    config = MOD_BASE_URLS.get(target.site_key, {})
    url = config.get("url") or target.url
    client = config.get("client", "防衛省")
    region = config.get("region", "")

    if not url:
        logger.warning(f"[{target.site_key}] URLが設定されていません")
        return []

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        page.add_init_script(
            'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
        )

        try:
            logger.info(f"[{target.site_key}] {url} を開きます...")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Cloudflareチャレンジ待ち
            for _ in range(10):
                time.sleep(2)
                title = page.title()
                if "moment" not in title.lower() and "403" not in title:
                    break

            if "403" in page.title():
                logger.error(f"[{target.site_key}] Cloudflare 403 でブロックされました")
                return []

            from bs4 import BeautifulSoup

            # フレームセット対応（Excel HTML形式のページ）
            if config.get("frameset"):
                page.wait_for_load_state("load")
                time.sleep(3)
                sheet_frame = next(
                    (f for f in page.frames if "sheet" in f.url), None,
                )
                if sheet_frame:
                    content = sheet_frame.content()
                else:
                    content = page.content()
            else:
                content = page.content()

            soup = BeautifulSoup(content, "html.parser")

            # 案件テーブルを探す（「件名」を含むヘッダー行を探す）
            for table in soup.find_all("table"):
                rows = table.find_all("tr")
                if len(rows) < 3:
                    continue

                # ヘッダー行を探す（「件名」を含む行）
                header_row_idx = None
                headers = []
                for ri, row in enumerate(rows):
                    cells = row.find_all(["th", "td"])
                    texts = [c.get_text(strip=True).replace("\u3000", "") for c in cells]
                    if any("件名" in t for t in texts):
                        headers = texts
                        header_row_idx = ri
                        break

                if header_row_idx is None:
                    continue

                # カラムインデックスを特定
                name_idx = next(
                    (i for i, h in enumerate(headers) if "件名" in h),
                    None,
                )
                if name_idx is None:
                    continue

                date_idx = next(
                    (i for i, h in enumerate(headers) if "入札" in h and "日" in h),
                    None,
                )
                delivery_idx = next(
                    (i for i, h in enumerate(headers) if "納期" in h or "履行" in h),
                    None,
                )
                contract_idx = next(
                    (i for i, h in enumerate(headers)
                     if "契約管理" in h or "調達要求" in h),
                    None,
                )
                category_idx = next(
                    (i for i, h in enumerate(headers) if "資格" in h and "種類" in h),
                    None,
                )

                for row in rows[header_row_idx + 1:]:
                    cells = row.find_all("td")
                    if len(cells) < 3:
                        continue

                    # 全セルのテキストを取得
                    cell_texts = [c.get_text(strip=True) for c in cells]

                    # 件名を探す: name_idx を試し、だめなら最長のテキストセル
                    title = ""
                    name_cell = None
                    if name_idx < len(cells):
                        candidate = cell_texts[name_idx]
                        if len(candidate) >= 3:
                            title = candidate
                            name_cell = cells[name_idx]

                    if not title:
                        # 最長の非数値テキストを件名とみなす
                        best_len = 0
                        for ci, ct in enumerate(cell_texts):
                            if (len(ct) > best_len
                                    and not re.fullmatch(r"[\d.Rr\-/]+", ct)
                                    and ct not in ("免除", "役務", "物品")):
                                best_len = len(ct)
                                title = ct
                                name_cell = cells[ci]

                    if not title or len(title) < 3:
                        continue
                    # ヘッダー行・注記・番号だけの行を除外
                    skip_words = ("件名", "番号", "資格の種類", "調達要求", "適用する",
                                  "以下余白")
                    if any(title.startswith(w) for w in skip_words):
                        continue
                    if re.fullmatch(r"\d{1,3}", title):
                        continue
                    # 契約管理番号が件名になっている場合、同じ行の他セルから件名を探す
                    if re.match(r"G\d{2}-[SN]\d{2}-", title):
                        real_title = ""
                        for ci, ct in enumerate(cell_texts):
                            if (len(ct) > len(real_title)
                                    and not re.match(r"G\d{2}-[SN]\d{2}-", ct)
                                    and not re.fullmatch(r"[\d.Rr\-/]+", ct)
                                    and ct not in ("免除", "役務", "物品", "1式")
                                    and len(ct) >= 4):
                                real_title = ct
                                name_cell = cells[ci]
                        if real_title:
                            title = real_title
                        else:
                            continue
                    # お知らせ・注記を除外
                    if title.startswith("※") or title.startswith("①") or title.startswith("②"):
                        continue
                    if title.startswith("（注）") or title.startswith("令和"):
                        continue

                    # PDFリンク
                    href = ""
                    if name_cell:
                        link = name_cell.find("a")
                        if link:
                            raw_href = link.get("href", "")
                            if raw_href:
                                from urllib.parse import urljoin
                                href = urljoin(url, raw_href)

                    # 日付を全セルから探す（入札日を優先）
                    dates_found = []
                    for ct in cell_texts:
                        d = _parse_date_dot(ct)
                        if d:
                            dates_found.append(d)

                    # 入札日（最も近い未来の日付）または最初の日付
                    deadline = None
                    if dates_found:
                        from datetime import date as _today_date
                        today = _today_date.today()
                        future = [d for d in dates_found if d >= today]
                        deadline = min(future) if future else min(dates_found)

                    # 契約管理番号
                    contract_no = ""
                    for ct in cell_texts:
                        if re.match(r"G\d{2}-[SN]\d{2}-", ct):
                            contract_no = ct
                            break

                    # 資格の種類（物品/役務）
                    bid_category = "物品・役務"
                    for ct in cell_texts:
                        if ct in ("役務", "物品"):
                            bid_category = ct
                            break

                    from apps.bids.scraper import _empty_record

                    rec = _empty_record()
                    rec.update({
                        "title": title,
                        "client": client,
                        "region": region,
                        "category": bid_category,
                        "deadline": deadline.isoformat() if deadline else None,
                        "source_url": href,
                        "design_no": contract_no,
                    })
                    results.append(rec)

                logger.info(
                    f"[{target.site_key}] {len(results)} 件の案件を取得しました"
                )
                break  # 最初の案件テーブルのみ

        except Exception:
            logger.exception(f"[{target.site_key}] スクレイピングエラー")
            raise
        finally:
            browser.close()

    return results
