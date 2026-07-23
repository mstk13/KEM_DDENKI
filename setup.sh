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

# 依存パッケージインストール
echo "[2/4] 依存パッケージをインストール中..."
pip install -r bid_manager/requirements.txt \
            -r material_manager/requirements.txt \
            -r 作業日報/requirements.txt \
            -r evaluation/requirements.txt --quiet
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

cd 作業日報
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
echo "========================================"
