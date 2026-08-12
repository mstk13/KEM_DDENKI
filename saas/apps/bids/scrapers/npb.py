"""国立印刷局の電子入札スクレイパー。

対象: https://www.npb.go.jp/ja/guide/finance/portal/index.html
"""

from apps.bids.scrapers import BaseScraper, BidInfo, register


@register("npb")
class NpbScraper(BaseScraper):
    site_key = "npb"
    base_url = "https://www.npb.go.jp/"

    def scrape(self) -> list[BidInfo]:
        url = "https://www.npb.go.jp/ja/guide/finance/portal/index.html"
        soup = self.fetch_soup(url)
        bids = []

        for link in soup.find_all("a"):
            href = link.get("href", "")
            text = link.get_text(strip=True)
            if not text or len(text) < 5:
                continue
            if any(kw in text for kw in
                   ["入札", "公告", "調達", "案件", "工事"]):
                bids.append(BidInfo(
                    title=text,
                    client="国立印刷局",
                    region="全国",
                    source_url=self._abs_url(href) if href else url,
                ))

        return bids
