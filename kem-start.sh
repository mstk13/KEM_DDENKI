#!/bin/bash
# KEM_DDENKI ワンクリック起動スクリプト
set -e

cd "$(dirname "$0")/saas"

echo "=== ケンモチ電機 業務管理システム 起動中 ==="

# .env がなければ作成
if [ ! -f .env ]; then
    echo ".env が見つかりません。.env.example からコピーします..."
    cp .env.example .env
fi

# Docker が起動しているか確認
if ! docker info > /dev/null 2>&1; then
    echo "Docker が起動していません。Docker Desktop を起動してください。"
    exit 1
fi

# コンテナ起動
echo "Docker コンテナを起動しています..."
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# DB の準備完了を待つ
echo "データベースの準備を待っています..."
for i in $(seq 1 30); do
    if docker compose exec -T db pg_isready -U postgres > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# マイグレーション実行
echo "マイグレーションを実行しています..."
docker compose exec -T web python manage.py migrate --no-input

# アプリの応答を待つ
echo "アプリの起動を待っています..."
for i in $(seq 1 30); do
    if curl -s -o /dev/null http://localhost:8000/ 2>/dev/null; then
        break
    fi
    sleep 1
done

echo ""
echo "=== 起動完了! ==="
echo "ブラウザで http://localhost:8000 を開きます..."

# Windows側のブラウザで開く
cmd.exe /c start http://localhost:8000 2>/dev/null || true
