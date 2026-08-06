#!/bin/bash
# Git hookをインストールするスクリプト
# 各PCで1回実行: bash tools/git-hooks/install.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"

cp "$SCRIPT_DIR/pre-push" "$HOOKS_DIR/pre-push"
chmod +x "$HOOKS_DIR/pre-push"

echo "Git hook をインストールしました。"
echo "push前に自動でリモートの最新状態を確認します。"
