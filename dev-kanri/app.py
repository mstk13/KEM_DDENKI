"""開発管理システム — Streamlit メインアプリ。

ソフトウェア開発のプロジェクト・タスク管理を行う。
カンバンボード、タスク一覧、進捗ダッシュボードを提供。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import database as db

st.set_page_config(page_title="開発管理 | ケンモチ電機", page_icon="💻", layout="wide")

st.markdown("""
<style>
    h1 { font-size: 2.0rem !important; }
    h2 { font-size: 1.5rem !important; }
    h3 { font-size: 1.25rem !important; }
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    [data-testid="stMetricLabel"] { font-size: 1.0rem !important; }
    .stButton button { font-size: 1.0rem !important; }
    .stExpander summary { font-size: 1.05rem !important; }

    .kanban-card {
        background: #fff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 0.7rem 0.9rem;
        margin-bottom: 0.5rem;
        border-left: 4px solid #3b82f6;
    }
    .kanban-card.pri-critical { border-left-color: #dc2626; }
    .kanban-card.pri-high     { border-left-color: #f59e0b; }
    .kanban-card.pri-medium   { border-left-color: #3b82f6; }
    .kanban-card.pri-low      { border-left-color: #94a3b8; }
    .kanban-card .card-title {
        font-size: 1.0rem; font-weight: 700; color: #1e293b;
        margin-bottom: 0.3rem;
    }
    .kanban-card .card-meta {
        font-size: 0.85rem; color: #64748b;
    }
    .kanban-card .card-badges {
        display: flex; gap: 0.4rem; margin-top: 0.3rem; flex-wrap: wrap;
    }
    .kanban-card .badge {
        display: inline-block; padding: 0.1rem 0.5rem;
        border-radius: 4px; font-size: 0.75rem; font-weight: 600;
    }
    .badge-bug      { background: #fee2e2; color: #991b1b; }
    .badge-feature  { background: #dbeafe; color: #1e40af; }
    .badge-refactor { background: #fef3c7; color: #92400e; }
    .badge-docs     { background: #d1fae5; color: #065f46; }
    .badge-test     { background: #ede9fe; color: #5b21b6; }
    .badge-infra    { background: #f1f5f9; color: #334155; }
    .badge-other    { background: #f1f5f9; color: #64748b; }

    .col-header {
        font-size: 1.1rem; font-weight: 700; text-align: center;
        padding: 0.5rem; border-radius: 8px; margin-bottom: 0.6rem;
    }
</style>
""", unsafe_allow_html=True)

db.init_db()

PRIORITY_COLORS = {"critical": "#dc2626", "high": "#f59e0b", "medium": "#3b82f6", "low": "#94a3b8"}
STATUS_BG = {
    "open": "#f1f5f9", "in_progress": "#dbeafe",
    "review": "#fef3c7", "done": "#d1fae5", "closed": "#f1f5f9",
}


def _select_project() -> dict | None:
    """サイドバーでプロジェクトを選択。"""
    projects = db.list_projects()
    if not projects:
        return None
    st.sidebar.divider()
    pid = st.sidebar.selectbox(
        "プロジェクト",
        [p["id"] for p in projects],
        format_func=lambda i: next((p["name"] for p in projects if p["id"] == i), str(i)),
        key="sidebar_project",
    )
    return db.get_project(pid)


# ===================================================================
# 1. カンバンボード
# ===================================================================
def page_kanban() -> None:
    st.header("カンバンボード")
    project = _select_project()
    if not project:
        st.info("プロジェクトを作成してください。（「プロジェクト管理」ページから）")
        return

    st.caption(f"プロジェクト: **{project['name']}**")

    columns = ["open", "in_progress", "review", "done"]
    col_labels = {
        "open": ("未着手", "#64748b"),
        "in_progress": ("作業中", "#2563eb"),
        "review": ("レビュー中", "#d97706"),
        "done": ("完了", "#16a34a"),
    }

    cols = st.columns(len(columns))
    for col_ui, status in zip(cols, columns):
        label, color = col_labels[status]
        tasks = db.list_tasks(project["id"], status=status)

        with col_ui:
            st.markdown(
                f"<div class='col-header' style='background:{STATUS_BG[status]};color:{color};'>"
                f"{label}（{len(tasks)}）</div>", unsafe_allow_html=True)

            for t in tasks:
                pri = t.get("priority", "medium")
                cat = t.get("category", "feature")
                assignee = t.get("assignee") or "未割当"
                due = t.get("due_date")
                due_str = f" | 期限: {due}" if due else ""

                st.markdown(f"""
                <div class="kanban-card pri-{pri}">
                    <div class="card-title">#{t['id']} {t['title']}</div>
                    <div class="card-meta">{assignee}{due_str}</div>
                    <div class="card-badges">
                        <span class="badge badge-{cat}">{db.CATEGORY_LABELS.get(cat, cat)}</span>
                        <span class="badge" style="background:{PRIORITY_COLORS[pri]}20;
                              color:{PRIORITY_COLORS[pri]};">{db.PRIORITY_LABELS.get(pri, pri)}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

            # ステータス変更ボタン
            if tasks:
                with st.expander("ステータス変更"):
                    for t in tasks:
                        tc1, tc2 = st.columns([2, 1])
                        tc1.write(f"#{t['id']} {t['title']}")
                        next_statuses = [s for s in db.TASK_STATUSES if s != status]
                        new_st = tc2.selectbox(
                            "→", next_statuses,
                            format_func=lambda s: db.STATUS_LABELS.get(s, s),
                            key=f"mv_{t['id']}",
                        )
                        if tc2.button("移動", key=f"mvb_{t['id']}"):
                            db.update_task(t["id"], status=new_st)
                            st.rerun()


# ===================================================================
# 2. タスク管理
# ===================================================================
def page_tasks() -> None:
    st.header("タスク管理")
    project = _select_project()
    if not project:
        st.info("プロジェクトを作成してください。")
        return

    st.caption(f"プロジェクト: **{project['name']}**")
    members = db.list_members()

    # --- タスク追加 ---
    with st.expander("タスクを追加", expanded=False):
        with st.form("add_task_form"):
            title = st.text_input("タイトル*", placeholder="例: ログイン画面のバグ修正")
            desc = st.text_area("説明", height=100, placeholder="詳細な説明・再現手順など")
            c1, c2, c3 = st.columns(3)
            priority = c1.selectbox("優先度", db.TASK_PRIORITIES,
                                    format_func=lambda p: db.PRIORITY_LABELS[p], index=1)
            category = c2.selectbox("カテゴリ", db.TASK_CATEGORIES,
                                    format_func=lambda c: db.CATEGORY_LABELS[c])
            assignee = c3.selectbox("担当者", [""] + members)
            c4, c5, c6 = st.columns(3)
            reporter = c4.selectbox("報告者", [""] + members)
            due = c5.date_input("期限", value=None)
            estimate = c6.number_input("見積時間(h)", min_value=0.0, step=0.5, value=0.0)

            if st.form_submit_button("タスクを作成", type="primary"):
                if not title.strip():
                    st.error("タイトルは必須です。")
                else:
                    tid = db.add_task(
                        project["id"], title.strip(), desc,
                        priority=priority, category=category,
                        assignee=assignee, reporter=reporter,
                        due_date=due.isoformat() if due else None,
                        estimate_h=estimate or None,
                    )
                    st.success(f"タスク #{tid} を作成しました。")
                    st.rerun()

    # --- フィルタ ---
    st.divider()
    fc1, fc2 = st.columns(2)
    filter_status = fc1.selectbox("ステータス絞り込み",
        ["すべて"] + db.TASK_STATUSES,
        format_func=lambda s: db.STATUS_LABELS.get(s, s) if s != "すべて" else "すべて")
    status_val = None if filter_status == "すべて" else filter_status

    tasks = db.list_tasks(project["id"], status=status_val)
    st.caption(f"{len(tasks)} 件のタスク")

    if not tasks:
        st.info("タスクがありません。上の「タスクを追加」から作成してください。")
        return

    # --- タスク一覧 ---
    for t in tasks:
        pri = t.get("priority", "medium")
        cat = t.get("category", "feature")
        status = t.get("status", "open")

        with st.expander(
            f"{'🔴' if pri == 'critical' else '🟡' if pri == 'high' else '🔵' if pri == 'medium' else '⚪'} "
            f"#{t['id']} {t['title']}　"
            f"[{db.STATUS_LABELS.get(status, status)}]"
        ):
            # 詳細表示
            if t.get("description"):
                st.markdown(t["description"])

            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.write(f"**カテゴリ**: {db.CATEGORY_LABELS.get(cat, cat)}")
            mc2.write(f"**担当**: {t.get('assignee') or '未割当'}")
            mc3.write(f"**期限**: {t.get('due_date') or '未設定'}")
            mc4.write(f"**見積**: {t.get('estimate_h') or '-'}h / **実績**: {t.get('actual_h') or '-'}h")

            # 編集フォーム
            st.markdown("---")
            ec1, ec2, ec3 = st.columns(3)
            new_status = ec1.selectbox("ステータス", db.TASK_STATUSES,
                index=db.TASK_STATUSES.index(status) if status in db.TASK_STATUSES else 0,
                format_func=lambda s: db.STATUS_LABELS.get(s, s),
                key=f"ts_{t['id']}")
            new_assignee = ec2.selectbox("担当者", [""] + members,
                index=(members.index(t["assignee"]) + 1) if t.get("assignee") in members else 0,
                key=f"ta_{t['id']}")
            new_actual = ec3.number_input("実績時間(h)", min_value=0.0, step=0.5,
                value=float(t.get("actual_h") or 0), key=f"th_{t['id']}")

            bc1, bc2 = st.columns([3, 1])
            if bc1.button("更新", key=f"tu_{t['id']}", type="primary"):
                db.update_task(t["id"], status=new_status, assignee=new_assignee,
                               actual_h=new_actual or None)
                st.rerun()
            if bc2.button("削除", key=f"td_{t['id']}"):
                db.delete_task(t["id"])
                st.rerun()

            # コメント
            st.markdown("---")
            st.markdown("**コメント**")
            comments = db.list_comments(t["id"])
            for c in comments:
                st.markdown(f"> **{c['author']}** ({str(c['created_at'])[:16]}): {c['body']}")
            with st.form(f"comment_form_{t['id']}"):
                cc1, cc2 = st.columns([1, 3])
                c_author = cc1.selectbox("名前", [""] + members, key=f"ca_{t['id']}")
                c_body = cc2.text_input("コメント", key=f"cb_{t['id']}")
                if st.form_submit_button("投稿"):
                    if c_body.strip():
                        db.add_comment(t["id"], c_author or "匿名", c_body.strip())
                        st.rerun()


# ===================================================================
# 3. プロジェクト管理
# ===================================================================
def page_projects() -> None:
    st.header("プロジェクト管理")

    members = db.list_members()

    # --- プロジェクト追加 ---
    with st.expander("プロジェクトを作成"):
        with st.form("add_project_form"):
            p_name = st.text_input("プロジェクト名*", placeholder="例: 施工管理システム v2")
            p_desc = st.text_area("説明", height=80)
            pa1, pa2 = st.columns(2)
            p_assignee = pa1.selectbox("責任者 (assignee)", [""] + members, key="proj_assignee")
            p_repo = pa2.text_input("リポジトリURL", placeholder="https://github.com/...")
            pc1, pc2 = st.columns(2)
            p_start = pc1.date_input("開始日", value=None)
            p_due = pc2.date_input("期限", value=None)

            if st.form_submit_button("作成", type="primary"):
                if not p_name.strip():
                    st.error("プロジェクト名は必須です。")
                else:
                    pid = db.add_project(
                        p_name.strip(), p_desc,
                        assignee=p_assignee,
                        repo_url=p_repo,
                        start_date=p_start.isoformat() if p_start else None,
                        due_date=p_due.isoformat() if p_due else None,
                    )
                    st.success(f"プロジェクト「{p_name.strip()}」を作成しました（ID: {pid}）。")
                    st.rerun()

    st.divider()

    # --- プロジェクト一覧 ---
    projects = db.list_projects()
    if not projects:
        st.info("プロジェクトがありません。上の「プロジェクトを作成」から追加してください。")
        return

    for p in projects:
        stats = db.get_project_stats(p["id"])
        total = stats["total"]
        completed = stats["completed"]
        pct = (completed / total * 100) if total > 0 else 0

        status_color = {"進行中": "#3b82f6", "計画中": "#94a3b8", "完了": "#22c55e",
                        "中断": "#ef4444"}.get(p.get("status", ""), "#6b7280")

        assignee_text = p.get('assignee') or '未設定'

        st.markdown(f"""
        <div style="background:#fff;border:2px solid #e2e8f0;border-radius:10px;
                    padding:1.2rem;margin-bottom:0.8rem;">
            <div style="display:flex;align-items:center;gap:0.8rem;margin-bottom:0.5rem;">
                <span style="font-size:1.3rem;font-weight:700;color:#1e293b;">{p['name']}</span>
                <span style="background:{status_color};color:#fff;padding:0.15rem 0.6rem;
                      border-radius:5px;font-size:0.85rem;font-weight:600;">{p.get('status','')}</span>
            </div>
            <div style="font-size:1.0rem;color:#1e40af;font-weight:600;margin-bottom:0.3rem;">
                責任者: {assignee_text}
            </div>
            <div style="font-size:0.95rem;color:#64748b;margin-bottom:0.4rem;">
                {p.get('description','') or '説明なし'}
            </div>
            <div style="font-size:0.9rem;color:#94a3b8;">
                タスク: {completed}/{total} 完了 ({pct:.0f}%)
                {'　|　バグ: ' + str(stats['open_bugs']) + '件' if stats['open_bugs'] else ''}
                {'　|　緊急: ' + str(stats['critical']) + '件' if stats['critical'] else ''}
                {'　|　見積: ' + str(stats['total_estimate']) + 'h / 実績: ' + str(stats['total_actual']) + 'h' if stats['total_estimate'] else ''}
            </div>
        </div>
        """, unsafe_allow_html=True)

        if total > 0:
            st.progress(pct / 100, text=f"進捗: {completed}/{total} ({pct:.0f}%)")

        # 編集
        with st.expander(f"「{p['name']}」を編集"):
            ec1, ec2, ec3 = st.columns(3)
            new_status = ec1.selectbox("ステータス",
                ["計画中", "進行中", "完了", "中断"],
                index=["計画中", "進行中", "完了", "中断"].index(p["status"])
                    if p.get("status") in ["計画中", "進行中", "完了", "中断"] else 1,
                key=f"ps_{p['id']}")
            cur_assignee = p.get("assignee") or ""
            new_assignee = ec2.selectbox("責任者 (assignee)", [""] + members,
                index=(members.index(cur_assignee) + 1) if cur_assignee in members else 0,
                key=f"pa_{p['id']}")
            if ec3.button("更新", key=f"pu_{p['id']}", type="primary"):
                db.update_project(p["id"], status=new_status, assignee=new_assignee)
                st.rerun()
            if st.button("プロジェクトを削除", key=f"pd_{p['id']}"):
                db.delete_project(p["id"])
                st.rerun()


# ===================================================================
# 4. ダッシュボード
# ===================================================================
def page_dashboard() -> None:
    st.header("ダッシュボード")
    project = _select_project()
    if not project:
        st.info("プロジェクトを作成してください。")
        return

    st.caption(f"プロジェクト: **{project['name']}**")
    stats = db.get_project_stats(project["id"])
    total = stats["total"]
    completed = stats["completed"]

    # KPI
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("総タスク", total)
    c2.metric("完了", completed)
    c3.metric("作業中", stats["in_progress"])
    c4.metric("未着手", stats["open_count"])
    c5.metric("未解決バグ", stats["open_bugs"])

    if total > 0:
        pct = completed / total * 100
        st.progress(pct / 100, text=f"全体進捗: {completed}/{total} ({pct:.0f}%)")

    st.divider()

    all_tasks = db.list_tasks(project["id"])
    if not all_tasks:
        st.info("タスクがありません。")
        return

    # ステータス分布
    col_a, col_b = st.columns(2)
    with col_a:
        status_data = {}
        for t in all_tasks:
            s = db.STATUS_LABELS.get(t["status"], t["status"])
            status_data[s] = status_data.get(s, 0) + 1
        fig = px.pie(names=list(status_data.keys()), values=list(status_data.values()),
                     title="ステータス分布",
                     color_discrete_sequence=["#94a3b8", "#3b82f6", "#f59e0b", "#22c55e", "#6b7280"])
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

    # カテゴリ分布
    with col_b:
        cat_data = {}
        for t in all_tasks:
            c = db.CATEGORY_LABELS.get(t["category"], t["category"])
            cat_data[c] = cat_data.get(c, 0) + 1
        fig = px.bar(x=list(cat_data.keys()), y=list(cat_data.values()),
                     title="カテゴリ別タスク数",
                     color_discrete_sequence=["#3b82f6"])
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=40, b=10),
                          xaxis_title="", yaxis_title="件数")
        st.plotly_chart(fig, use_container_width=True)

    # 担当者別
    st.subheader("担当者別タスク数")
    assignee_data = {}
    for t in all_tasks:
        a = t.get("assignee") or "未割当"
        if a not in assignee_data:
            assignee_data[a] = {"未着手": 0, "作業中": 0, "レビュー中": 0, "完了": 0}
        s_label = db.STATUS_LABELS.get(t["status"], "その他")
        if s_label in assignee_data[a]:
            assignee_data[a][s_label] += 1
    if assignee_data:
        df_a = pd.DataFrame(assignee_data).T
        df_a.index.name = "担当者"
        st.dataframe(df_a, use_container_width=True)


# ===================================================================
# ルーティング
# ===================================================================
PAGES = {
    "カンバンボード": page_kanban,
    "タスク管理": page_tasks,
    "プロジェクト管理": page_projects,
    "ダッシュボード": page_dashboard,
}

st.sidebar.title("開発管理")
st.sidebar.caption("株式会社ケンモチ電機")

if "page" not in st.session_state:
    st.session_state["page"] = "カンバンボード"
choice = st.sidebar.radio("メニュー", list(PAGES.keys()),
                          index=list(PAGES.keys()).index(st.session_state.get("page", "カンバンボード"))
                          if st.session_state.get("page") in PAGES else 0)
st.session_state["page"] = choice

PAGES[choice]()
