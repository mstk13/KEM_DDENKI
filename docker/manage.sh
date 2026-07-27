#!/bin/bash
# ケンモチ電機 Docker管理スクリプト
#
# 使い方:
#   ./docker/manage.sh start          全アプリ起動
#   ./docker/manage.sh stop           全アプリ停止
#   ./docker/manage.sh restart [app]  再起動 (例: ./docker/manage.sh restart bid_manager)
#   ./docker/manage.sh status         稼働状況
#   ./docker/manage.sh update         最新版に更新
#   ./docker/manage.sh logs [app]     ログ表示
#   ./docker/manage.sh backup         DBバックアップ
#   ./docker/manage.sh optional       オプションアプリも含めて起動

cd "$(dirname "$0")/.."

case "$1" in
  start)
    docker compose up -d --build
    echo ""
    echo "全アプリを起動しました。"
    echo "ブラウザで http://localhost/ を開いてください。"
    ;;
  stop)
    docker compose down
    echo "全アプリを停止しました。"
    ;;
  restart)
    if [ -n "$2" ]; then
      docker compose restart "$2"
      echo "$2 を再起動しました。"
    else
      docker compose restart
      echo "全アプリを再起動しました。"
    fi
    ;;
  status)
    docker compose ps
    ;;
  update)
    echo "最新版を取得中..."
    git pull origin main
    echo "アプリを再ビルド・起動中..."
    docker compose up -d --build
    echo "更新完了。"
    ;;
  logs)
    docker compose logs -f --tail=50 ${2:-}
    ;;
  backup)
    BACKUP_DIR="backups/$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    for svc in bid_manager material_manager sagyo_nippou evaluation; do
      docker compose cp "${svc}:/data/." "$BACKUP_DIR/" 2>/dev/null
    done
    echo "バックアップ完了: $BACKUP_DIR"
    ;;
  optional)
    docker compose --profile optional up -d --build
    echo "オプションアプリを含めて起動しました。"
    ;;
  *)
    echo "ケンモチ電機 Docker管理スクリプト"
    echo ""
    echo "使い方: $0 {start|stop|restart|status|update|logs|backup|optional}"
    echo ""
    echo "  start          全アプリ起動"
    echo "  stop           全アプリ停止"
    echo "  restart [app]  再起動 (例: $0 restart bid_manager)"
    echo "  status         稼働状況の確認"
    echo "  update         最新版に更新"
    echo "  logs [app]     ログ表示"
    echo "  backup         DBバックアップ"
    echo "  optional       オプションアプリも含めて起動"
    ;;
esac
