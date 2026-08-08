#!/bin/bash
# KEM_DDENKI 日次バックアップスクリプト
# Windowsタスクスケジューラまたはcronで毎日実行してください
#
# 使い方:
#   bash scripts/backup.sh /d/backup/kem_ddenki
#   （保存先は外付けUSB等に変更してください。省略時は D:\backup\kem_ddenki）

set -uo pipefail

# タスクスケジューラから起動されると作業ディレクトリが任意の場所になるため、
# docker compose / media パスが解決できるようリポジトリの saas/ へ移動する。
cd "$(dirname "$0")/.." || exit 1

BACKUP_DIR="${1:-/d/backup/kem_ddenki}"
DATE=$(date +%Y%m%d_%H%M%S)
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR"

echo "[$(date)] バックアップ開始..."

# 1. PostgreSQLダンプ
# パイプの終了ステータスは gzip のものになるため、pg_dump の失敗を PIPESTATUS で判定する。
# （これを見ないと、pg_dump が落ちても中身が空の .gz が「成功」として残る）
docker compose exec -T db pg_dump -U postgres kensetsu_saas | gzip > "$BACKUP_DIR/db_${DATE}.sql.gz"
if [ "${PIPESTATUS[0]}" -eq 0 ]; then
    echo "[$(date)] DB バックアップ完了: db_${DATE}.sql.gz ($(du -h "$BACKUP_DIR/db_${DATE}.sql.gz" | cut -f1))"
else
    echo "[$(date)] ERROR: DB バックアップ失敗"
    rm -f "$BACKUP_DIR/db_${DATE}.sql.gz"
    exit 1
fi

# 2. mediaファイル（名刺画像・資格証明書等）
# media は named volume (media_data) にありホスト側の saas/media は空なので、
# コンテナ内の /app/media を tar でストリーム取得する。
# Git Bash から実行すると `-C /app` が Windows パスへ自動変換されてしまうため、
# 引数を sh -c の単一文字列にまとめて変換を回避する。
docker compose exec -T web sh -c 'tar czf - -C /app media' > "$BACKUP_DIR/media_${DATE}.tar.gz"
if [ "${PIPESTATUS[0]}" -eq 0 ]; then
    echo "[$(date)] media バックアップ完了: media_${DATE}.tar.gz ($(du -h "$BACKUP_DIR/media_${DATE}.tar.gz" | cut -f1))"
else
    echo "[$(date)] WARN: media バックアップ失敗（DBは取得済み）"
    rm -f "$BACKUP_DIR/media_${DATE}.tar.gz"
fi

# 3. 古いバックアップを削除
find "$BACKUP_DIR" -name "db_*.sql.gz" -mtime +${KEEP_DAYS} -delete
find "$BACKUP_DIR" -name "media_*.tar.gz" -mtime +${KEEP_DAYS} -delete
echo "[$(date)] ${KEEP_DAYS}日より古いバックアップを削除"

echo "[$(date)] バックアップ完了"
