"""神奈川県下水道公社のスクレイパー。

対象: http://kanagawa-swf.or.jp/
"""

from apps.bids.scrapers import BaseScraper, BidInfo, register


@register("kanagawa_swf")
class KanagawaSwfScraper(BaseScraper):
    site_key = "kanagawa_swf"
    base_url = "http://kanagawa-swf.or.jp/"

    def scrape(self) -> list[BidInfo]:
        url = "http://kanagawa-swf.or.jp/"
        soup = self.fetch_soup(url)
        bids = []

        # 入札・調達情報のリンクを探す
        for link in soup.find_all("a"):
            href = link.get("href", "")
            text = link.get_text(strip=True)
            if not text or len(text) < 5:
                continue
            if any(kw in text for kw in
                   ["入札", "公告", "調達", "工事", "発注"]):
                bids.append(BidInfo(
                    title=text,
                    client="神奈川県下水道公社",
                    region="神奈川県",
                    source_url=self._abs_url(href) if href else url,
                ))

        return bids
