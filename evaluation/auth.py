"""人事評価 管理アプリのアクセス制限。

社員IDを入力させ、許可リストに載っているIDだけを通す。
許可リストは admin_users.json（このファイルと同じフォルダ）で管理する。

注意: これは「誰が管理画面を開けるか」を絞るための簡易的な入口であって、
パスワード認証ではない。社員IDを知っていれば誰でも入れる点は理解した上で使う。
社外からアクセスできない社内LAN限定の運用が前提。
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

USERS_FILE = Path(__file__).resolve().parent / "admin_users.json"

# ログイン状態を保持するキー（ブラウザのタブを閉じるまで有効）
SESSION_KEY = "eval_admin_user"


def load_allowed_users() -> list[dict]:
    """許可された社員の一覧を読み込む。

    ファイルが無い・壊れている場合は空リストを返す（＝誰も入れない）。
    アクセス制限は「開けない」側に倒すのが安全なため。
    """
    if not USERS_FILE.exists():
        return []
    try:
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    users = []
    for entry in data.get("allowed", []):
        if isinstance(entry, str):                  # "E001" だけの書き方も許す
            users.append({"id": entry.strip(), "name": ""})
        elif isinstance(entry, dict) and entry.get("id"):
            users.append({"id": str(entry["id"]).strip(), "name": entry.get("name", "")})
    return users


def find_user(employee_id: str, users: list[dict]) -> dict | None:
    """社員IDが許可リストにあれば、その社員を返す。大文字小文字は区別しない。"""
    key = employee_id.strip().upper()
    for u in users:
        if u["id"].upper() == key:
            return u
    return None


def logout():
    st.session_state.pop(SESSION_KEY, None)


def render_sidebar_user():
    """ログイン中の社員をサイドバーに表示し、ログアウトできるようにする。"""
    user = st.session_state.get(SESSION_KEY)
    if not user:
        return
    label = f"{user['name']}（{user['id']}）" if user["name"] else user["id"]
    st.sidebar.success(f"ログイン中: {label}")
    if st.sidebar.button("ログアウト", use_container_width=True):
        logout()
        st.rerun()


def require_login() -> dict:
    """ログイン済みなら社員情報を返す。未ログインならログイン画面を出して停止する。

    呼び出し側は戻り値を受け取った時点で「認証済み」とみなしてよい。
    """
    user = st.session_state.get(SESSION_KEY)
    if user:
        return user

    users = load_allowed_users()

    st.header("🔒 ログイン")
    st.caption("人事評価 管理アプリを利用するには、社員IDの入力が必要です。")

    # 許可リストが空＝設定漏れ。誰も入れない状態なので、その旨をはっきり出す。
    if not users:
        st.error(
            "アクセスを許可された社員IDが1件も登録されていません。\n\n"
            f"`{USERS_FILE.name}` の `allowed` に社員IDを追加してください。"
        )
        st.stop()

    with st.form("login_form"):
        employee_id = st.text_input("社員ID", placeholder="例: E001")
        submitted = st.form_submit_button("ログイン", type="primary", use_container_width=True)

    if submitted:
        if not employee_id.strip():
            st.warning("社員IDを入力してください。")
        else:
            matched = find_user(employee_id, users)
            if matched:
                st.session_state[SESSION_KEY] = matched
                st.rerun()
            else:
                # 存在しないIDか、権限が無いIDかは区別せず同じ文面にする。
                # どのIDが実在するかを推測させないため。
                st.error(
                    f"社員ID「{employee_id.strip()}」には、このアプリへのアクセス権限がありません。\n\n"
                    "権限が必要な場合は管理者に連絡してください。"
                )

    st.stop()
