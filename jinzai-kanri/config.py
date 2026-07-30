"""人材管理アプリ設定。"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent

COMPANY_NAME = os.getenv("JINZAI_COMPANY_NAME", "株式会社ケンモチ電機")

# 社員マスターJSONのパス（DB が空のとき自動復元に使う）
EMPLOYEES_JSON = REPO_DIR / "shared" / "data" / "employees.json"

# 社員番号のプレフィックス（通常社員）
CODE_PREFIX = "E"

# 職種区分（role）
ROLES = ["役員", "電工", "事務", "developer"]

# 部署
DEPARTMENTS = ["役員", "電気工事部", "総務部", "AI system development"]

# 役職
POSITIONS = ["代表取締役", "取締役", "職長", "主任", "社員", "見習い", "engineer"]
