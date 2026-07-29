"""アプリ全体の設定。

機密値（メールのユーザ/パスワード）は環境変数（.env）から読み込む。
それ以外の運用パラメータ（工事種別・ステータス等）はここで定義する。

項目は紙の「作業日報」フォームに準拠:
    現場名 / 発注先 / 年月日 / 曜日 / 作業員名 / 作業時間 / 残業 / 宿泊 /
    作業内容・使用材料 / 交通手段・交通費 / 協力会社 / 現場代理人又は責任者
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
REPO_DIR = BASE_DIR.parent
_data_dir = os.getenv("KEM_DATA_DIR", str(REPO_DIR / "data"))
DB_PATH = Path(os.path.join(_data_dir, "sagyo_nippou.db"))
DATA_DIR = Path(os.getenv("NIPPOU_DATA_DIR", BASE_DIR / "data"))  # 写真等の非構造化データ

# --- 会社名（画面表示用） ---
COMPANY_NAME = os.getenv("NIPPOU_COMPANY_NAME", "株式会社ケンモチ電機")

# --- 工事種別（現場マスタ用） ---
WORK_TYPES = [
    "電気工事",
    "電気設備",
    "照明設備",
    "受変電設備",
    "配線工事",
    "通信・弱電",
    "点検・保守",
    "撤去・解体",
    "その他",
]

# --- 現場ステータス ---
SITE_STATUSES = ["着工前", "施工中", "完了", "中断"]
ACTIVE_SITE_STATUSES = {"着工前", "施工中"}

# --- 日報ステータス（アプリ内の提出フロー。用紙の承認印とは別管理） ---
REPORT_STATUSES = ["下書き", "提出済", "承認済", "差戻し"]

# --- 曜日（年月日から算出して表示） ---
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]

# --- 作業時間の初期値 ---
DEFAULT_START_TIME = os.getenv("NIPPOU_DEFAULT_START", "08:00")
DEFAULT_END_TIME = os.getenv("NIPPOU_DEFAULT_END", "17:00")
STANDARD_WORK_HOURS = float(os.getenv("NIPPOU_STANDARD_HOURS", "8"))  # これを超えると残業目安

# --- 社員の担当区分（日報確認のフィルタに使用） ---
EMPLOYEE_ROLES = ["現場", "事務員", "役員"]

# --- メール通知 ---
EMAIL_FROM = os.getenv("GMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD", "")
EMAIL_TO = [a.strip() for a in os.getenv("NIPPOU_EMAIL_TO", "").split(",") if a.strip()]
EMAIL_SUBJECT = "【作業日報】本日の提出まとめ"
SMTP_HOST = os.getenv("NIPPOU_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("NIPPOU_SMTP_PORT", "587"))


def weekday_jp(iso_date: str) -> str:
    """'YYYY-MM-DD' → 曜日（日本語1文字）。不正な入力は空文字。"""
    from datetime import date

    try:
        y, m, d = (int(x) for x in iso_date.split("-"))
        return WEEKDAYS_JP[date(y, m, d).weekday()]
    except (ValueError, AttributeError):
        return ""
