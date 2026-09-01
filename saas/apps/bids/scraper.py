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

# --- 検索結果／詳細ページの id ---
# 実物を確認済み。文言ではなく id で掴むほうが安定する。
GRID_SEARCH_LIST = "#dgrSearchList"  # 検索結果テーブル
TBL_DETAIL_HDR = "#tblDataHdr"  # 詳細ページの案件概要（ラベル+値の2列）
GRID_KOKOKU = "#dgrKokoku"  # 詳細ページの「公開文書（入札公告等）」

# 詳細ページの一覧の案件リンクは href="javascript:__doPostBack(...)" なので
# URL にならない。案件ごとの外部URLは公開文書のリンク（発注機関のページ、
# または e-bisc の公開文書サーブレット）から取る。

# 一覧テーブルのヘッダー → レコードのキー。上から順に部分一致で判定する。
# 実物のヘッダー: No / 発注機関／担当部・事務所 / 工事名 / 入札契約方式 / 工事区分 / 公告日
LIST_HEADER_MAP = [
    (("工事名", "業務名", "案件名", "件名"), "title"),
    (("発注機関", "発注者"), "client"),
    (("入札契約方式", "契約方式", "入札方式"), "bid_method"),
    (("工事区分", "工事種別", "種別", "業種", "工種"), "category"),
    (("公告日",), "announced_on"),
    (("開札",), "opening_on"),
    (("期限", "締切"), "deadline"),
    (("場所", "地域", "都道府県"), "location"),
    (("予定価格", "金額"), "budget"),
    (("等級", "格付"), "required_grade"),
]

# 詳細ページ（案件概要）のラベル → レコードのキー。完全一致で引く。
DETAIL_LABEL_MAP = {
    "発注機関": "client",
    "担当部・事務所": "agency_dept",
    "工事名称": "title",
    "業務名称": "title",
    "工事場所": "location",
    "履行場所": "location",
    "入札契約方式": "bid_method",
    "工事種別／工事の業種": "category",
    "業務種別": "category",
    "設計書番号": "design_no",
    "公告日時": "announced_on",
    "期限日時": "deadline",
    "開札日時": "opening_on",
    "電子入札対象": "electronic_bid",
    "予定価格": "budget",
}

DETAIL_DATE_KEYS = ("announced_on", "deadline", "opening_on")

PREFECTURES = (
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
)


def _empty_record() -> dict:
    """スクレイパーが返すレコードの雛形。"""
    return {
        "title": "",
        "client": "",
        "agency_dept": "",
        "region": "",
        "location": "",
        "category": "",
        "bid_method": "",
        "design_no": "",
        "electronic_bid": "",
        "announced_on": None,
        "opening_on": None,
        "deadline": None,
        "budget": 0,
        "source_url": "",
        "document_urls": [],
        "summary": "",
        "required_grade": "",
        "required_category": "",
        "required_issuer_type": "",
    }


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

    result_table = _find_result_table(page)

    if not result_table:
        logger.warning("結果テーブルが見つかりませんでした")
        # ヘッダー文言を確定させるため、候補テーブルの1行目を残す
        tables = page.locator("table")
        _log_table_candidates(page, tables, tables.count())
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


def _match_list_header(header: str) -> str | None:
    """一覧テーブルのヘッダー文言をレコードのキーに対応づける。"""
    for needles, key in LIST_HEADER_MAP:
        if any(n in header for n in needles):
            return key
    return None


def _split_agency(client: str, agency_dept: str) -> tuple[str, str]:
    """「発注機関 ／ 担当部・事務所」を分割する。

    一覧の1カラムに両方入っている。詳細ページでは別項目なので、
    そちらで取れている場合はそのまま返す。
    """
    if agency_dept or not client:
        return client, agency_dept
    for sep in ("／", "/"):
        if sep in client:
            head, _, tail = client.partition(sep)
            return head.strip(), tail.strip()
    return client, ""


