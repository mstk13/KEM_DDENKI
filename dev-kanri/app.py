"""開発管理システム — Streamlit メインアプリ。

プロジェクト単位でタスクを管理する。
1つの画面でプロジェクト選択→カンバン→タスク詳細まで完結する。
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

import database as db

st.set_page_config(page_title="開発管理 | ケンモチ電機", page_icon="💻", layout="wide")

st.markdown("""
<style>
    h1 { font-size: 2.0rem !important; }
    h2 { font-size: 1.5rem !important; }
    h3 { font-size: 1.2rem !important; }
    [data-testid="stMetricValue"] { font-size: 1.5rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.95rem !important; }
    .stButton button { font-size: 1.0rem !important; }

    .kanban-col-header {
        font-size: 1.1rem; font-weight: 700; text-align: center;
        padding: 0.5rem; border-radius: 8px; margin-bottom: 0.5rem;
    }
    .kanban-card {
        background: #fff; border: 1px solid #e2e8f0; border-radius: 8px;
        padding: 0.6rem 0.8rem; margin-bottom: 0.4rem;
        border-left: 4px solid #3b82f6;
    }
    .kanban-card.pri-critical { border-left-color: #dc2626; }
    .kanban-card.pri-high     { border-left-color: #f59e0b; }
    .kanban-card.pri-medium   { border-left-color: #3b82f6; }
    .kanban-card.pri-low      { border-left-color: #94a3b8; }
    .kanban-card .title { font-size: 0.95rem; font-weight: 700; color: #1e293b; }
    .kanban-card .meta  { font-size: 0.8rem; color: #64748b; margin-top: 0.2rem; }
    .badge {
        display: inline-block; padding: 0.1rem 0.4rem;
        border-radius: 4px; font-size: 0.75rem; font-weight: 600;
    }
    .badge-bug     { background: #fee2e2; color: #991b1b; }
    .badge-feature { background: #dbeafe; color: #1e40af; }
    .badge-refactor{ background: #fef3c7; color: #92400e; }
    .badge-docs    { background: #d1fae5; color: #065f46; }
    .badge-test    { background: #ede9fe; color: #5b21b6; }
    .badge-infra   { background: #f1f5f9; color: #334155; }
    .badge-other   { background: #f1f5f9; color: #64748b; }
</style>
""", unsafe_allow_html=True)

db.init_db()

PRIORITY_ICONS = {"critical": "🔴", "high": "🟡", "medium": "🔵", "low": "⚪"}
STATUS_BG = {
    "open": "#f1f5f9", "in_progress": "#dbeafe",
    "review": "#fef3c7", "done": "#d1fae5", "closed": "#e2e8f0",
}
PRIORITY_COLORS = {"critical": "#dc2626", "high": "#f59e0b", "medium": "#3b82f6", "low": "#94a3b8"}


# ===================================================================
# サイドバー: プロジェクト選択 + 新規作成
# ===================================================================
def _sidebar() -> dict | None:
    st.sidebar.title("開発管理")
    st.sidebar.caption("株式会社ケンモチ電機")
    st.sidebar.divider()

    projects = db.list_projects()
    assignee_candidates = db.list_project_assignees()
    members = db.list_members()

    # プロジェクト新規作成
    with st.sidebar.expander("＋ プロジェクト作成"):
        p_name = st.text_input("プロジェクト名", key="sb_pname", placeholder="例: 施工管理v2")
        p_assignee = st.selectbox("責任者 (assignee)", [""] + assignee_candidates, key="sb_passignee")
        if not assignee_candidates:
            st.caption("※ Gコードの社員がいません")
        p_desc = st.text_area("説明", key="sb_pdesc", height=60)
        pc1, pc2 = st.columns(2)
        p_start = pc1.date_input("開始", value=None, key="sb_pstart")
        p_due = pc2.date_input("期限", value=None, key="sb_pdue")
        if st.button("作成", key="sb_pcreate", type="primary", use_container_width=True):
            if p_name.strip():
                db.add_project(p_name.strip(), p_desc, assignee=p_assignee,
                               start_date=p_start.isoformat() if p_start else None,
                               due_date=p_due.isoformat() if p_due else None)
                st.rerun()
            else:
                st.error("名前を入力")

    if not projects:
        st.sidebar.info("プロジェクトを作成してください。")
        return None

    st.sidebar.divider()

    # プロジェクト選択
    pid = st.sidebar.radio(
        "プロジェクト",
        [p["id"] for p in projects],
        format_func=lambda i: next(
            (f"{'●' if p.get('status') == '進行中' else '○'} {p['name']}"
             for p in projects if p["id"] == i), str(i)),
        key="sb_proj",
    )

    project = db.get_project(pid)
    if project:
        stats = db.get_project_stats(pid)
        total = stats["total"]
        done = stats["completed"]
        st.sidebar.caption(
            f"責任者: **{project.get('assignee') or '未設定'}**\n\n"
            f"タスク: {done}/{total} 完了"
            f"{'　|　バグ: ' + str(stats['open_bugs']) if stats['open_bugs'] else ''}"
        )

    return project


# ===================================================================
# メイン画面
# ===================================================================
def main_view(project: dict) -> None:
    members = db.list_members()
    assignee_candidates = db.list_project_assignees()

    # --- プロジェクトヘッダー ---
    hc1, hc2 = st.columns([3, 1])
    hc1.header(project["name"])
    status_opts = ["計画中", "進行中", "完了", "中断"]
    cur_status = project.get("status", "進行中")
    new_status = hc2.selectbox("ステータス", status_opts,
        index=status_opts.index(cur_status) if cur_status in status_opts else 1,
        key="proj_status")
    if new_status != cur_status:
        db.update_project(project["id"], status=new_status)
        st.rerun()

    # プロジェクト情報
    ic1, ic2, ic3, ic4 = st.columns(4)
    ic1.metric("責任者", project.get("assignee") or "未設定")
    ic2.metric("開始", str(project.get("start_date") or "未設定"))
    ic3.metric("期限", str(project.get("due_date") or "未設定"))
    stats = db.get_project_stats(project["id"])
    total = stats["total"]
    done = stats["completed"]
    pct = (done / total * 100) if total > 0 else 0
    ic4.metric("進捗", f"{done}/{total} ({pct:.0f}%)")

    if total > 0:
        st.progress(pct / 100)

    # プロジェクト編集
    with st.expander("プロジェクト設定を編集"):
        ec1, ec2, ec3 = st.columns(3)
        new_assignee = ec1.selectbox("責任者", [""] + assignee_candidates,
            index=(assignee_candidates.index(project["assignee"]) + 1)
                if project.get("assignee") in assignee_candidates else 0,
            key="proj_edit_assignee")
        e_start = ec2.date_input("開始日",
            value=project["start_date"] if project.get("start_date") else None,
            key="proj_edit_start")
        e_due = ec3.date_input("期限",
            value=project["due_date"] if project.get("due_date") else None,
            key="proj_edit_due")
        e_desc = st.text_area("説明", value=project.get("description") or "", key="proj_edit_desc", height=60)
        ebc1, ebc2 = st.columns([3, 1])
        if ebc1.button("保存", key="proj_edit_save", type="primary"):
            db.update_project(project["id"],
                assignee=new_assignee,
                description=e_desc,
                start_date=e_start.isoformat() if e_start else None,
                due_date=e_due.isoformat() if e_due else None)
            st.success("更新しました")
            st.rerun()
        if ebc2.button("プロジェクト削除", key="proj_del"):
            db.delete_project(project["id"])
            st.rerun()

    st.divider()

    # --- タブ: カンバン / タスク一覧 / ダッシュボード ---
    tab_kanban, tab_list, tab_dash = st.tabs(["カンバンボード", "タスク一覧・編集", "ダッシュボード"])

    with tab_kanban:
        _render_kanban(project, members)

    with tab_list:
        _render_task_list(project, members)

    with tab_dash:
        _render_dashboard(project)


# ===================================================================
# カンバンボード
# ===================================================================
def _render_kanban(project: dict, members: list[str]) -> None:
    # タスク追加（カンバンの上に常時表示）
    with st.expander("＋ タスクを追加", expanded=False):
        _task_add_form(project["id"], members)

    all_tasks = db.list_tasks(project["id"])
    if not all_tasks:
        st.info("タスクがまだありません。上の「＋ タスクを追加」から最初のタスクを作成してください。")
        return

    columns = ["open", "in_progress", "review", "done"]
    col_labels = {
        "open": ("未着手", "#64748b"), "in_progress": ("作業中", "#2563eb"),
        "review": ("レビュー", "#d97706"), "done": ("完了", "#16a34a"),
    }

    cols = st.columns(len(columns))
    for col_ui, status in zip(cols, columns):
        label, color = col_labels[status]
        tasks = [t for t in all_tasks if t["status"] == status]

        with col_ui:
            st.markdown(
                f"<div class='kanban-col-header' style='background:{STATUS_BG[status]};color:{color};'>"
                f"{label}（{len(tasks)}）</div>", unsafe_allow_html=True)

            for t in tasks:
                pri = t.get("priority", "medium")
                cat = t.get("category", "feature")
                assignee = t.get("assignee") or ""
                due = t.get("due_date")
                due_str = f"期限: {due}" if due else ""
                assignee_str = f"👤 {assignee}" if assignee else ""
                meta_parts = [x for x in [assignee_str, due_str] if x]

                st.markdown(f"""
                <div class="kanban-card pri-{pri}">
                    <div class="title">{PRIORITY_ICONS.get(pri,'')} #{t['id']} {t['title']}</div>
                    <div class="meta">
                        <span class="badge badge-{cat}">{db.CATEGORY_LABELS.get(cat, cat)}</span>
                        {'　' + '　|　'.join(meta_parts) if meta_parts else ''}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            # ステータス移動
            if tasks:
                move_task = st.selectbox(
                    "タスクを移動", ["--"] + [f"#{t['id']} {t['title']}" for t in tasks],
                    key=f"kmv_sel_{status}", label_visibility="collapsed")
                if move_task != "--":
                    tid = int(move_task.split(" ")[0].replace("#", ""))
                    next_opts = [s for s in columns if s != status]
                    mc1, mc2 = st.columns(2)
                    dest = mc1.selectbox("→", next_opts,
                        format_func=lambda s: db.STATUS_LABELS.get(s, s),
                        key=f"kmv_dest_{status}")
                    if mc2.button("移動", key=f"kmv_btn_{status}", use_container_width=True):
                        db.update_task(tid, status=dest)
                        st.rerun()


def _task_add_form(project_id: int, members: list[str]) -> None:
    """タスク追加フォーム（カンバン・タスク一覧の両方から使える）。"""
    with st.form(f"add_task_{project_id}"):
        title = st.text_input("タイトル", placeholder="例: ログイン画面のバグ修正")
        c1, c2, c3 = st.columns(3)
        category = c1.selectbox("カテゴリ", db.TASK_CATEGORIES,
                                format_func=lambda c: db.CATEGORY_LABELS[c])
        priority = c2.selectbox("優先度", db.TASK_PRIORITIES,
                                format_func=lambda p: db.PRIORITY_LABELS[p], index=1)
        assignee = c3.selectbox("担当者", [""] + members)
        c4, c5, c6 = st.columns(3)
        start = c4.date_input("開始日", value=None, key=f"tadd_s_{project_id}")
        due = c5.date_input("期限", value=None, key=f"tadd_d_{project_id}")
        estimate = c6.number_input("見積(h)", min_value=0.0, step=0.5, value=0.0)
        desc = st.text_area("詳細", height=80, placeholder="説明・再現手順など")

        if st.form_submit_button("タスクを作成", type="primary", use_container_width=True):
            if not title.strip():
                st.error("タイトルは必須です。")
            else:
                db.add_task(project_id, title.strip(), desc,
                            priority=priority, category=category, assignee=assignee,
                            due_date=due.isoformat() if due else None,
                            estimate_h=estimate or None)
                st.rerun()


# ===================================================================
# タスク一覧・編集
# ===================================================================
def _render_task_list(project: dict, members: list[str]) -> None:
    # フィルタ
    fc1, fc2 = st.columns(2)
    filter_status = fc1.selectbox("ステータス",
        ["すべて"] + db.TASK_STATUSES,
        format_func=lambda s: db.STATUS_LABELS.get(s, s) if s != "すべて" else "すべて",
        key="tlist_filter")
    status_val = None if filter_status == "すべて" else filter_status

    tasks = db.list_tasks(project["id"], status=status_val)

    if not tasks:
        st.info("タスクがありません。「カンバンボード」タブからタスクを作成してください。")
        return

    st.caption(f"{len(tasks)} 件")

    for t in tasks:
        pri = t.get("priority", "medium")
        cat = t.get("category", "feature")
        status = t.get("status", "open")
        icon = PRIORITY_ICONS.get(pri, "")

        with st.expander(
            f"{icon} #{t['id']} {t['title']}　"
            f"[{db.STATUS_LABELS.get(status, status)}]　"
            f"👤 {t.get('assignee') or '未割当'}"
        ):
            # 詳細
            if t.get("description"):
                st.markdown(t["description"])
                st.markdown("---")

            # 編集フォーム
            ec1, ec2, ec3 = st.columns(3)
            new_status = ec1.selectbox("ステータス", db.TASK_STATUSES,
                index=db.TASK_STATUSES.index(status) if status in db.TASK_STATUSES else 0,
                format_func=lambda s: db.STATUS_LABELS.get(s, s),
                key=f"te_st_{t['id']}")
            new_pri = ec2.selectbox("優先度", db.TASK_PRIORITIES,
                index=db.TASK_PRIORITIES.index(pri) if pri in db.TASK_PRIORITIES else 1,
                format_func=lambda p: db.PRIORITY_LABELS.get(p, p),
                key=f"te_pri_{t['id']}")
            new_assignee = ec3.selectbox("担当者", [""] + members,
                index=(members.index(t["assignee"]) + 1) if t.get("assignee") in members else 0,
                key=f"te_a_{t['id']}")

            dc1, dc2, dc3 = st.columns(3)
            new_due = dc1.date_input("期限",
                value=t["due_date"] if t.get("due_date") else None,
                key=f"te_due_{t['id']}")
            new_est = dc2.number_input("見積(h)", min_value=0.0, step=0.5,
                value=float(t.get("estimate_h") or 0), key=f"te_est_{t['id']}")
            new_act = dc3.number_input("実績(h)", min_value=0.0, step=0.5,
                value=float(t.get("actual_h") or 0), key=f"te_act_{t['id']}")

            bc1, bc2 = st.columns([3, 1])
            if bc1.button("更新", key=f"te_save_{t['id']}", type="primary", use_container_width=True):
                db.update_task(t["id"],
                    status=new_status, priority=new_pri, assignee=new_assignee,
                    due_date=new_due.isoformat() if new_due else None,
                    estimate_h=new_est or None, actual_h=new_act or None)
                st.rerun()
            if bc2.button("削除", key=f"te_del_{t['id']}", use_container_width=True):
                db.delete_task(t["id"])
                st.rerun()

            # コメント
            st.markdown("---")
            comments = db.list_comments(t["id"])
            if comments:
                for c in comments:
                    st.markdown(f"> **{c['author']}** ({str(c['created_at'])[:16]}): {c['body']}")
            cc1, cc2, cc3 = st.columns([1, 3, 1])
            c_author = cc1.selectbox("名前", [""] + members, key=f"tc_a_{t['id']}", label_visibility="collapsed")
            c_body = cc2.text_input("コメント", key=f"tc_b_{t['id']}", label_visibility="collapsed",
                                    placeholder="コメントを入力...")
            if cc3.button("投稿", key=f"tc_s_{t['id']}"):
                if c_body.strip():
                    db.add_comment(t["id"], c_author or "匿名", c_body.strip())
                    st.rerun()


# ===================================================================
# ダッシュボード
# ===================================================================
def _render_dashboard(project: dict) -> None:
    stats = db.get_project_stats(project["id"])
    all_tasks = db.list_tasks(project["id"])

    if not all_tasks:
        st.info("タスクがありません。")
        return

    # KPI
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("総タスク", stats["total"])
    c2.metric("完了", stats["completed"])
    c3.metric("作業中", stats["in_progress"])
    c4.metric("未着手", stats["open_count"])
    c5.metric("未解決バグ", stats["open_bugs"])

    st.divider()

    col_a, col_b = st.columns(2)

    with col_a:
        status_data = {}
        for t in all_tasks:
            s = db.STATUS_LABELS.get(t["status"], t["status"])
            status_data[s] = status_data.get(s, 0) + 1
        fig = px.pie(names=list(status_data.keys()), values=list(status_data.values()),
                     title="ステータス分布",
                     color_discrete_sequence=["#94a3b8", "#3b82f6", "#f59e0b", "#22c55e", "#6b7280"])
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        cat_data = {}
        for t in all_tasks:
            c = db.CATEGORY_LABELS.get(t["category"], t["category"])
            cat_data[c] = cat_data.get(c, 0) + 1
        fig = px.bar(x=list(cat_data.keys()), y=list(cat_data.values()),
                     title="カテゴリ別タスク数", color_discrete_sequence=["#3b82f6"])
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10),
                          xaxis_title="", yaxis_title="件数")
        st.plotly_chart(fig, use_container_width=True)

    # 担当者別
    st.subheader("担当者別")
    assignee_data = {}
    for t in all_tasks:
        a = t.get("assignee") or "未割当"
        if a not in assignee_data:
            assignee_data[a] = {"未着手": 0, "作業中": 0, "レビュー": 0, "完了": 0}
        s_label = db.STATUS_LABELS.get(t["status"], "")
        if s_label in assignee_data[a]:
            assignee_data[a][s_label] += 1
    if assignee_data:
        df = pd.DataFrame(assignee_data).T
        df.index.name = "担当者"
        st.dataframe(df, use_container_width=True)

    # 期限切れタスク
    today = date.today()
    overdue = [t for t in all_tasks
               if t.get("due_date") and t["due_date"] < today
               and t["status"] not in ("done", "closed")]
    if overdue:
        st.subheader("期限切れタスク")
        for t in overdue:
            days = (today - t["due_date"]).days
            st.warning(f"#{t['id']} **{t['title']}** — {days}日超過（担当: {t.get('assignee') or '未割当'}）")


# ===================================================================
# エントリーポイント
# ===================================================================
project = _sidebar()

if project:
    main_view(project)
else:
    st.header("開発管理")
    st.info("左のサイドバーからプロジェクトを作成してください。")
    st.markdown("""
    ### 使い方
    1. **サイドバー**の「＋ プロジェクト作成」でプロジェクトを作る
    2. サイドバーでプロジェクトを選択
    3. **カンバンボード**でタスクを追加・ステータスを管理
    4. **タスク一覧・編集**で詳細の編集・担当者の割り当て
    5. **ダッシュボード**で進捗を確認
    """)
