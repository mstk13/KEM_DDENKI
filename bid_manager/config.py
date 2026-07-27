"""アプリ全体の設定。

機密値（メールのユーザ/パスワード）は環境変数（.env）から読み込む。
それ以外の運用パラメータ（キーワード・エリア・ステータス等）はここで定義する。
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv 未導入でも環境変数があれば動く
    pass

# --- パス ---
BASE_DIR = Path(__file__).resolve().parent
_data_dir = os.getenv("KEM_DATA_DIR")
DB_PATH = Path(os.path.join(_data_dir, "bid_manager.db")) if _data_dir else Path(os.getenv("BID_DB_PATH", BASE_DIR / "database.db"))
DATA_DIR = Path(os.getenv("BID_DATA_DIR", BASE_DIR / "data"))  # 非構造化データ（PDF等）

# --- スクレイピング対象キーワード ---
KEYWORDS = ["電気工事", "電気設備", "照明", "配線", "受変電", "幹線", "動力", "弱電"]

# --- 対象エリア ---
REGIONS = ["東京都", "神奈川県", "埼玉県", "千葉県", "茨城県", "栃木県", "群馬県"]

# --- 工事種別（推定用の候補） ---
CATEGORIES = ["電気工事", "電気設備", "照明設備", "受変電設備", "通信・弱電", "その他"]

# --- 案件ステータス（遷移順） ---
STATUSES = ["新着", "検討中", "見積作成中", "入札済", "受注", "失注", "見送り"]
OPEN_STATUSES = {"新着", "検討中", "見積作成中", "入札済"}
WON_STATUS = "受注"
LOST_STATUS = "失注"

# --- スクレイピング挙動 ---
SCRAPE_INTERVAL = float(os.getenv("BID_SCRAPE_INTERVAL", "2"))  # サイト間の待機秒数
SCRAPE_TIMEOUT = int(os.getenv("BID_SCRAPE_TIMEOUT", "20"))
USER_AGENT = os.getenv(
    "BID_USER_AGENT",
    "Mozilla/5.0 (compatible; KenmochiBidBot/1.0; +https://example.com/bot)",
)
USE_PLAYWRIGHT = os.getenv("BID_USE_PLAYWRIGHT", "0") == "1"  # JS描画サイト向け

# サイトごとのCSSセレクタ上書き（任意）。DBスキーマは変えず、ここでドメイン別に調整する。
# 例: {"example.go.jp": {"item": "table.bid tr", "title": "td.name a", "link": "td.name a"}}
SITE_SELECTORS: dict[str, dict[str, str]] = {}

# --- メール通知 ---
EMAIL_FROM = os.getenv("GMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD", "")
EMAIL_TO = [a.strip() for a in os.getenv("BID_EMAIL_TO", "").split(",") if a.strip()]
EMAIL_SUBJECT = "【入札案件】本日の新着案件通知"
SMTP_HOST = os.getenv("BID_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("BID_SMTP_PORT", "587"))
DEADLINE_ALERT_DAYS = int(os.getenv("BID_DEADLINE_ALERT_DAYS", "3"))
