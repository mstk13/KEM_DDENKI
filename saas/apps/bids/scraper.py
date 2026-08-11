"""入札情報サービス (i-ppi.jp) スクレイパー。

Playwright を使って以下を自動化する:
1. 工事の検索画面 (tab=3) を開く
2. ScrapeTarget の検索条件をフォームに入力
3. 検索ボタンをクリック
4. 結果テーブルをパースして dict のリストで返す

使い方:
    from apps.bids.scraper import scrape_ippi
    results = scrape_ippi(target)  # ScrapeTarget インスタンス
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

SEARCH_URL = (
    "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=3"
)


def scrape_ippi(
    target,
    *,
    headless: bool = True,
    timeout_ms: int = 60_000,
) -> list[dict]:
    """ScrapeTarget の条件で i-ppi.jp を検索し、結果を返す。

    Args:
        target: ScrapeTarget モデルインスタンス（keyword, region, prefecture, category, days_back）
        headless: ヘッドレスモードで実行するか
        timeout_ms: ページ操作のタイムアウト（ミリ秒）

    Returns:
        list[dict]: パースされた入札案件のリスト
    """
    from playwright.sync_api import sync_playwright

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.set_default_timeout(timeout_ms)

        try:
            logger.info("i-ppi.jp 検索ページを開きます...")
            page.goto(target.url or SEARCH_URL, wait_until="networkidle")

            # --- フォーム入力 ---
            _fill_form(page, target)

            # --- 検索実行 ---
            logger.info("検索を実行します...")
            _click_search(page)

            # --- 結果パース ---
            results = _parse_results(page)
            logger.info(f"{len(results)} 件の案件を取得しました")

        except Exception:
            logger.exception("スクレイピング中にエラーが発生しました")
            raise
        finally:
            browser.close()

    return results


def _fill_form(page, target) -> None:
    """検索フォームに条件を入力する。"""

    # 工事名キーワード
    if target.keyword:
        keyword_input = page.locator("input[type='text']").first
        keyword_input.fill(target.keyword)
        logger.info(f"キーワード: {target.keyword}")

    # 工事種別（セレクトボックスがある場合）
    if target.category:
        try:
            # 工事種別のセレクトボックスを探す
            category_selects = page.locator("select")
            count = category_selects.count()
            for i in range(count):
                sel = category_selects.nth(i)
                # option のテキストに工事種別が含まれるセレクトを探す
                options_text = sel.inner_text()
                if "電気" in options_text or "建築" in options_text or "土木" in options_text:
                    # マッチする option を選択
                    options = sel.locator("option")
                    for j in range(options.count()):
                        opt = options.nth(j)
                        if target.category in (opt.inner_text() or ""):
                            sel.select_option(label=opt.inner_text().strip())
                            logger.info(f"工事種別: {target.category}")
                            break
                    break
        except Exception:
            logger.warning("工事種別の設定に失敗しました（フォーム構造が想定と異なる可能性）")

    # 地域（地方）
    if target.region:
        try:
            selects = page.locator("select")
            count = selects.count()
            for i in range(count):
                sel = selects.nth(i)
                options_text = sel.inner_text()
                if "北海道" in options_text and "東北" in options_text:
                    options = sel.locator("option")
                    for j in range(options.count()):
                        opt = options.nth(j)
                        if target.region in (opt.inner_text() or ""):
                            sel.select_option(label=opt.inner_text().strip())
                            logger.info(f"地域: {target.region}")
                            break
                    break
        except Exception:
            logger.warning("地域の設定に失敗しました")

    # 都道府県（地域選択後に表示される連動セレクト）
    if target.prefecture:
        try:
            page.wait_for_timeout(1000)  # 連動セレクトの読込待ち
            selects = page.locator("select")
            count = selects.count()
            for i in range(count):
                sel = selects.nth(i)
                options_text = sel.inner_text()
                if target.prefecture in options_text:
                    sel.select_option(label=target.prefecture)
                    logger.info(f"都道府県: {target.prefecture}")
                    break
        except Exception:
            logger.warning("都道府県の設定に失敗しました")

    # 最終更新日（過去N日以内）
    if target.days_back:
        try:
            # 「過去N日以内」のラジオボタンまたは入力欄を探す
            radio_buttons = page.locator("input[type='radio']")
            count = radio_buttons.count()
            for i in range(count):
                radio = radio_buttons.nth(i)
                # ラジオボタンの隣接テキストを確認
                parent = radio.locator("..")
                text = parent.inner_text()
                if "日以内" in text or "過去" in text:
                    radio.check()
                    # 日数入力欄があれば入力
                    day_input = parent.locator("input[type='text']")
                    if day_input.count() > 0:
                        day_input.first.fill(str(target.days_back))
                    logger.info(f"最終更新日: 過去{target.days_back}日以内")
                    break
        except Exception:
            logger.warning("最終更新日の設定に失敗しました")


def _click_search(page) -> None:
    """検索ボタンをクリックして結果を待つ。"""
    # 検索ボタンを探す（テキストまたは value で判定）
    search_btn = None

    # input[type='button'] or input[type='submit'] で「検索」を含むもの
    buttons = page.locator("input[type='button'], input[type='submit']")
    count = buttons.count()
    for i in range(count):
        btn = buttons.nth(i)
        value = btn.get_attribute("value") or ""
        if "検索" in value:
            search_btn = btn
            break

    if not search_btn:
        # <button> タグで探す
        btn_tags = page.locator("button")
        for i in range(btn_tags.count()):
            btn = btn_tags.nth(i)
            if "検索" in (btn.inner_text() or ""):
                search_btn = btn
                break

    if not search_btn:
        # <a> タグで探す
        links = page.locator("a")
        for i in range(links.count()):
            link = links.nth(i)
            if "検索" in (link.inner_text() or ""):
                search_btn = link
                break

    if search_btn:
        search_btn.click()
        # 結果ページの読み込みを待つ
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)  # 追加の描画待ち
    else:
        logger.warning("検索ボタンが見つかりませんでした")


def _parse_results(page) -> list[dict]:
    """検索結果テーブルをパースする。"""
    results = []

    # テーブルを探す
    tables = page.locator("table")
    result_table = None
    count = tables.count()

    for i in range(count):
        table = tables.nth(i)
        text = table.inner_text()
        # 結果テーブルの特徴的なヘッダーを探す
        if "案件名" in text or "工事名" in text or "件名" in text:
            result_table = table
            break

    if not result_table:
        logger.warning("結果テーブルが見つかりませんでした")
        # ページ全体のテキストからリンクを探すフォールバック
        return _parse_results_fallback(page)

    rows = result_table.locator("tr")
    row_count = rows.count()

    # ヘッダー行を特定
    headers = []
    data_start = 0
    for i in range(min(row_count, 3)):
        row = rows.nth(i)
        ths = row.locator("th")
        if ths.count() > 0:
            headers = [th.inner_text().strip() for th in ths.all()]
            data_start = i + 1
            break

    if not headers:
        # th がない場合、最初の tr をヘッダーとして扱う
        first_row = rows.nth(0)
        headers = [td.inner_text().strip() for td in first_row.locator("td").all()]
        data_start = 1

    logger.info(f"テーブルヘッダー: {headers}")

    for i in range(data_start, row_count):
        row = rows.nth(i)
        tds = row.locator("td")
        if tds.count() == 0:
            continue

        cells = [td.inner_text().strip() for td in tds.all()]

        # リンクから詳細URLを取得
        link = row.locator("a").first
        detail_url = ""
        if link.count() > 0:
            detail_url = link.get_attribute("href") or ""
            if detail_url and not detail_url.startswith("http"):
                detail_url = f"https://www.i-ppi.jp{detail_url}"

        record = _map_cells_to_record(headers, cells, detail_url)
        if record and record.get("title"):
            results.append(record)

    return results


def _parse_results_fallback(page) -> list[dict]:
    """テーブルが見つからない場合のフォールバックパーサー。"""
    results = []
    # リンクテキストから案件情報を抽出
    links = page.locator("a")
    for i in range(links.count()):
        link = links.nth(i)
        text = (link.inner_text() or "").strip()
        href = link.get_attribute("href") or ""
        # 案件リンクらしいものをフィルタ
        if len(text) > 10 and ("工事" in text or "業務" in text or "電気" in text):
            if not href.startswith("http"):
                href = f"https://www.i-ppi.jp{href}"
            results.append({
                "title": text,
                "client": "",
                "region": "",
                "category": "",
                "deadline": None,
                "budget": 0,
                "source_url": href,
            })
    return results


def _map_cells_to_record(
    headers: list[str], cells: list[str], detail_url: str
) -> Optional[dict]:
    """ヘッダーとセルの値からレコード dict にマッピングする。"""
    if len(cells) == 0:
        return None

    record = {
        "title": "",
        "client": "",
        "region": "",
        "category": "",
        "deadline": None,
        "budget": 0,
        "source_url": detail_url,
        "required_grade": "",
        "required_category": "",
        "required_issuer_type": "",
    }

    for idx, header in enumerate(headers):
        if idx >= len(cells):
            break
        val = cells[idx]

        if "案件" in header or "件名" in header or "工事名" in header:
            record["title"] = val
        elif "発注" in header or "機関" in header:
            record["client"] = val
        elif "場所" in header or "地域" in header:
            record["region"] = val
        elif "種別" in header or "業種" in header or "工種" in header:
            record["category"] = val
        elif "期限" in header or "締切" in header or "開札" in header:
            record["deadline"] = _parse_date(val)
        elif "予定価格" in header or "金額" in header:
            record["budget"] = _parse_amount(val)
        elif "等級" in header or "格付" in header:
            record["required_grade"] = _extract_grade(val)

    # タイトルが空なら最初の長いセルをタイトルにする
    if not record["title"]:
        for cell in cells:
            if len(cell) > 5:
                record["title"] = cell
                break

    # 全セルのテキストから等級を推測（ヘッダーで取れなかった場合）
    if not record["required_grade"]:
        all_text = " ".join(cells)
        record["required_grade"] = _extract_grade(all_text)

    return record


def _parse_date(text: str) -> Optional[str]:
    """日付文字列を ISO format に変換する。"""
    if not text:
        return None
    # 2025/04/01 or 2025-04-01
    m = re.search(r"(\d{4})[/\-年.](\d{1,2})[/\-月.](\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            pass
    # 令和7年4月1日
    m = re.search(r"令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日", text)
    if m:
        try:
            return date(
                2018 + int(m.group(1)), int(m.group(2)), int(m.group(3))
            ).isoformat()
        except ValueError:
            pass
    return None


def _parse_amount(text: str) -> int:
    """金額文字列から整数を返す。"""
    if not text:
        return 0
    cleaned = re.sub(r"[^\d]", "", text)
    return int(cleaned) if cleaned else 0


def _extract_grade(text: str) -> str:
    """テキストから等級（A/B/C/D）を抽出する。

    対応パターン:
      - 「Ａ等級」「A等級」「Ａ級」
      - 「Ｄ等級以上」「D等級以上」
      - 「格付：A」
    """
    if not text:
        return ""
    # 全角→半角変換
    normalized = text.translate(str.maketrans("ＡＢＣＤ", "ABCD"))
    # 「X等級以上」→ 最低等級 X を返す
    m = re.search(r"([A-D])\s*等?級?\s*以上", normalized)
    if m:
        return m.group(1)
    # 「X等級」単独
    m = re.search(r"([A-D])\s*等?級", normalized)
    if m:
        return m.group(1)
    # 「格付：A」
    m = re.search(r"格付[：:]?\s*([A-D])", normalized)
    if m:
        return m.group(1)
    return ""


def extract_requirements_from_text(text: str) -> dict:
    """入札公告テキスト（PDF等）から参加資格要件を抽出する。

    Args:
        text: 入札公告の全文テキスト

    Returns:
        dict: {"required_grade", "required_category", "required_issuer_type"}
    """
    result = {
        "required_grade": "",
        "required_category": "",
        "required_issuer_type": "",
    }

    if not text:
        return result

    # 全角→半角
    normalized = text.translate(str.maketrans("ＡＢＣＤ", "ABCD"))

    # 等級抽出
    # パターン: 「○○のD等級以上」「○○のA等級」
    m = re.search(r"「([^」]+)」の([A-D])\s*等?級?\s*以上", normalized)
    if m:
        result["required_category"] = m.group(1)
        result["required_grade"] = m.group(2)
    else:
        result["required_grade"] = _extract_grade(normalized)

    # 資格種別抽出
    if "全省庁統一資格" in text:
        result["required_issuer_type"] = "全省庁統一資格"
    elif "防衛省" in text and "競争参加資格" in text:
        result["required_issuer_type"] = "防衛省"

    # 業種区分（まだ取れていない場合）
    if not result["required_category"]:
        # 「役務の提供等」「物品の製造」「物品の販売」「工事」等
        categories = ["役務の提供等", "物品の製造", "物品の販売", "工事"]
        for cat in categories:
            if cat in text:
                result["required_category"] = cat
                break

    return result
