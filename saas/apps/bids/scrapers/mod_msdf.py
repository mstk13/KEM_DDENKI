"""海上自衛隊の入札情報スクレイパー。

対象: https://www.mod.go.jp/msdf/bukei/nyusatsu_idx.html
"""

from apps.bids.scrapers import BaseScraper, BidInfo, register


@register("mod_msdf")
class ModMsdfScraper(BaseScraper):
    site_key = "mod_msdf"
    base_url = "https://www.mod.go.jp/msdf/bukei/"

    def scrape(self) -> list[BidInfo]:
        url = "https://www.mod.go.jp/msdf/bukei/nyusatsu_idx.html"
        soup = self.fetch_soup(url)
        bids = []

        for link in soup.find_all("a"):
            href = link.get("href", "")
            text = link.get_text(strip=True)
            if not text or len(text) < 5:
                continue
            # 入札関連のリンクを探す
            if any(kw in href.lower() or kw in text for kw in
                   ["nyusatsu", "koukoku", "入札", "公告", "調達"]):
                bids.append(BidInfo(
                    title=text,
                    client="海上自衛隊",
                    region="全国",
                    category="防衛",
                    source_url=self._abs_url(href),
                ))

        return bids
