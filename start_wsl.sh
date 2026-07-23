#!/bin/bash
# WSL上で全アプリをLAN公開モードで起動するスクリプト

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== KEM_DDENKI - All Apps (WSL/LAN mode) ==="
echo ""

# venv
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "[ERROR] .venv not found. Run setup first."
    exit 1
fi

# cleanup
cleanup() {
    echo ""
    echo "Stopping apps..."
    kill $PID_MAT $PID_BID $PID_NIP $PID_EVA 2>/dev/null
    echo "Done."
    exit 0
}
trap cleanup INT TERM

# 1. Material Manager (Flask, port 5000)
echo "[1/4] Material Manager (port 5000)"
cd "$SCRIPT_DIR/material_manager"
python3 -c "from db import init_db; init_db()" 2>/dev/null
python3 -c "from app import app; app.run(debug=False, host='0.0.0.0', port=5000, use_reloader=False)" &
PID_MAT=$!

# 2. Bid Manager (Streamlit, port 8501)
echo "[2/4] Bid Manager (port 8501)"
cd "$SCRIPT_DIR/bid_manager"
streamlit run app.py --server.port 8501 &>/dev/null &
PID_BID=$!

# 3. Work Report (Streamlit, port 8502)
echo "[3/4] Work Report (port 8502)"
cd "$SCRIPT_DIR/sagyo-nippou"
streamlit run app.py --server.port 8502 &>/dev/null &
PID_NIP=$!

# 4. Evaluation (Streamlit, port 8503)
echo "[4/4] Evaluation (port 8503)"
cd "$SCRIPT_DIR/evaluation"
streamlit run app.py --server.port 8503 &>/dev/null &
PID_EVA=$!

sleep 3

# Get Windows IP
WIN_IP=$(cmd.exe /c "ipconfig" 2>/dev/null | iconv -f SHIFT_JIS -t UTF-8 2>/dev/null | grep "IPv4" | head -1 | grep -oP '[\d.]+$' || echo "192.168.0.27")

echo ""
echo "=== Started! ==="
echo ""
echo "  This PC:"
echo "    http://localhost:5000    Material Manager"
echo "    http://localhost:8501    Bid Manager"
echo "    http://localhost:8502    Work Report"
echo "    http://localhost:8503    Evaluation"
echo ""
echo "  Other PCs:"
echo "    http://${WIN_IP}:5000"
echo "    http://${WIN_IP}:8501"
echo "    http://${WIN_IP}:8502"
echo "    http://${WIN_IP}:8503"
echo ""
echo "  Press Ctrl+C to stop all apps."

wait
