#!/bin/bash
# 汎用エントリポイント: DB初期化 → アプリ起動
# Usage: /entrypoint.sh <app_dir> <start_command...>

APP_DIR="$1"
shift

cd "/app/$APP_DIR"

# git user設定（コンテナ内からのcommit/push用）
git config --global user.email "kem-system@kenmochi-denki.local" 2>/dev/null || true
git config --global user.name "KEM System" 2>/dev/null || true

# ローカルの db.py を shared/db.py より優先させる
export PYTHONPATH="/app/$APP_DIR:${PYTHONPATH:-}"

# DB初期化（database.py または db.py があれば実行）
if [ -f "database.py" ]; then
    python database.py 2>/dev/null || true
elif [ -f "db.py" ]; then
    python -c "from db import init_db; init_db()" 2>/dev/null || true
fi

exec "$@"
