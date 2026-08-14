#!/bin/sh
# scheduler.sh の判定を、date コマンドを差し替えて検証する。
# 実ジョブは動かさない（SCHEDULER_DRY_RUN=1）。
#
# pytest ではなくシェルスクリプトなのは、検証対象がシェルであり、
# 「本番と同じ /bin/sh（dash）で動くか」自体が確認したい点だから。
# bash でしか通らない書き方（10# など）を pytest では検出できない。
#
#   docker compose run --rm --entrypoint sh cron /app/scripts/test_scheduler.sh
set -u

STATE=/tmp/sched_state
PASS=0
FAIL=0

reset_state() {
    if [ -d "$STATE" ]; then
        find "$STATE" -type f -delete
    fi
    mkdir -p "$STATE"
}

check() {
    desc="$1"; fake="$2"; expect="$3"
    mkdir -p /tmp/fakebin
    printf '#!/bin/sh\nexec /bin/date -d "%s" "$@"\n' "$fake" > /tmp/fakebin/date
    chmod +x /tmp/fakebin/date

    out=$(PATH=/tmp/fakebin:$PATH SCHEDULER_ONCE=1 SCHEDULER_DRY_RUN=1 \
          SCHEDULER_STATE_DIR="$STATE" sh /app/scripts/scheduler.sh 2>&1)
    got=$(echo "$out" | grep -c "を実行します")

    if [ "$got" = "$expect" ]; then
        PASS=$((PASS + 1))
        echo "  OK   $desc  (実行 $got 件)"
    else
        FAIL=$((FAIL + 1))
        echo "  NG   $desc  期待=$expect 実際=$got"
        echo "$out" | sed 's/^/         /'
    fi
}

echo "=== 未実行の状態 ==="
reset_state
check "偶数日 06:59 → まだ何も動かない" "2026-08-14 06:59" 0
reset_state
check "偶数日 07:00 → scrape のみ" "2026-08-14 07:00" 1
reset_state
check "偶数日 08:30 → 2つとも（遅れても拾う）" "2026-08-14 08:30" 2
reset_state
check "奇数日 08:30 → alerts のみ" "2026-08-15 08:30" 1
reset_state
check "偶数日 23:59 → 2つとも（取りこぼさない）" "2026-08-14 23:59" 2

echo "=== 実行記録がある場合（再起動の想定） ==="
reset_state
echo "2026-08-14" > "$STATE/scrape_bids"
echo "2026-08-14" > "$STATE/send_document_alerts"
check "同日に再起動 → 二重実行しない" "2026-08-14 09:00" 0
check "翌日になったら再び動く" "2026-08-15 09:00" 1

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ]
