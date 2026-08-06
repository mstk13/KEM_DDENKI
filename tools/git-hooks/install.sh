#!/bin/bash
# Git hookをインストールするスクリプト
# 使い方:
#   Linux/Mac/WSL: bash tools/git-hooks/install.sh
#   Windows (Git Bash): bash tools/git-hooks/install.sh
#   Windows (コマンドプロンプト): git bash tools/git-hooks/install.sh
#
# ※ リポジトリのルートディレクトリから実行してください

# スクリプトのディレクトリを取得
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"

if [ ! -d "$HOOKS_DIR" ]; then
    echo "エラー: .git/hooks ディレクトリが見つかりません"
    echo "リポジトリのルートから実行してください"
    exit 1
fi

cp "$SCRIPT_DIR/pre-push" "$HOOKS_DIR/pre-push"
chmod +x "$HOOKS_DIR/pre-push" 2>/dev/null || true

echo ""
echo "=== Git hook インストール完了 ==="
echo "push前に自動でリモートの最新状態を確認します。"
echo ""
