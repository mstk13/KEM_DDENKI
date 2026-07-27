#!/bin/bash
# 自動更新スクリプト（cron から呼ばれる）
# 変更があった場合のみ再ビルド

cd "$(dirname "$0")/.."

git fetch origin main --quiet

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    git pull origin main --quiet
    docker compose up -d --build --quiet-pull
    echo "$(date): Updated to $(git rev-parse --short HEAD)"
fi
