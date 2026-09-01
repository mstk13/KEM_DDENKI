"""かながわ土地建物の工事情報スクレイパー。

対象: https://bid.thk.or.jp/pub/koujilist.aspx
ASP.NET の ViewState を使うフォームのため、GETで取得できる範囲で対応。
"""

from apps.bids.scrapers import BaseScraper, BidInfo, register


@register("kanagawa_thk")
class KanagawaThkScraper(BaseScraper):
    site_key = "kanagawa_thk"
    base_url = "https://bid.thk.or.jp/pub/"

    def scrape(self) -> list[BidInfo]:
        url = "https://bid.thk.or.jp/pub/koujilist.aspx"
        soup = self.fetch_soup(url)
        bids = []

        # テーブルから工事情報を抽出
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows[1:]:  # ヘッダースキップ
                cells = row.find_all("td")
                if len(cells) < 3:
                    continue
                title = cells[0].get_text(strip=True)
                if not title or len(title) < 3:
                    continue

                link = row.find("a")
                href = link.get("href", "") if link else ""

                deadline = None
                for cell in cells:
                    d = self._parse_date(cell.get_text(strip=True))
                    if d:
                        deadline = d
                        break

                bids.append(BidInfo(
                    title=title,
                    client="かながわ土地建物",
                    region="神奈川県",
                    deadline=deadline,
                    source_url=self._abs_url(href) if href else url,
                ))

        return bids
