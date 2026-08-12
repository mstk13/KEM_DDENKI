"""神奈川電子入札共同システムのスクレイパー。

対象: https://nyusatsu-joho.e-kanagawa.lg.jp/DENTYO/GPPI_MENU
電子入札システムのため、公開されている案件一覧ページを取得。
"""

from apps.bids.scrapers import BaseScraper, BidInfo, register


@register("kanagawa_ebid")
class KanagawaEbidScraper(BaseScraper):
    site_key = "kanagawa_ebid"
    base_url = "https://nyusatsu-joho.e-kanagawa.lg.jp/"

    def scrape(self) -> list[BidInfo]:
        url = "https://nyusatsu-joho.e-kanagawa.lg.jp/DENTYO/GPPI_MENU"
        soup = self.fetch_soup(url)
        bids = []

        # 入札公告一覧のリンクを探す
        for link in soup.find_all("a"):
            href = link.get("href", "")
            text = link.get_text(strip=True)
            if not text or len(text) < 5:
                continue
            if any(kw in text for kw in ["入札", "公告", "案件", "工事"]):
                bids.append(BidInfo(
                    title=text,
                    client="神奈川県（電子入札）",
                    region="神奈川県",
                    source_url=self._abs_url(href) if href else url,
                ))

        return bids
