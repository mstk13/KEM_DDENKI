#!/bin/bash
# ============================================================
# 自動デプロイスクリプト
# GitHub Webhook レシーバーから呼ばれる
# ============================================================

set -e

# プロジェクトルート（saas/ の親ディレクトリ）
REPO_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
SAAS_DIR="${REPO_DIR}/saas"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') デプロイ開始 ==="
echo "リポジトリ: ${REPO_DIR}"

cd "${REPO_DIR}"

# 1. 最新コードを取得
echo "--- git pull ---"
git fetch origin developer
git checkout developer
git pull origin developer

# 2. マイグレーション実行
cd "${SAAS_DIR}"
echo "--- マイグレーション ---"
if [ -f "docker-compose.yml" ] && docker compose ps --status running | grep -q "web"; then
    # Docker環境
    docker compose exec -T web python manage.py migrate --no-input
    echo "--- 静的ファイル収集 ---"
    docker compose exec -T web python manage.py collectstatic --no-input 2>/dev/null || true
    echo "--- アプリ再起動 ---"
    docker compose restart web
else
    # 非Docker環境（直接実行）
    python manage.py migrate --no-input
    python manage.py collectstatic --no-input 2>/dev/null || true
    # gunicorn の場合は HUP シグナルで graceful restart
    if pgrep -f "gunicorn.*config.wsgi" > /dev/null; then
        echo "--- Gunicorn 再起動 ---"
        pkill -HUP -f "gunicorn.*config.wsgi"
    fi
fi

echo "=== $(date '+%Y-%m-%d %H:%M:%S') デプロイ完了 ==="
