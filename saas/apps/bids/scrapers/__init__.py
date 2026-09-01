"""入札情報スクレイパー。

各官公庁サイトから入札案件情報を自動取得する。
BaseScraper を継承したサイト固有のスクレイパーをレジストリで管理。

注意:
- 対象は全て官公庁・公的機関（商用サイトのスクレイピングは禁止）
- robots.txt を尊重する
- リクエスト間隔は最低2秒空ける
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# レジストリ
_SCRAPERS: dict[str, type] = {}


def register(site_key: str):
    """スクレイパークラスをレジストリに登録するデコレータ。"""
    def decorator(cls):
        _SCRAPERS[site_key] = cls
        return cls
    return decorator


def get_scraper(site_key: str) -> "BaseScraper | None":
    """site_key に対応するスクレイパーのインスタンスを返す。"""
    cls = _SCRAPERS.get(site_key)
    if cls:
        return cls()
    return None


def list_scrapers() -> dict[str, type]:
    """登録済みスクレイパーの一覧。"""
    return dict(_SCRAPERS)


@dataclass
class BidInfo:
    """スクレイパーが返す1案件分の情報。"""

    title: str
    client: str = ""
    region: str = ""
    category: str = ""
    deadline: date | None = None
    budget: Decimal | None = None
    source_url: str = ""
    raw_data: dict = field(default_factory=dict)


class BaseScraper:
    """スクレイパーの基底クラス。"""

    site_key: str = ""
    base_url: str = ""
    request_interval: float = 2.0  # 秒

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "KEC-BidMonitor/1.0 "
                "(Construction company bid monitoring; "
                "contact: admin@kem-ddenki.com)"
            ),
        })
        self._last_request_time = 0.0

    def _rate_limit(self):
        """リクエスト間隔を制御する。"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)
        self._last_request_time = time.time()

    def fetch(self, url: str, **kwargs) -> requests.Response:
        """URLを取得する。レート制限付き。"""
        self._rate_limit()
        logger.info(f"[{self.site_key}] Fetching: {url}")
        response = self.session.get(url, timeout=30, **kwargs)
        response.raise_for_status()
        return response

    def fetch_soup(self, url: str, encoding: str | None = None) -> BeautifulSoup:
        """URLを取得して BeautifulSoup を返す。"""
        response = self.fetch(url)
        if encoding:
            response.encoding = encoding
        return BeautifulSoup(response.text, "html.parser")

    def scrape(self) -> list[BidInfo]:
        """入札案件を取得する。サブクラスでオーバーライドすること。"""
        raise NotImplementedError

    def _parse_date(self, text: str) -> date | None:
        """日付文字列をパースする。複数フォーマットに対応。"""
        if not text:
            return None
        text = text.strip().replace("　", " ")
        for fmt in [
            "%Y年%m月%d日", "%Y/%m/%d", "%Y-%m-%d",
            "%Y.%m.%d", "%R%y年%m月%d日",
        ]:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        # 令和対応
        import re
        m = re.search(r"令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日", text)
        if m:
            year = 2018 + int(m.group(1))
            return date(year, int(m.group(2)), int(m.group(3)))
        return None

    def _parse_amount(self, text: str) -> Decimal | None:
        """金額文字列をパースする。"""
        if not text:
            return None
        import re
        text = re.sub(r"[,、円￥\s]", "", text)
        try:
            return Decimal(text)
        except Exception:
            return None

    def _abs_url(self, relative: str) -> str:
        """相対URLを絶対URLに変換する。"""
        return urljoin(self.base_url, relative)
