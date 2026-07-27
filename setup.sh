#!/bin/bash
# 初回セットアップスクリプト（Mac / Linux）

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "  ケンモチ電機 施工コスト最適化システム"
echo "  初回セットアップ"
echo "========================================"
echo ""

# Python チェック
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "[エラー] Python が見つかりません。Python 3.11 以上をインストールしてください。"
    exit 1
fi

echo "[INFO] Python: $PYTHON ($($PYTHON --version))"
echo ""

# venv 作成
if [ ! -d ".venv" ]; then
    echo "[1/4] 仮想環境を作成中..."
    $PYTHON -m venv .venv
    echo "      完了"
else
    echo "[1/4] 仮想環境は既に存在します。スキップ。"
fi
echo ""

# venv 有効化
source .venv/bin/activate

# .env 読み込み（KEM_DATA_DIR 等の共通設定）
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# データフォルダを作成（デフォルト: プロジェクト直下の data/）
KEM_DATA_DIR="${KEM_DATA_DIR:-$SCRIPT_DIR/data}"
mkdir -p "$KEM_DATA_DIR" 2>/dev/null || true
echo "[データ] DB保存先: $KEM_DATA_DIR"

# 依存パッケージインストール
echo "[2/4] 依存パッケージをインストール中..."
pip install -r bid_manager/requirements.txt \
            -r material_manager/requirements.txt \
            -r sagyo-nippou/requirements.txt \
            -r evaluation/requirements.txt \
            -r eigyo-kanri/requirements.txt \
            -r nippou-kanri/requirements.txt --quiet
echo "      完了"
echo ""

# DB 初期化
echo "[3/4] データベースを初期化中..."

cd bid_manager
mkdir -p data
$PYTHON database.py
cd "$SCRIPT_DIR"

cd material_manager
$PYTHON -c "from db import init_db; init_db()"
cd "$SCRIPT_DIR"

cd sagyo-nippou
$PYTHON database.py
cd "$SCRIPT_DIR"

cd eigyo-kanri
[ -f .env ] || { [ -f .env.example ] && cp .env.example .env; }
$PYTHON database.py
cd "$SCRIPT_DIR"

cd nippou-kanri
$PYTHON database.py
cd "$SCRIPT_DIR"

echo "      完了"
echo ""

# 完了
echo "[4/4] セットアップ完了！"
echo ""
echo "========================================"
echo "  次回からは ./start_all.sh で起動できます。"
echo "  起動時に自動でアップデートも行います。"
echo ""
echo "  ※ 営業管理の資料自動抽出を使うには"
echo "     eigyo-kanri/.env に ANTHROPIC_API_KEY を設定してください。"
echo "     未設定でも手動登録・一覧・閲覧は使えます。"
echo "========================================"
