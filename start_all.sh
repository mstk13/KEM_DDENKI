#!/bin/bash
# 全アプリ一括起動スクリプト（自動アップデート付き）
# Usage: ./start_all.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== ケンモチ電機 施工コスト最適化システム ==="
echo ""

# venv チェック・有効化
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "[警告] 仮想環境が見つかりません。先に ./setup.sh を実行してください。"
    echo "       venv なしで続行します..."
fi

# Python チェック
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "[エラー] Python が見つかりません。"
    exit 1
fi

# ===== 自動アップデート =====
if command -v git &>/dev/null && [ -d ".git" ]; then
    echo "[アップデート確認中...]"
    git fetch origin main --quiet 2>/dev/null || true

    LOCAL_HASH=$(git rev-parse HEAD 2>/dev/null)
    REMOTE_HASH=$(git rev-parse origin/main 2>/dev/null)

    if [ "$LOCAL_HASH" != "$REMOTE_HASH" ]; then
        echo "[更新あり] 最新版をダウンロード中..."

        # ローカル変更がある場合は退避
        git stash --quiet 2>/dev/null || true

        if git pull origin main --quiet 2>/dev/null; then
            echo "[更新完了] 依存パッケージを更新中..."
            pip install -r bid_manager/requirements.txt \
                        -r material_manager/requirements.txt \
                        -r sagyo-nippou/requirements.txt --quiet 2>/dev/null || true

            # DB マイグレーション（テーブル追加のみ、既存データは維持）
            (cd bid_manager && $PYTHON database.py 2>/dev/null) || true
            (cd material_manager && $PYTHON -c "from db import init_db; init_db()" 2>/dev/null) || true
            (cd sagyo-nippou && $PYTHON database.py 2>/dev/null) || true

            echo "[完了] アプリを最新版で起動します。"
        else
            echo "[警告] 更新に失敗しました。現在のバージョンで起動します。"
            git stash pop --quiet 2>/dev/null || true
        fi
    else
        echo "[最新版です]"
    fi
else
    echo "[スキップ] Git リポジトリではないため自動アップデートをスキップ。"
fi
echo ""

# ===== アプリ起動 =====

# 終了時にバックグラウンドプロセスを停止
cleanup() {
    echo ""
    echo "アプリを停止中..."
    [ -n "$PID_MATERIAL" ] && kill "$PID_MATERIAL" 2>/dev/null
    [ -n "$PID_BID" ] && kill "$PID_BID" 2>/dev/null
    [ -n "$PID_NIPPOU" ] && kill "$PID_NIPPOU" 2>/dev/null
    echo "停止完了。"
    exit 0
}
trap cleanup INT TERM

# 1. 材料管理 (Flask, port 5000)
echo "[1/3] 材料管理を起動中... (port 5000)"
cd "$SCRIPT_DIR/material_manager"
$PYTHON -c "from db import init_db; init_db()" 2>/dev/null
$PYTHON -c "from app import app; app.run(debug=False, host='0.0.0.0', port=5000, use_reloader=False)" &
PID_MATERIAL=$!
echo "      PID: $PID_MATERIAL"

# 2. 入札案件管理 (Streamlit, port 8501)
echo "[2/3] 入札案件管理を起動中... (port 8501)"
cd "$SCRIPT_DIR/bid_manager"
if command -v streamlit &>/dev/null; then
    streamlit run app.py --server.port 8501 --server.headless true &>/dev/null &
    PID_BID=$!
    echo "      PID: $PID_BID"
else
    echo "      ⚠ streamlit 未インストール。skip"
    PID_BID=""
fi

# 3. 作業日報 (Streamlit, port 8502)
echo "[3/3] 作業日報を起動中... (port 8502)"
cd "$SCRIPT_DIR/sagyo-nippou"
if command -v streamlit &>/dev/null; then
    streamlit run app.py --server.port 8502 --server.headless true &>/dev/null &
    PID_NIPPOU=$!
    echo "      PID: $PID_NIPPOU"
else
    echo "      ⚠ streamlit 未インストール。skip"
    PID_NIPPOU=""
fi

# 4. ポータルページを開く
echo ""
sleep 2

if command -v xdg-open &>/dev/null; then
    xdg-open "$SCRIPT_DIR/portal/index.html"
elif command -v open &>/dev/null; then
    open "$SCRIPT_DIR/portal/index.html"
else
    echo "ブラウザで開いてください: file://$SCRIPT_DIR/portal/index.html"
fi

echo ""
echo "=== 起動完了 ==="
echo "  ポータル:   file://$SCRIPT_DIR/portal/index.html"
echo "  材料管理:   http://localhost:5000"
echo "  入札管理:   http://localhost:8501"
echo "  作業日報:   http://localhost:8502"
echo ""
echo "  Ctrl+C で全アプリを停止します。"

# 待機
wait
