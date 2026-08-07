#!/bin/bash
# KEM_DDENKI 日次バックアップスクリプト
# Windowsタスクスケジューラまたはcronで毎日実行してください
#
# 使い方:
#   bash scripts/backup.sh /mnt/d/backup
#   （/mnt/d/backup は外付けUSBのパスに変更してください）

BACKUP_DIR="${1:-/mnt/d/backup/kem_ddenki}"
DATE=$(date +%Y%m%d_%H%M%S)
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR"

echo "[$(date)] バックアップ開始..."

# 1. PostgreSQLダンプ
docker compose exec -T db pg_dump -U postgres kensetsu_saas | gzip > "$BACKUP_DIR/db_${DATE}.sql.gz"
if [ $? -eq 0 ]; then
    echo "[$(date)] DB バックアップ完了: db_${DATE}.sql.gz"
else
    echo "[$(date)] ERROR: DB バックアップ失敗"
    exit 1
fi

# 2. mediaファイル（画像・PDF等）
if [ -d "media" ]; then
    tar czf "$BACKUP_DIR/media_${DATE}.tar.gz" media/
    echo "[$(date)] media バックアップ完了: media_${DATE}.tar.gz"
fi

# 3. 古いバックアップを削除
find "$BACKUP_DIR" -name "db_*.sql.gz" -mtime +${KEEP_DAYS} -delete
find "$BACKUP_DIR" -name "media_*.tar.gz" -mtime +${KEEP_DAYS} -delete
echo "[$(date)] ${KEEP_DAYS}日より古いバックアップを削除"

echo "[$(date)] バックアップ完了"
