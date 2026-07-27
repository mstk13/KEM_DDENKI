#!/bin/bash
# ケンモチ電機 サーバーPC 初回セットアップ
#
# 実行方法:
#   chmod +x docker/setup_server.sh
#   ./docker/setup_server.sh

set -e

echo "========================================"
echo "  ケンモチ電機 サーバーセットアップ"
echo "========================================"
echo ""

# Docker がインストールされているか確認
if ! command -v docker &>/dev/null; then
    echo "[1/3] Docker をインストール中..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo ""
    echo "Docker をインストールしました。"
    echo "一度ログアウトして再ログインしてから、再度このスクリプトを実行してください。"
    exit 0
fi

echo "[1/3] Docker: $(docker --version)"

# .env がなければ .env.example からコピー
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    cp .env.example .env
    echo "[INFO] .env ファイルを作成しました。必要に応じて編集してください。"
fi

# 全アプリをビルド・起動
echo ""
echo "[2/3] 全アプリをビルド・起動中...（初回は数分かかります）"
docker compose up -d --build

# 自動更新の cron を登録（毎朝5時）
echo ""
echo "[3/3] 自動更新を設定中..."
REPO_DIR="$(pwd)"
CRON_CMD="0 5 * * * cd $REPO_DIR && bash docker/update-cron.sh >> /var/log/kem_update.log 2>&1"
(crontab -l 2>/dev/null | grep -v "kem_update" ; echo "$CRON_CMD") | crontab -

# サーバーIPを表示
echo ""
echo "========================================"
echo "  セットアップ完了"
echo "========================================"
echo ""
echo "  ブラウザで http://localhost/ を開いてください。"
echo ""
echo "  他のPCからアクセスする場合:"
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -n "$IP" ]; then
    echo "    http://$IP/"
fi
echo ""
echo "  毎朝5時に自動更新されます。"
echo "  管理コマンド: ./docker/manage.sh --help"
echo "========================================"
