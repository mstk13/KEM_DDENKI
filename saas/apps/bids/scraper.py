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
from datetime import date
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

BASE_URL = "https://www.i-ppi.jp/"
SEARCH_URL = (
    "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=3"
)

# --- 検索フォームの id ---
# i-ppi は ASP.NET WebForms。要素の並びや隣接テキストは当てにならないが id は安定している。
TBX_KOJI_NAME = "#tbxKojiNm"  # 工事名
DRP_KOJI_DISTRICT = "#drpKojiDistrict"  # 地域（地方）
DRP_KOJI_PREFECTURE = "#drpKojiPrefecture2"  # 都道府県（地域選択で中身が入る）
DRP_KOJI_KBN = "#drpKojiKbn"  # 工事区分
DRP_KOJI_GYOSYU = "#drpKojiGyosyu"  # 業種
RBT_LAST_UPDATE2 = "#rbtLastUpdate2"  # 最終更新日「過去N日以内」
TBX_LAST_UPDATE = "#tbxLastUpdate"  # 同 日数（既定 disabled）
RBT_KOKOKU_DATE_NONE = "#rbtKokokuDate1Kokoku"  # 公告日「指定なし」
DRP_COUNT = "#drpCount"  # 1ページの表示件数
BTN_SEARCH = "#btnSearch"  # 検索開始

# 1ページあたりの取得件数。選択肢は 20/30/50/100 件。
PAGE_SIZE_LABEL = "100件"

# 0件時に i-ppi が返す文言
NO_RESULT_TEXT = "該当する案件が見つかりませんでした"


