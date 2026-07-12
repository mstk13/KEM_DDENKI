#!/bin/bash
# 全アプリ一括起動スクリプト
# Usage: ./start_all.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== ケンモチ電機 施工コスト最適化システム ==="
echo ""

# 1. 材料管理 (Flask, port 5000)
echo "[1/3] 材料管理を起動中... (port 5000)"
cd "$SCRIPT_DIR/material_manager"
python -c "from db import init_db; init_db()" 2>/dev/null
python -c "from app import app; app.run(debug=False, host='0.0.0.0', port=5000, use_reloader=False)" &
PID_MATERIAL=$!
echo "      PID: $PID_MATERIAL"

# 2. 入札案件管理 (Streamlit, port 8501)
echo "[2/4] 入札案件管理を起動中... (port 8501)"
cd "$SCRIPT_DIR/bid_manager"
if command -v streamlit &>/dev/null; then
    streamlit run app.py --server.port 8501 --server.headless true &>/dev/null &
    PID_BID=$!
    echo "      PID: $PID_BID"
else
    echo "      ⚠ streamlit未インストール。skip"
    PID_BID=""
fi

# 3. 作業日報 (Streamlit, port 8502)
echo "[3/4] 作業日報を起動中... (port 8502)"
cd "$SCRIPT_DIR/sagyo-nippou"
if command -v streamlit &>/dev/null; then
    streamlit run app.py --server.port 8502 --server.headless true &>/dev/null &
    PID_NIPPOU=$!
    echo "      PID: $PID_NIPPOU"
else
    echo "      ⚠ streamlit未インストール。skip"
    PID_NIPPOU=""
fi

# 4. ポータルページを開く
echo "[4/4] ポータルページを開きます..."
sleep 2

if command -v xdg-open &>/dev/null; then
    xdg-open "$SCRIPT_DIR/portal/index.html"
elif command -v open &>/dev/null; then
    open "$SCRIPT_DIR/portal/index.html"
else
    echo "      ブラウザで開いてください: file://$SCRIPT_DIR/portal/index.html"
fi

echo ""
echo "=== 起動完了 ==="
echo "  ポータル:   file://$SCRIPT_DIR/portal/index.html"
echo "  材料管理:   http://localhost:5000"
echo "  入札管理:   http://localhost:8501"
echo "  作業日報:   http://localhost:8502"
echo ""
echo "停止するには: kill $PID_MATERIAL $PID_BID $PID_NIPPOU"
echo "または Ctrl+C"

# 待機
wait
