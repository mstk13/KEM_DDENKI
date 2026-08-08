#!/bin/bash
# ============================================================
# KEM_DDENKI 自動デプロイ（ポーリング方式）
#
# GitHub を定期的に確認し、対象ブランチに新しいコミットがあれば
# そのサーバーへ取り込んで反映する。Webhook と違い GitHub からサーバーへの
# 到達性が不要なため、NAT の内側にある社内PCでもそのまま動く。
#
# 使い方:
#   bash tools/autodeploy/autodeploy.sh              # 設定ファイルの全環境を処理
#   bash tools/autodeploy/autodeploy.sh dev          # 指定した環境だけ処理
#
# 設定ファイル（既定: ~/kem-ops/autodeploy.conf）:
#   環境名|リポジトリのパス|ブランチ|ヘルスチェックURL|backup(取る場合のみ)
#
# サーバー上のリポジトリは「GitHub の鏡」として扱う。ローカルの変更は
# reset --hard / clean で破棄されるため、サーバー上で直接編集しないこと。
# ============================================================

set -uo pipefail

# --- 自身をコピーしてから実行する ---------------------------------
# このスクリプト自体がリポジトリ内にあるため、git reset --hard の最中に
# 本体が書き換わると bash が続きを読み損ねて誤動作する。複製から動かす。
if [ -z "${KEM_AUTODEPLOY_REEXEC:-}" ]; then
    _copy="$(mktemp -t autodeploy.XXXXXX)"
    cp "$0" "$_copy" || exit 1
    KEM_AUTODEPLOY_REEXEC=1 exec bash "$_copy" "$@"
fi
trap 'rm -f "$0"' EXIT

CONF="${KEM_AUTODEPLOY_CONF:-$HOME/kem-ops/autodeploy.conf}"
LOCK_DIR="${KEM_AUTODEPLOY_LOCK:-$HOME/kem-ops/autodeploy.lock}"
ONLY_ENV="${1:-}"

HEALTH_RETRIES=25
HEALTH_INTERVAL=6

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

if [ ! -f "$CONF" ]; then
    log "ERROR: 設定ファイルが見つかりません: $CONF"
    exit 1
fi

# --- 多重起動の防止 ------------------------------------------------
# mkdir は原子的なので、これでロックを取る。前回が異常終了して残った
# ロックは 1 時間で無効とみなす。
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    if [ -n "$(find "$LOCK_DIR" -maxdepth 0 -mmin +60 2>/dev/null)" ]; then
        log "WARN: 1時間以上前のロックが残っていたため解放します"
        rm -rf "$LOCK_DIR"
        mkdir "$LOCK_DIR" 2>/dev/null || { log "ERROR: ロックを取得できません"; exit 1; }
    else
        log "前回の実行が進行中のためスキップします"
        exit 0
    fi
fi
trap 'rm -rf "$LOCK_DIR"; rm -f "$0"' EXIT

health_check() {
    local url="$1" i code
    for i in $(seq 1 "$HEALTH_RETRIES"); do
        code=$(curl -s -o /dev/null -m 10 -w "%{http_code}" "$url" 2>/dev/null)
        if [ "$code" = "200" ]; then
            return 0
        fi
        sleep "$HEALTH_INTERVAL"
    done
    log "  ヘルスチェック失敗: $url (最後の応答: ${code:-応答なし})"
    return 1
}

write_version() {
    # コンテナからは .git が見えないため、稼働中のコミットをファイルに残す。
    # /health/ がこれを読んで返す（push した変更が入ったかの確認用）。
    local saas_dir="$1" branch="$2"
    printf '%s|%s|%s\n' \
        "$(git rev-parse --short HEAD)" \
        "$branch" \
        "$(date '+%Y-%m-%d %H:%M:%S')" \
        > "$saas_dir/deployed_version.txt"
}

bring_up() {
    local saas_dir="$1"
    ( cd "$saas_dir" && docker compose up -d --build ) >/dev/null 2>&1 || return 1
    # コードは bind mount で渡しているため、イメージに変化がないと
    # コンテナが再作成されず新しいコードが読み込まれない。明示的に再起動する
    # （entrypoint.sh がここで migrate と collectstatic も実行する）。
    ( cd "$saas_dir" && docker compose restart web ) >/dev/null 2>&1 || return 1
    return 0
}

deploy_one() {
    local name="$1" repo_dir="$2" branch="$3" health_url="$4" want_backup="$5"
    local saas_dir="$repo_dir/saas"

    if [ ! -d "$repo_dir/.git" ]; then
        log "[$name] ERROR: git リポジトリではありません: $repo_dir"
        return 1
    fi

    cd "$repo_dir" || return 1

    if ! git fetch origin "$branch" --quiet 2>/dev/null; then
        log "[$name] WARN: git fetch に失敗しました（ネットワーク／認証を確認）"
        return 1
    fi

    local current target
    current=$(git rev-parse HEAD)
    target=$(git rev-parse "origin/$branch")

    if [ "$current" = "$target" ]; then
        # 変更なし。ここで必ず抜けることで、ローカルに未コミットの変更が
        # 残っている環境を勝手に巻き戻してしまう事故を防いでいる。
        return 0
    fi

    log "[$name] 更新を検出: ${current:0:7} → ${target:0:7} ($branch)"
    git log --oneline "$current..$target" 2>/dev/null | head -10 | sed 's/^/[  ] /'

    if [ "$want_backup" = "backup" ]; then
        log "[$name] 反映前にバックアップを取得します"
        bash "$saas_dir/scripts/backup.sh" >/dev/null 2>&1 \
            && log "[$name] バックアップ完了" \
            || log "[$name] WARN: バックアップに失敗しました（デプロイは続行）"
    fi

    git reset --hard "origin/$branch" --quiet || { log "[$name] ERROR: reset に失敗"; return 1; }
    git clean -fd --quiet   # .gitignore 対象（.env 等）は消さない
    write_version "$saas_dir" "$branch"

    if bring_up "$saas_dir" && health_check "$health_url"; then
        log "[$name] デプロイ成功: $(git log --oneline -1)"
        return 0
    fi

    # --- 失敗したので元のコミットへ戻す ---
    log "[$name] ERROR: デプロイ後の起動確認に失敗。${current:0:7} へ巻き戻します"
    git reset --hard "$current" --quiet
    git clean -fd --quiet
    write_version "$saas_dir" "$branch"
    if bring_up "$saas_dir" && health_check "$health_url"; then
        log "[$name] 巻き戻し完了。アプリは元のバージョンで動作中です"
    else
        log "[$name] CRITICAL: 巻き戻し後も起動しません。手動対応が必要です"
    fi
    if [ "$want_backup" = "backup" ]; then
        log "[$name] NOTE: マイグレーションが途中まで適用された可能性があります。"
        log "[$name]       必要なら反映前のバックアップから復元してください。"
    fi
    return 1
}

rc=0
while IFS='|' read -r name repo_dir branch health_url want_backup; do
    case "$name" in ''|\#*) continue ;; esac
    if [ -n "$ONLY_ENV" ] && [ "$ONLY_ENV" != "$name" ]; then
        continue
    fi
    deploy_one "$name" "$repo_dir" "$branch" "$health_url" "${want_backup:-}" || rc=1
done < "$CONF"

exit $rc
