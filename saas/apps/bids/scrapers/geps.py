"""政府電子調達（GEPS）のスクレイパー。

対象: https://www.geps.go.jp/
GEPSは調達案件の検索システム。公開されている案件一覧を取得する。

注意: GEPSはJavaScript重依存のシステムのため、
直接HTMLをパースしても案件情報が取れない場合がある。
その場合はAPIエンドポイントの調査が必要。
"""

from apps.bids.scrapers import BaseScraper, BidInfo, register


@register("geps")
class GepsScraper(BaseScraper):
    site_key = "geps"
    base_url = "https://www.geps.go.jp/"

    def scrape(self) -> list[BidInfo]:
        """GEPSから案件を取得する。

        GEPSはSPA（JavaScript）ベースのため、requests では
        動的コンテンツを取得できない可能性がある。
        まずは公開ページの静的コンテンツを試み、
        取れない場合は検索APIの利用を検討する。
        """
        url = "https://www.geps.go.jp/"
        bids = []

        try:
            soup = self.fetch_soup(url)

            # 調達案件へのリンクを探す
            for link in soup.find_all("a"):
                href = link.get("href", "")
                text = link.get_text(strip=True)
                if not text or len(text) < 5:
                    continue
                if any(kw in text for kw in
                       ["調達", "入札", "案件", "公告", "工事"]):
                    bids.append(BidInfo(
                        title=text,
                        client="GEPS",
                        region="全国",
                        source_url=self._abs_url(href) if href else url,
                    ))

        except Exception as e:
            # GEPSがJS必須の場合はここに来る
            import logging
            logging.getLogger(__name__).warning(
                f"GEPS取得エラー（JS必須の可能性）: {e}"
            )

        return bids
