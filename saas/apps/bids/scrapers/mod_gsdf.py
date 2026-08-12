"""陸上自衛隊の調達情報スクレイパー。

対象: https://www.mod.go.jp/gsdf/chotatsu/
"""

from apps.bids.scrapers import BaseScraper, BidInfo, register


@register("mod_gsdf")
class ModGsdfScraper(BaseScraper):
    site_key = "mod_gsdf"
    base_url = "https://www.mod.go.jp/gsdf/chotatsu/"

    def scrape(self) -> list[BidInfo]:
        url = "https://www.mod.go.jp/gsdf/chotatsu/"
        soup = self.fetch_soup(url)
        bids = []

        for link in soup.find_all("a"):
            href = link.get("href", "")
            text = link.get_text(strip=True)
            if not text or len(text) < 5:
                continue
            if any(kw in href.lower() or kw in text for kw in
                   ["nyusatsu", "koukoku", "入札", "公告", "調達", "工事"]):
                bids.append(BidInfo(
                    title=text,
                    client="陸上自衛隊",
                    region="全国",
                    category="防衛",
                    source_url=self._abs_url(href),
                ))

        return bids
