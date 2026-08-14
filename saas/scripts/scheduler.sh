#!/bin/sh
# 定時実行スケジューラ。cron コンテナの中身。
#
# cron を使わない理由:
#   - python:3.12-slim に cron は入っておらず crontab/crond が 127 で落ちる
#   - cron を入れてもジョブに環境変数が渡らず DB_HOST 等が欠ける
#
# 「予定時刻ちょうど」ではなく「予定時刻を過ぎていて、その日まだ
# 実行していなければ実行する」という判定にしている。理由は2つ。
#
#   1. sleep と分の完全一致だと取りこぼす
#      ループ1周は sleep + 実行時間なので必ず60秒を少し超え、
#      位相が少しずつずれて数日に1回ある1分が丸ごと飛ぶ。
#   2. 長いジョブが後続を潰す
#      07:00 の scrape_bids が1時間以上かかると、その間ループが止まり
#      08:00 の send_document_alerts が同日分ごと抜ける。
#      予定時刻を過ぎていれば拾えるようにしておけば、遅れて実行される。
#
# 実行記録はファイルに残す。コンテナ再起動で消えると、自動デプロイの
# たびに同じジョブが走り直してしまうため。
#
# 環境変数（既定値で本番動作。テスト時のみ上書きする）:
#   SCHEDULER_INTERVAL   判定間隔の秒数（既定 30）
#   SCHEDULER_STATE_DIR  実行記録の置き場（既定 /app/media/.scheduler）
#   SCHEDULER_DRY_RUN    1 なら実際には実行せずログだけ出す
#   SCHEDULER_ONCE       1 なら1周だけ判定して終了する

set -u

INTERVAL="${SCHEDULER_INTERVAL:-30}"
STATE_DIR="${SCHEDULER_STATE_DIR:-/app/media/.scheduler}"
DRY_RUN="${SCHEDULER_DRY_RUN:-0}"
ONCE="${SCHEDULER_ONCE:-0}"

log() { echo "[$(date '+%F %T')] $*"; }

# 先頭の 0 を落とす。date は 08 や 009 を返すが、算術式ではこれが
# 8進数と解釈されて "invalid number" になる。
#
# bash なら 10#08 と書けるが、このコンテナの /bin/sh は dash であり
# 10# は構文エラーになる。しかも dash は算術構文エラーでスクリプト自体を
# 終了させる（終了コード2）。restart: always と相まって再起動ループになり、
# ジョブは永久に走らない。実際にこの書き方で本番が壊れていた。
strip_zeros() {
    v="$1"
    while [ "${v#0}" != "$v" ]; do
        v="${v#0}"
    done
    [ -n "$v" ] || v=0
    echo "$v"
}

# 実行記録を読む。無ければ空。
read_state() {
    if [ -f "$STATE_DIR/$1" ]; then
        cat "$STATE_DIR/$1"
    else
        echo ""
    fi
}

write_state() {
    mkdir -p "$STATE_DIR" 2>/dev/null || true
    echo "$2" > "$STATE_DIR/$1" 2>/dev/null || \
        log "警告: 実行記録を保存できませんでした ($STATE_DIR/$1)"
}

# $1=記録名 $2=表示名 $3.. = manage.py に渡す引数
run_job() {
    state_key="$1"; label="$2"; shift 2
    write_state "$state_key" "$(date +%F)"

    if [ "$DRY_RUN" = "1" ]; then
        log "$label を実行します（dry-run のため実際には動かしません）"
        return 0
    fi

    log "$label 開始"
    if python manage.py "$@"; then
        log "$label 完了"
    else
        log "$label が失敗しました"
    fi
}

cd /app || exit 1
mkdir -p "$STATE_DIR" 2>/dev/null || true

log "=== 定時実行サービス起動 ==="
log "  scrape_bids          2日に1回 07:00 以降"
log "  send_document_alerts 毎日     08:00 以降"
log "  判定間隔 ${INTERVAL}秒 / 記録 ${STATE_DIR}"

while true; do
    today=$(date +%F)
    hh=$(strip_zeros "$(date +%H)")
    mm=$(strip_zeros "$(date +%M)")
    doy=$(strip_zeros "$(date +%j)")
    minutes=$(( hh * 60 + mm ))

    # scrape_bids: 偶数日の 07:00 以降に1回
    if [ "$minutes" -ge 420 ] && [ $((doy % 2)) -eq 0 ] &&
       [ "$(read_state scrape_bids)" != "$today" ]; then
        run_job scrape_bids "scrape_bids" scrape_bids --force
    fi

    # send_document_alerts: 毎日 08:00 以降に1回
    if [ "$minutes" -ge 480 ] &&
       [ "$(read_state send_document_alerts)" != "$today" ]; then
        run_job send_document_alerts "send_document_alerts" send_document_alerts
    fi

    [ "$ONCE" = "1" ] && exit 0
    sleep "$INTERVAL"
done