def scrape_ippi(
    target,
    *,
    headless: bool = True,
    timeout_ms: int = 60_000,
) -> list[dict]:
    """ScrapeTarget の条件で i-ppi.jp を検索し、結果を返す。

    Args:
        target: ScrapeTarget モデルインスタンス
            （keyword, region, prefecture, koji_kbn, koji_gyosyu, days_back）
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

            # --- 詳細ページから締切日等を取得 ---
            _enrich_from_detail_pages(page, results)

        except Exception:
            logger.exception("スクレイピング中にエラーが発生しました")
            raise
        finally:
            browser.close()

    return results


def _fill_form(page, target) -> None:
    """検索フォームに条件を入力する。

    i-ppi は ASP.NET WebForms で、要素の並びや隣接テキストからの推定は当てにならない。
    id は安定しているので直接指定する（実物を probe して確認済み）。

    順序が重要:
      都道府県 (#drpKojiPrefecture2) は選択でポストバックが走りページが作り直される。
      先に地域→都道府県を確定させ、そのあとで他の項目を入れる。
    """
    _clear_kokoku_date(page)
    _select_by_label(page, DRP_COUNT, PAGE_SIZE_LABEL, "表示件数")

    _select_area(page, target)

    # 工事名キーワード
    if target.keyword:
        page.fill(TBX_KOJI_NAME, target.keyword)
        logger.info(f"キーワード: {target.keyword}")

    # 工事区分・業種。i-ppi では別々のセレクトで、選択肢も体系が違う。
    _select_by_label(page, DRP_KOJI_KBN, target.koji_kbn, "工事区分")
    _select_by_label(page, DRP_KOJI_GYOSYU, target.koji_gyosyu, "業種")

    # 最終更新日（過去N日以内）
    if target.days_back:
        try:
            # 日数欄 tbxLastUpdate は既定で disabled。「過去N日以内」側のラジオ
            # rbtLastUpdate2 を選択して初めて入力できるようになるため、順序が重要。
            # 隣接テキストから探す方法は DOM 構造上ヒットしないので id で直接指定する。
            page.check(RBT_LAST_UPDATE2)
            day_input = page.locator(TBX_LAST_UPDATE)
            day_input.wait_for(state="visible")
            # maxlength=3 のため 3 桁までに丸める
            day_input.fill(str(min(int(target.days_back), 999)))
            logger.info(f"最終更新日: 過去{target.days_back}日以内")
        except Exception:
            logger.warning("最終更新日の設定に失敗しました")


def _clear_kokoku_date(page) -> None:
    """公告日の絞り込みを外す。

    i-ppi は公告日が既定で「期間指定：本日〜本日」になっている。
    これが他の条件と AND されるため、放置すると当日公告の案件しか出ない。
    実際、無条件検索でも 0 件になっていた（祝日だからではない）。
    検索範囲は ScrapeTarget.days_back（最終更新日）で指定する方針なので、
    公告日は「指定なし」に倒す。
    """
    try:
        page.check(RBT_KOKOKU_DATE_NONE)
        logger.info("公告日: 指定なし")
    except Exception:
        logger.warning(
            "公告日を「指定なし」にできませんでした。"
            "当日公告の案件しか取得できない可能性があります"
        )


def _select_area(page, target) -> None:
    """地域（地方）と都道府県を選択する。

    都道府県セレクトは地域を選ぶまで空で、地域選択で JS が中身を組み立てる。
    さらに都道府県の選択はポストバックを起こすため、完了を待ってから次へ進む。
    """
    if not target.region:
        if target.prefecture:
            logger.warning(
                "都道府県「%s」が指定されていますが地域が未設定のため無視されます",
                target.prefecture,
            )
        return

    if not _select_by_label(page, DRP_KOJI_DISTRICT, target.region, "地域"):
        return

    if not target.prefecture:
        return

    # 地域選択で都道府県の option が入るまで待つ
    page.wait_for_timeout(1000)
    if _select_by_label(page, DRP_KOJI_PREFECTURE, target.prefecture, "都道府県"):
        # 都道府県の選択はポストバック（市区町村の絞り込み）を起こす
        page.wait_for_load_state("networkidle")


def _select_by_label(page, selector: str, label: str, field_name: str) -> bool:
    """セレクトを表示ラベルで選択する。選べたら True。

    i-ppi の選択肢が変わったときに黙って既定値のまま検索してしまわないよう、
    見つからない場合は警告を残す。
    """
    if not label:
        return False
    try:
        page.select_option(selector, label=label)
        logger.info(f"{field_name}: {label}")
        return True
    except Exception:
        logger.warning(
            "%s に「%s」が見つかりませんでした（%s の選択肢が変わった可能性）"
            "。この条件は指定されずに検索されます",
            field_name,
            label,
            selector,
        )
        return False


def _click_search(page) -> None:
    """検索ボタンをクリックして結果を待つ。"""
    try:
        page.click(BTN_SEARCH)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)  # 追加の描画待ち
        return
    except Exception:
        logger.warning(
            "%s をクリックできませんでした。テキストから検索ボタンを探します", BTN_SEARCH
        )

    # フォールバック: 「検索」を含むボタン/リンクを探す
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

    # 0件は正常な結果。フォールバックに落として無関係なリンクを拾わないよう先に判定する。
    try:
        if NO_RESULT_TEXT in page.inner_text("body"):
            logger.info("該当案件は0件でした")
            return []
    except Exception:
        logger.warning("ページ本文を読めませんでした")

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
        # ヘッダー文言を確定させるため、候補テーブルの1行目を残す
        _log_table_candidates(page, tables, count)
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
            headers = [_normalize_header(th.inner_text()) for th in ths.all()]
            data_start = i + 1
            break

    if not headers:
        # th がない場合、最初の tr をヘッダーとして扱う
        first_row = rows.nth(0)
        headers = [
            _normalize_header(td.inner_text()) for td in first_row.locator("td").all()
        ]
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
            detail_url = _absolute_url(link.get_attribute("href"))

        record = _map_cells_to_record(headers, cells, detail_url)
        if record and record.get("title"):
            results.append(record)

    _log_coverage(page, len(results))
    return results


def _absolute_url(href: str | None) -> str:
    """href を絶対URLにする。URL として使えないものは空文字を返す。

    i-ppi の一覧の案件リンクは href="javascript:__doPostBack('dgrSearchList','$0')" で、
    行の位置しか持たない。これを URL として保存すると、
    実行のたびに別の案件が同じ「URL」を持つことになり重複判定が壊れる。
    URL が無いことを空文字で表し、重複判定は案件名に任せる。
    """
    value = (href or "").strip()
    if not value or value.lower().startswith(("javascript:", "#")):
        return ""
    return urljoin(BASE_URL, value)


def _normalize_header(text: str) -> str:
    """ヘッダーセルから並べ替え記号と改行を落とす。

    実物は「発注機関／担当部・事務所\\n△▽」のように並べ替え矢印が付いてくる。
    """
    head = (text or "").split("\n")[0]
    return head.translate(str.maketrans("", "", "△▽▲▼ 　\xa0")).strip()


def _log_coverage(page, fetched: int) -> None:
    """総ヒット件数と実際に取得できた件数の差をログに残す。

    i-ppi は1ページ分しか返さない。ページ送りは未実装なので、
    取りこぼしが起きていることを黙って隠さない。
    """
    try:
        body = page.inner_text("body")
    except Exception:
        return
    m = re.search(r"該当する案件が\s*([\d,]+)\s*件あります", body)
    if not m:
        return
    total = int(m.group(1).replace(",", ""))
    if total > fetched:
        logger.warning(
            "総ヒット %d 件のうち %d 件のみ取得しました"
            "（ページ送り未対応。条件を絞ってください）",
            total,
            fetched,
        )
    else:
        logger.info("総ヒット %d 件をすべて取得しました", total)


def _log_table_candidates(page, tables, count: int) -> None:
    """結果テーブルを特定できなかったとき、候補の1行目をログに残す。

    i-ppi のヘッダー文言は実データが返る日にしか確認できない。
    次回の調査で当て推量にならないよう、見えたものをそのまま記録しておく。
    """
    for i in range(min(count, 10)):
        try:
            first_row = tables.nth(i).locator("tr").first
            if first_row.count() == 0:
                continue
            cells = [c.inner_text().strip() for c in first_row.locator("th, td").all()]
            if cells:
                logger.warning("テーブル候補[%d] 1行目: %s", i, cells)
        except Exception:
            continue


def _enrich_from_detail_pages(page, results: list[dict]) -> None:
    """検索結果の各案件の詳細ページを開き、締切日等を補完する。

    i-ppi の一覧リンクは javascript:__doPostBack('dgrSearchList','$N') 形式。
    各行をクリック → 詳細ページから情報を取得 → ブラウザバック を繰り返す。
    """
    if not results:
        return

    # deadline が既に取れている案件はスキップ対象
    indices_to_visit = [
        i for i, r in enumerate(results) if not r.get("deadline")
    ]
    if not indices_to_visit:
        logger.info("全案件に締切日があるため詳細ページの巡回をスキップします")
        return

    logger.info(f"{len(indices_to_visit)}件の詳細ページから締切日を取得します...")

    for row_index in indices_to_visit:
        try:
            # 一覧ページの N 番目の案件リンクをクリック
            # __doPostBack で遷移するため、テーブル内の a タグを直接クリック
            table = _find_result_table(page)
            if not table:
                logger.warning("結果テーブルが見つからず詳細巡回を中断します")
                break

            rows = table.locator("tr")
            # ヘッダー行を除いたデータ行のインデックスを算出
            data_row_index = _data_row_offset(rows) + row_index
            if data_row_index >= rows.count():
                break

            row = rows.nth(data_row_index)
            link = row.locator("a").first
            if link.count() == 0:
                continue

            link.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)

            # 詳細ページから情報を抽出
            detail = _parse_detail_page(page)
            if detail.get("deadline"):
                results[row_index]["deadline"] = detail["deadline"]
                logger.info(
                    f"  [{row_index}] {results[row_index]['title'][:30]}... "
                    f"→ 締切: {detail['deadline']}"
                )
            if detail.get("budget") and not results[row_index].get("budget"):
                results[row_index]["budget"] = detail["budget"]

            # 一覧に戻る
            page.go_back()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1000)

        except Exception as e:
            logger.warning(f"詳細ページ取得エラー (行{row_index}): {e}")
            # エラーが起きても一覧に戻れるよう試みる
            try:
                page.go_back()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1000)
            except Exception:
                logger.warning("一覧ページへの復帰に失敗。詳細巡回を中断します")
                break

    filled = sum(1 for r in results if r.get("deadline"))
    logger.info(f"締切日を取得済み: {filled}/{len(results)}件")


def _find_result_table(page):
    """結果テーブルを再取得する（ページ遷移後に参照が無効になるため）。"""
    tables = page.locator("table")
    for i in range(tables.count()):
        table = tables.nth(i)
        try:
            text = table.inner_text()
            if "案件名" in text or "工事名" in text or "件名" in text:
                return table
        except Exception:
            continue
    return None


def _data_row_offset(rows) -> int:
    """テーブルのデータ行開始位置を返す（ヘッダー行を飛ばす）。"""
    for i in range(min(rows.count(), 3)):
        row = rows.nth(i)
        if row.locator("th").count() > 0:
            return i + 1
    return 1


def _parse_detail_page(page) -> dict:
    """詳細ページから締切日・予定価格等を抽出する。

    i-ppi の詳細ページは定義リスト風のテーブル（ラベル＋値）で構成される。
    開札日時、入札書提出期限、質問受付期限などの日付フィールドを探す。
    """
    result = {"deadline": None, "budget": 0}

    try:
        body_text = page.inner_text("body")
    except Exception:
        return result

    # 日付抽出の優先順位:
    # 1. 開札日時（入札の結果が決まる日）
    # 2. 入札書提出期限 / 申請書提出期限
    # 3. 参加申込期限
    deadline_patterns = [
        r"開札日[時\s]*[：:]\s*(.+?)(?:\n|$)",
        r"開札予定日[時\s]*[：:]\s*(.+?)(?:\n|$)",
        r"入札書提出期限[：:]\s*(.+?)(?:\n|$)",
        r"入札書の提出期限[：:]\s*(.+?)(?:\n|$)",
        r"申[請込]書[等の]*提出期限[：:]\s*(.+?)(?:\n|$)",
        r"申[請込][書の]*受[付領]期限[：:]\s*(.+?)(?:\n|$)",
        r"参加申[込請]期限[：:]\s*(.+?)(?:\n|$)",
        r"提出期限[：:]\s*(.+?)(?:\n|$)",
    ]

    for pattern in deadline_patterns:
        m = re.search(pattern, body_text)
        if m:
            parsed = _parse_date(m.group(1).strip())
            if parsed:
                result["deadline"] = parsed
                break

    # テーブルのラベル→値パターンでも探す
    if not result["deadline"]:
        try:
            # th/td ペアのテーブルから日付を探す
            all_tables = page.locator("table")
            for t_idx in range(all_tables.count()):
                table = all_tables.nth(t_idx)
                trs = table.locator("tr")
                for r_idx in range(trs.count()):
                    tr = trs.nth(r_idx)
                    ths = tr.locator("th")
                    tds = tr.locator("td")
                    if ths.count() == 0 or tds.count() == 0:
                        continue
                    label = ths.first.inner_text().strip()
                    value = tds.first.inner_text().strip()
                    if any(k in label for k in ("開札", "提出期限", "申込期限", "入札期日")):
                        parsed = _parse_date(value)
                        if parsed:
                            result["deadline"] = parsed
                            break
                if result["deadline"]:
                    break
        except Exception:
            pass

    # 予定価格
    budget_patterns = [
        r"予定価格[（\(税抜き\)）]*[：:]\s*([\d,]+)",
        r"設計金額[：:]\s*([\d,]+)",
    ]
    for pattern in budget_patterns:
        m = re.search(pattern, body_text)
        if m:
            result["budget"] = _parse_amount(m.group(1))
            break

    return result


def _parse_results_fallback(page) -> list[dict]:
    """テーブルが見つからない場合のフォールバックパーサー。"""
    results = []
    # リンクテキストから案件情報を抽出
    links = page.locator("a")
    for i in range(links.count()):
        link = links.nth(i)
        text = (link.inner_text() or "").strip()
        href = _absolute_url(link.get_attribute("href"))
        # 案件リンクらしいものをフィルタ
        if len(text) > 10 and ("工事" in text or "業務" in text or "電気" in text):
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
) -> dict | None:
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
        elif "種別" in header or "業種" in header or "工種" in header or "区分" in header:
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


def _parse_date(text: str) -> str | None:
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
