"""設定（ステータス・フォルダ・Claude API モデル等）。"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Python の SSL に Windows 証明書ストアを使わせる。
# 社内プロキシ/ウイルス対策が HTTPS を検査する環境で、Claude API 接続時の
# CERTIFICATE_VERIFY_FAILED を防ぐ（Windows が信頼する独自ルートCAを利用）。
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

# アプリのルートディレクトリ
BASE_DIR = Path(__file__).resolve().parent

# データベース
_data_dir = os.environ.get("KEM_DATA_DIR")
DB_PATH = os.path.join(_data_dir, "eigyo_kanri.db") if _data_dir else os.environ.get("EIGYO_DB_PATH", str(BASE_DIR / "database.db"))

# フォルダ監視（営業資料の受け取り）
#   INBOX_DIR   : データ化された資料（PDF/画像）を置くフォルダ
#   FILES_DIR   : 取込済みの資料を業界/会社ごとに保管するフォルダ
INBOX_DIR = Path(os.environ.get("EIGYO_INBOX_DIR", str(BASE_DIR / "data" / "inbox")))
FILES_DIR = Path(os.environ.get("EIGYO_FILES_DIR", str(BASE_DIR / "data" / "files")))

# 取込対象の拡張子
SUPPORTED_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"}

# Claude API（自動抽出エンジン）
#   ANTHROPIC_API_KEY は .env で設定する
EXTRACT_MODEL = os.environ.get("EIGYO_MODEL", "claude-opus-4-8")

# ステータス（営業対応の進捗）
STATUSES = ["下書き", "確認済", "対応中", "完了", "見送り"]
DEFAULT_STATUS = "下書き"

# 業界（営業に来た会社の業界カテゴリ）
# 画面は「業界一覧 → 会社一覧」のドリルダウン。自動抽出でもこの中から分類する。
INDUSTRIES = [
    "電材・資材",
    "メーカー・製造",
    "商社・卸",
    "通信・IT",
    "建設・設備工事",
    "省エネ・環境",
    "オフィス・事務用品",
    "金融・保険・リース",
    "人材・サービス",
    "広告・印刷",
    "その他",
]
DEFAULT_INDUSTRY = "その他"

# メール通知（任意）
EMAIL_TO = [a.strip() for a in os.environ.get("EIGYO_EMAIL_TO", "").split(",") if a.strip()]