def _clean_location(location: str) -> str:
    """工事場所を読める形に整える。

    実物は「自：…」と「至：…」の2行構成で、1地点しかない案件でも
    「至：」だけの行が付いてくる。中身のない「至：」は落とす。
    """
    text = " ".join((location or "").split())
    if not text:
        return ""
    head, sep, tail = text.partition("至：")
    if sep and not tail.strip():
        text = head.strip()
        if text.startswith("自："):
            text = text[2:].strip()
    return text


def _extract_prefecture(location: str) -> str:
    """工事場所から都道府県名を取り出す。

    実物は「自：長野県長野県飯田市…から静岡県浜松市…」のように
    都道府県が重複したり複数県にまたがったりする。最初の1つを地域として扱う。
    """
    if not location:
        return ""
    hits = [(location.find(p), p) for p in PREFECTURES if p in location]
    if not hits:
        return ""
    return min(hits)[1]


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
    """検索結果の各案件の詳細ページを開き、案件概要を取り込む。

    一覧が持っているのは発注機関・工事名・入札契約方式・工事区分・公告日だけで、
    工事場所・期限・開札日・情報源URLは詳細ページにしかない。
    案件詳細画面が空にならないよう、全件の詳細を開く。

    i-ppi の一覧リンクは javascript:__doPostBack('dgrSearchList','$N') 形式。
    各行をクリック → 詳細ページから情報を取得 → ブラウザバック を繰り返す。
    """
    if not results:
        return

    indices_to_visit = list(range(len(results)))
    logger.info(f"{len(indices_to_visit)}件の詳細ページから案件概要を取得します...")

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

            # 詳細ページから情報を抽出し、一覧で取れた値の上に重ねる
            detail = _parse_detail_page(page)
            _merge_detail(results[row_index], detail)
            logger.info(
                "  [%d] %s... → 締切: %s / 場所: %s / URL: %s",
                row_index,
                results[row_index]["title"][:30],
                results[row_index].get("deadline") or "不明",
                results[row_index].get("location") or "不明",
                results[row_index].get("source_url") or "なし",
            )

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

    total = len(results)
    logger.info(
        "詳細取得: 締切 %d/%d件, 工事場所 %d/%d件, 情報源URL %d/%d件",
        sum(1 for r in results if r.get("deadline")), total,
        sum(1 for r in results if r.get("location")), total,
        sum(1 for r in results if r.get("source_url")), total,
    )


def _merge_detail(record: dict, detail: dict) -> None:
    """詳細ページで取れた値をレコードに反映する。

    詳細ページのほうが情報源として正確なので、値があるものは上書きする。
    空の値で一覧の値を潰さないようにする。
    """
    for key, value in detail.items():
        if value in (None, "", 0):
            continue
        record[key] = value

    record["client"], record["agency_dept"] = _split_agency(
        record.get("client", ""), record.get("agency_dept", ""),
    )
    if record.get("location"):
        record["location"] = _clean_location(record["location"])
        record["region"] = _extract_prefecture(record["location"]) or record.get(
            "region", "",
        )
    # 期限日時が空の案件がある（法務省の例）。開札日を締切として扱う。
    if not record.get("deadline") and record.get("opening_on"):
        record["deadline"] = record["opening_on"]


