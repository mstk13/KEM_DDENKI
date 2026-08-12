"""私学事業団の入札公告ページスクレイパー。

対象: https://www.shigaku.go.jp/g_nyusatukoukoku2.htm
"""

from apps.bids.scrapers import BaseScraper, BidInfo, register


@register("shigaku")
class ShigakuScraper(BaseScraper):
    site_key = "shigaku"
    base_url = "https://www.shigaku.go.jp/"

    def scrape(self) -> list[BidInfo]:
        url = "https://www.shigaku.go.jp/g_nyusatukoukoku2.htm"
        soup = self.fetch_soup(url)
        bids = []

        # テーブル形式の入札公告を探す
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                text = cells[0].get_text(strip=True)
                # リンクがあれば案件
                link = row.find("a")
                if link and text and len(text) > 5:
                    href = link.get("href", "")
                    bids.append(BidInfo(
                        title=text,
                        client="日本私立学校振興・共済事業団",
                        region="全国",
                        source_url=self._abs_url(href) if href else url,
                    ))

        # テーブルが見つからない場合、リスト形式を試す
        if not bids:
            for li in soup.find_all("li"):
                link = li.find("a")
                if link:
                    title = link.get_text(strip=True)
                    if title and len(title) > 5:
                        href = link.get("href", "")
                        bids.append(BidInfo(
                            title=title,
                            client="日本私立学校振興・共済事業団",
                            region="全国",
                            source_url=self._abs_url(href) if href else url,
                        ))

        return bids
