"""全アプリ共通 — GitHub反映ユーティリティ。

devブランチで動作中のときだけ「GitHub反映」ボタンを表示し、
変更をコミット＆プッシュする。mainブランチでは何も表示しない。
"""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent


def current_branch() -> str:
    """現在のgitブランチ名を返す。取得できなければ空文字。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(REPO_DIR), capture_output=True, text=True, timeout=5,
        )
        branch = result.stdout.strip()
        return branch if result.returncode == 0 and branch and branch != "HEAD" else ""
    except Exception:
        return ""


def is_dev() -> bool:
    """devブランチかどうか。二重チェックで安全性を確保。

    1. 環境変数 KEM_DEV_MODE=1 が設定されていること（docker-compose.ymlで制御）
    2. 実際のgitブランチが dev であること
    両方が揃わなければFalseを返す。mainブランチではボタンが絶対に出ない。
    """
    import os
    if os.getenv("KEM_DEV_MODE") != "1":
        return False
    return current_branch() == "dev"


def push_changes(app_name: str, files: list[str]) -> tuple[bool, str]:
    """指定ファイルをadd→commit→pushする。

    Args:
        app_name: アプリ名（コミットメッセージ用）
        files: git addするファイルパス（リポジトリルートからの相対パス）

    Returns:
        (成功したか, メッセージ)
    """
    try:
        subprocess.run(
            ["git", "add"] + files,
            cwd=str(REPO_DIR), capture_output=True, text=True, check=True, timeout=10,
        )
        diff = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(REPO_DIR), capture_output=True, text=True, timeout=5,
        )
        if not diff.stdout.strip():
            return True, "変更はありません（既に最新です）。"

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        subprocess.run(
            ["git", "commit", "-m", f"update({app_name}): ブラウザから変更を反映（{now}）"],
            cwd=str(REPO_DIR), capture_output=True, text=True, check=True, timeout=10,
        )
        result = subprocess.run(
            ["git", "push", "origin", "dev"],
            cwd=str(REPO_DIR), capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return False, f"push失敗: {result.stderr}"
        return True, "GitHubに反映しました（ブランチ: dev）。"
    except subprocess.CalledProcessError as e:
        return False, f"エラー: {e.stderr or e.stdout or str(e)}"
    except Exception as e:
        return False, f"エラー: {str(e)}"


def render_sync_button(app_name: str, files: list[str], key: str = "sync_github") -> None:
    """devブランチの場合のみ「GitHub反映」ボタンを表示する。Streamlit用。"""
    if not is_dev():
        return

    import streamlit as st

    st.divider()
    st.subheader("🔄 GitHubに反映（dev）")
    st.caption("現在のデータ・設定をGitHubのdevブランチにプッシュします。")
    if st.button("GitHubに反映する", type="primary", use_container_width=True, key=key):
        with st.spinner("GitHubに反映中..."):
            ok, msg = push_changes(app_name, files)
        if ok:
            st.success(msg)
        else:
            st.error(msg)