def _find_result_table(page):
    """結果テーブルを取得する（ページ遷移後は参照が無効になるので都度呼ぶ）。

    id での取得を優先する。文言で探すとヘッダーを含む外側のテーブルを
    掴んでしまうことがあり、セルの並びがずれる。
    """
    grid = page.locator(GRID_SEARCH_LIST)
    try:
        if grid.count() > 0:
            return grid.first
    except Exception:
        pass

    logger.warning(
        "%s が見つかりませんでした。ヘッダー文言でテーブルを探します", GRID_SEARCH_LIST
    )
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
    """詳細ページ（案件概要）から案件情報を抽出する。

    i-ppi の案件概要は #tblDataHdr の「ラベル / 値」2列テーブル。実物の項目:
      発注機関 / 担当部・事務所 / 工事名称 / 工事場所 / 入札契約方式 /
      工事種別／工事の業種 / 設計書番号 / 公告日時 / 期限日時 / 開札日時 /
      電子入札対象 / 予定価格 / 落札者名 / 落札価格 / 契約者名 / 契約金額
    ラベルが取れない発注機関のために、本文テキストからの抽出も残す。
    """
    result = _parse_detail_table(page)
    documents = _find_document_urls(page)
    result["document_urls"] = documents
    result["source_url"] = documents[0] if documents else ""
    result["summary"] = _detail_summary(page)

    try:
        body_text = page.inner_text("body")
    except Exception:
        return result

    if result.get("deadline"):
        # 概要テーブルから取れているので本文からの推測は不要
        return result

    # 日付抽出の優先順位:
    # 1. 開札日時（入札の結果が決まる日）
    # 2. 期限日時（入札書提出期限）
    # 3. 入札書提出期限 / 申請書提出期限
    # 4. 参加申込期限
    deadline_patterns = [
        r"開札日[時\s]*[　\t]*(.+?)(?:\n|$)",
        r"開札予定日[時\s]*[　\t]*(.+?)(?:\n|$)",
        r"期限日[時\s]*[　\t]*(.+?)(?:\n|$)",
        r"入札書提出期限[：:　\t]*(.+?)(?:\n|$)",
        r"入札書の提出期限[：:　\t]*(.+?)(?:\n|$)",
        r"申[請込]書[等の]*提出期限[：:　\t]*(.+?)(?:\n|$)",
        r"申[請込][書の]*受[付領]期限[：:　\t]*(.+?)(?:\n|$)",
        r"参加申[込請]期限[：:　\t]*(.+?)(?:\n|$)",
        r"提出期限[：:　\t]*(.+?)(?:\n|$)",
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
    if not result.get("budget"):
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


def _parse_detail_table(page) -> dict:
    """案件概要テーブル（#tblDataHdr）をラベルで引いて dict にする。

    「工事場所」は値が「自：…」で、続く行に「至：…」だけが入る2行構成。
    行の1セル目がラベルにならないので、直前のラベルの続きとして連結する。
    """
    result: dict = {"deadline": None, "budget": 0}

    table = page.locator(TBL_DETAIL_HDR)
    try:
        if table.count() == 0:
            logger.warning(
                "%s が見つかりませんでした（案件概要のレイアウト変更の可能性）",
                TBL_DETAIL_HDR,
            )
            return result
    except Exception:
        return result

    last_key = None
    for row in table.first.locator("tr").all():
        try:
            cells = [c.inner_text().strip() for c in row.locator("td, th").all()]
        except Exception:
            continue
        if not cells:
            continue

        if len(cells) == 1:
            # 「至：…」のような値だけの行。直前の項目の続きとして扱う。
            # 「■予定価格情報」のような見出し行を値に混ぜないよう、
            # 継続を許すのは複数行構成が確認できている工事場所だけにする。
            if last_key and cells[0]:
                result[last_key] = f"{result.get(last_key, '')} {cells[0]}".strip()
            last_key = None
            continue

        key = DETAIL_LABEL_MAP.get(cells[0])
        last_key = key if key == "location" else None
        if not key:
            continue

        value = cells[1].strip()
        if not value:
            continue
        if key in DETAIL_DATE_KEYS:
            result[key] = _parse_date(value)
        elif key == "budget":
            result[key] = _parse_amount(value)
        elif key == "design_no":
            # 「2026857140010004 ＊発注機関が独自に定めるコード」の注記を落とす
            result[key] = value.split("＊")[0].strip()
        else:
            result[key] = value

    return result


def _find_document_urls(page) -> list[str]:
    """公開文書のリンクURLを、公告らしいものから順に返す。

    案件詳細そのものは Koji/Kokoku/List.aspx?tab=3 という全案件共通のURLで、
    セッションに依存するため情報源URLとして保存できない。
    公開文書のリンクは発注機関のページや e-bisc の公開文書サーブレットへの
    絶対URLで、案件ごとに変わるのでこれを情報源URLとして使う。

    1案件に複数の文書がぶら下がる（「入札公告」「指名結果書」「入札調書」
    「積算内訳書」…）。先頭を無条件に採ると、公告ではない文書を情報源に
    してしまう。文書名称で並べ替え、後段で読めるものを順に試せるよう
    全部返す。
    """
    urls: list[tuple[int, str]] = []
    seen = set()
    for selector in (f"{GRID_KOKOKU} tr", "#tblDataDtl tr"):
        try:
            rows = page.locator(selector).all()
        except Exception:
            continue
        for row in rows:
            try:
                link = row.locator("a").first
                if link.count() == 0:
                    continue
                url = _absolute_url(link.get_attribute("href"))
                cells = [c.inner_text().strip() for c in row.locator("td, th").all()]
            except Exception:
                continue
            if not url or url in seen:
                continue
            seen.add(url)
            name = cells[0] if cells else ""
            urls.append((_document_priority(name), url[:500]))

    urls.sort(key=lambda pair: pair[0])
    return [url for _, url in urls]


def _document_priority(name: str) -> int:
    """文書名称から、公告として読む優先順位を返す。小さいほど先。"""
    for rank, words in enumerate((
        ("入札公告", "公告"),
        ("公示", "掲示"),
        ("入札説明書", "説明書"),
    )):
        if any(w in name for w in words):
            return rank
    # 結果・調書・内訳書は要件が書かれていないので後回し
    if any(w in name for w in ("結果", "調書", "内訳", "契約")):
        return 9
    return 5


def _detail_summary(page) -> str:
    """案件概要テーブルをそのままテキストで残す。

    項目名がモデルのフィールドに割り当てられていない発注機関があるため、
    取りこぼしを画面で確認できるよう原文を保存する。
    """
    table = page.locator(TBL_DETAIL_HDR)
    try:
        if table.count() == 0:
            return ""
        lines = []
        for row in table.first.locator("tr").all():
            cells = [c.inner_text().strip() for c in row.locator("td, th").all()]
            cells = [c for c in cells if c]
            if cells:
                lines.append("\t".join(cells))
        return "\n".join(lines)[:4000]
    except Exception:
        return ""


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
            record = _empty_record()
            record["title"] = text
            record["source_url"] = href
            results.append(record)
    return results


def _map_cells_to_record(
    headers: list[str], cells: list[str], detail_url: str
) -> dict | None:
    """ヘッダーとセルの値からレコード dict にマッピングする。"""
    if len(cells) == 0:
        return None

    record = _empty_record()
    record["source_url"] = detail_url

    for idx, header in enumerate(headers):
        if idx >= len(cells):
            break
        val = cells[idx]
        key = _match_list_header(header)
        if not key:
            continue

        if key in DETAIL_DATE_KEYS:
            record[key] = _parse_date(val)
        elif key == "budget":
            record[key] = _parse_amount(val)
        elif key == "required_grade":
            record[key] = _extract_grade(val)
        else:
            record[key] = val

    # 一覧に締切がない（i-ppi の一覧は公告日だけ）場合は詳細ページで埋める。
    # 一覧が開札日を持っていた場合はそれを暫定の締切にする。
    if not record["deadline"] and record["opening_on"]:
        record["deadline"] = record["opening_on"]

    # 発注機関は「国土交通省中部地方整備局 ／ 飯田国道事務所」の形で入っている
    record["client"], record["agency_dept"] = _split_agency(
        record["client"], record["agency_dept"],
    )
    record["location"] = _clean_location(record["location"])
    record["region"] = _extract_prefecture(record["location"])

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
