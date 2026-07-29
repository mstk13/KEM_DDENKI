"""工期管理システム — Streamlit メインアプリ。

現場ごとの工期・進捗をガントチャートで視覚化し、
工程フェーズ・マイルストーン・日報実績・材料費を一元管理する。

ページ構成:
  1. 全現場ガントチャート（鳥瞰）
  2. 現場別 詳細（工程 / 日報 / 材料費）
  3. 進捗サマリー
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import database as db

st.set_page_config(page_title="工期管理 | ケンモチ電機", page_icon="📅", layout="wide")

db.init_db()

SITE_STATUSES = ["着工前", "施工中", "完了", "中断"]
CATEGORIES = ["電気工事", "電気設備", "照明設備", "受変電設備", "配線工事", "通信・弱電", "点検・保守", "その他"]
PHASE_COLORS = [
    "#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6",
    "#06b6d4", "#ec4899", "#14b8a6", "#f97316", "#6366f1",
]


def _to_date(val) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val))
    except (ValueError, TypeError):
        return None


# ===================================================================
# 1. 全現場ガントチャート
# ===================================================================
def page_gantt_all() -> None:
    st.header("📅 全現場 工期ガントチャート")

    # --- 現場を新規登録 ---
    with st.expander("➕ 工事（現場）を新規登録", expanded=False):
        with st.form("add_site_form"):
            s_name = st.text_input("現場名（工事名）*", placeholder="例: 〇〇基地 電気設備改修工事")
            ac1, ac2, ac3 = st.columns(3)
            s_client = ac1.text_input("発注先", placeholder="例: 防衛省")
            s_category = ac2.selectbox("工事種別", ["（未指定）"] + CATEGORIES)
            s_manager = ac3.text_input("現場代理人")
            ac4, ac5, ac6 = st.columns(3)
            s_start = ac4.date_input("工期開始", value=None)
            s_end = ac5.date_input("工期終了", value=None)
            s_status = ac6.selectbox("状態", SITE_STATUSES, index=1)
            s_address = st.text_input("住所", "")
            s_memo = st.text_area("メモ", "", height=68)
            if st.form_submit_button("登録", type="primary"):
                if not s_name:
                    st.error("現場名は必須です。")
                else:
                    new_id = db.add_site(
                        name=s_name,
                        client=s_client,
                        category="" if s_category == "（未指定）" else s_category,
                        start_date=s_start.isoformat() if s_start else None,
                        end_date=s_end.isoformat() if s_end else None,
                        status=s_status,
                        address=s_address,
                        manager=s_manager,
                        memo=s_memo,
                    )
                    st.success(f"現場「{s_name}」を登録しました（ID: {new_id}）")
                    st.rerun()

    st.divider()

    c1, c2 = st.columns([2, 1])
    keyword = c1.text_input("現場名で検索", "", key="gantt_kw")
    show_completed = c2.checkbox("完了した現場も表示", value=False)

    sites = db.list_sites(active_only=not show_completed, keyword=keyword)
    if not sites:
        st.info("現場が登録されていません。上の「工事を新規登録」から追加してください。")
        return

    # ガントチャート用データ構築
    gantt_rows = []
    today = date.today()

    for s in sites:
        start = _to_date(s.get("start_date"))
        end = _to_date(s.get("end_date"))
        if not start:
            continue

        end = end or (start + timedelta(days=30))

        gantt_rows.append({
            "Task": s["name"],
            "Start": start,
            "Finish": end,
            "Resource": s.get("status", "施工中"),
            "Type": "現場",
        })

        phases = db.list_phases(s["id"])
        for p in phases:
            p_start = _to_date(p.get("start_date"))
            p_end = _to_date(p.get("end_date"))
            if p_start and p_end:
                gantt_rows.append({
                    "Task": f"  {p['name']}",
                    "Start": p_start,
                    "Finish": p_end,
                    "Resource": f"{p.get('progress', 0)}%",
                    "Type": "工程",
                })

    if not gantt_rows:
        st.warning("工期（開始日・終了日）が設定されている現場がありません。現場を選択して工期を入力してください。")
        return

    df = pd.DataFrame(gantt_rows)

    color_map = {"着工前": "#94a3b8", "施工中": "#3b82f6", "完了": "#22c55e", "中断": "#ef4444"}
    for r in df["Resource"].unique():
        if r not in color_map:
            if "%" in str(r):
                pct = int(str(r).replace("%", ""))
                color_map[r] = "#22c55e" if pct >= 100 else ("#f59e0b" if pct >= 50 else "#94a3b8")
            else:
                color_map[r] = "#6366f1"

    fig = px.timeline(df, x_start="Start", x_end="Finish", y="Task", color="Resource",
                      color_discrete_map=color_map, title="")
    fig.update_yaxes(autorange="reversed", title="")
    fig.update_xaxes(title="")
    fig.add_vline(x=datetime.combine(today, datetime.min.time()), line_dash="dash", line_color="red",
                  annotation_text="今日", annotation_position="top")
    fig.update_layout(
        height=max(400, len(gantt_rows) * 35 + 100),
        margin=dict(l=10, r=10, t=30, b=30),
        legend_title_text="ステータス / 進捗", showlegend=True,
    )
    st.plotly_chart(fig, use_container_width=True)

    # 月別カレンダービュー
    st.subheader("月別カレンダービュー")
    _month_selector_view(sites)


def _month_selector_view(sites: list[dict]) -> None:
    today = date.today()
    months = sorted({(today.replace(day=1) + timedelta(days=32 * d)).replace(day=1) for d in range(-2, 7)})

    selected_month = st.selectbox(
        "表示月", months,
        index=months.index(today.replace(day=1)) if today.replace(day=1) in months else 2,
        format_func=lambda m: f"{m.year}年{m.month}月", key="month_sel",
    )

    month_start = selected_month
    month_end = (selected_month.replace(month=selected_month.month % 12 + 1,
                 year=selected_month.year + (1 if selected_month.month == 12 else 0))
                 - timedelta(days=1))

    overlapping = []
    for s in sites:
        sd = _to_date(s.get("start_date"))
        if not sd:
            continue
        ed = _to_date(s.get("end_date")) or (sd + timedelta(days=30))
        if sd <= month_end and ed >= month_start:
            overlapping.append({
                "現場名": s["name"], "状態": s.get("status", ""),
                "工期開始": str(sd), "工期終了": str(ed),
                "発注先": s.get("client", ""), "種別": s.get("category", ""),
            })

    if overlapping:
        st.caption(f"{selected_month.year}年{selected_month.month}月に工期がかかる現場: {len(overlapping)} 件")
        st.dataframe(pd.DataFrame(overlapping), use_container_width=True, hide_index=True)
    else:
        st.info(f"{selected_month.year}年{selected_month.month}月に工期がかかる現場はありません。")


# ===================================================================
# 2. 現場別 詳細工程管理
# ===================================================================
def page_site_detail() -> None:
    st.header("🏗 現場別 詳細管理")

    sites = db.list_sites()
    if not sites:
        st.info("現場が登録されていません。「全現場ガントチャート」ページから登録してください。")
        return

    site_id = st.selectbox(
        "現場を選択", [s["id"] for s in sites],
        format_func=lambda i: next(
            (f"{s['name']} [{s.get('status','')}]" for s in sites if s["id"] == i), str(i)),
        key="site_sel",
    )

    site = db.get_site(site_id)
    if not site:
        return

    # --- 基本情報 KPI ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("状態", site.get("status", "—"))
    c2.metric("発注先", site.get("client") or "—")
    c3.metric("工期開始", str(site.get("start_date") or "未設定"))
    c4.metric("工期終了", str(site.get("end_date") or "未設定"))

    # 実績 + 材料費 KPI
    work_summary = db.get_site_work_summary(site_id)
    mat_summary = db.get_site_material_summary(site_id)
    est_summary = db.get_site_estimate_summary(site_id)

    kc1, kc2, kc3, kc4 = st.columns(4)
    kc1.metric("作業日数", f"{work_summary['work_days']} 日")
    kc2.metric("総作業時間", f"{float(work_summary['total_hours']):.1f} h")
    kc3.metric("材料発注額", f"¥{mat_summary['total_amount']:,}")
    if est_summary:
        kc4.metric("見積額", f"¥{est_summary.get('total_amount', 0):,}")
    else:
        kc4.metric("見積額", "—")

    # --- 工期編集 ---
    with st.expander("工期・基本情報を編集"):
        with st.form("site_edit_form"):
            ec1, ec2, ec3 = st.columns(3)
            e_start = ec1.date_input("工期開始", value=_to_date(site.get("start_date")))
            e_end = ec2.date_input("工期終了", value=_to_date(site.get("end_date")))
            e_status = ec3.selectbox("状態", SITE_STATUSES,
                index=SITE_STATUSES.index(site["status"]) if site.get("status") in SITE_STATUSES else 0)
            ec4, ec5 = st.columns(2)
            e_client = ec4.text_input("発注先", value=site.get("client") or "")
            e_manager = ec5.text_input("現場代理人", value=site.get("manager") or "")
            e_category = st.selectbox("工事種別", ["（未指定）"] + CATEGORIES,
                index=(CATEGORIES.index(site["category"]) + 1) if site.get("category") in CATEGORIES else 0)
            if st.form_submit_button("保存"):
                db.update_site(site_id,
                    start_date=e_start.isoformat() if e_start else None,
                    end_date=e_end.isoformat() if e_end else None,
                    status=e_status, client=e_client, manager=e_manager,
                    category="" if e_category == "（未指定）" else e_category)
                st.success("工期情報を更新しました。")
                st.rerun()

    st.divider()

    # --- タブで工程 / 日報 / 材料費 を切り替え ---
    tab_phase, tab_nippou, tab_material = st.tabs(["📐 工程フェーズ", "📝 日報データ", "📦 材料費"])

    with tab_phase:
        _render_phases(site_id, site)

    with tab_nippou:
        _render_nippou(site_id)

    with tab_material:
        _render_materials(site_id)


# --- 工程フェーズ ---
def _render_phases(site_id: int, site: dict) -> None:
    phases = db.list_phases(site_id)

    with st.expander("工程を追加"):
        with st.form("add_phase_form"):
            pc1, pc2 = st.columns(2)
            p_name = pc1.text_input("工程名", placeholder="例: 仮設電気、幹線引替、照明LED化")
            p_color_idx = pc2.selectbox("色", range(len(PHASE_COLORS)),
                format_func=lambda i: f"色{i+1}")
            pc3, pc4 = st.columns(2)
            p_start = pc3.date_input("開始日", value=None, key="ph_start")
            p_end = pc4.date_input("終了日", value=None, key="ph_end")
            pc5, pc6 = st.columns(2)
            p_progress = pc5.slider("進捗率", 0, 100, 0, 5)
            p_memo = pc6.text_input("メモ", "")
            if st.form_submit_button("工程を追加"):
                if not p_name:
                    st.error("工程名は必須です。")
                else:
                    db.add_phase(site_id, p_name,
                        start_date=p_start.isoformat() if p_start else None,
                        end_date=p_end.isoformat() if p_end else None,
                        progress=p_progress, sort_order=len(phases),
                        color=PHASE_COLORS[p_color_idx % len(PHASE_COLORS)], memo=p_memo)
                    st.success(f"工程「{p_name}」を追加しました。")
                    st.rerun()

    if phases:
        for p in phases:
            col_bar, col_edit = st.columns([5, 1])
            pct = p.get("progress", 0)
            color = p.get("color") or "#3b82f6"
            col_bar.markdown(
                f"**{p['name']}** — {str(p.get('start_date','?'))} ~ {str(p.get('end_date','?'))} "
                f"<span style='background:{color};color:#fff;padding:2px 8px;border-radius:4px;'>"
                f"{pct}%</span>", unsafe_allow_html=True)
            col_bar.progress(pct / 100)

            with col_edit.popover("編集"):
                new_pct = st.slider("進捗率", 0, 100, pct, 5, key=f"pct_{p['id']}")
                if st.button("更新", key=f"upd_{p['id']}"):
                    db.update_phase(p["id"], progress=new_pct)
                    st.rerun()
                if st.button("削除", key=f"del_{p['id']}"):
                    db.delete_phase(p["id"])
                    st.rerun()

        _site_gantt(site, phases)
    else:
        st.caption("工程が未登録です。上の「工程を追加」から登録してください。")

    st.divider()

    # マイルストーン
    st.subheader("マイルストーン")
    milestones = db.list_milestones(site_id)

    with st.expander("マイルストーンを追加"):
        with st.form("add_ms_form"):
            mc1, mc2, mc3 = st.columns(3)
            ms_name = mc1.text_input("名称", placeholder="例: 中間検査、完了検査")
            ms_date = mc2.date_input("予定日", value=None, key="ms_date")
            ms_memo = mc3.text_input("メモ", "")
            if st.form_submit_button("追加"):
                if ms_name and ms_date:
                    db.add_milestone(site_id, ms_name, ms_date.isoformat(), ms_memo)
                    st.success(f"マイルストーン「{ms_name}」を追加しました。")
                    st.rerun()
                else:
                    st.error("名称と予定日は必須です。")

    if milestones:
        today = date.today()
        for ms in milestones:
            td_d = _to_date(ms["target_date"])
            if not td_d:
                continue
            days_left = (td_d - today).days
            done = ms.get("completed", False)
            icon = "✅" if done else ("🔴" if days_left < 0 else ("🟡" if days_left <= 7 else "⚪"))
            status_text = "完了" if done else (f"あと{days_left}日" if days_left >= 0 else f"{-days_left}日超過")
            mc1, mc2, mc3 = st.columns([3, 2, 1])
            mc1.write(f"{icon} **{ms['name']}** — {td_d} ({status_text})")
            mc2.write(ms.get("memo", ""))
            if not done:
                if mc3.button("完了", key=f"ms_done_{ms['id']}"):
                    db.update_milestone(ms["id"], completed=True)
                    st.rerun()
            else:
                if mc3.button("戻す", key=f"ms_undo_{ms['id']}"):
                    db.update_milestone(ms["id"], completed=False)
                    st.rerun()


# --- 日報データ ---
def _render_nippou(site_id: int) -> None:
    st.subheader("📝 この現場の日報データ")

    reports = db.list_site_reports(site_id)
    if not reports:
        st.info("この現場に紐づく日報はまだありません。作業日報アプリで日報を登録すると自動的にここに表示されます。")
        return

    st.caption(f"{len(reports)} 件の日報")

    # 日別作業時間チャート
    daily = db.get_daily_hours(site_id)
    if daily:
        df_daily = pd.DataFrame(daily)
        df_daily["report_date"] = pd.to_datetime(df_daily["report_date"])

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_daily["report_date"], y=df_daily["hours"],
            name="作業時間(h)", marker_color="#3b82f6",
        ))
        fig.add_trace(go.Scatter(
            x=df_daily["report_date"], y=df_daily["workers"],
            name="作業員数", yaxis="y2", mode="lines+markers",
            marker_color="#f59e0b", line=dict(width=2),
        ))
        fig.update_layout(
            title="日別 作業時間 / 作業員数",
            yaxis=dict(title="作業時間(h)"),
            yaxis2=dict(title="作業員数", overlaying="y", side="right"),
            height=350, margin=dict(l=10, r=10, t=40, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig, use_container_width=True)

    # 日報テーブル
    rows = []
    for r in reports:
        rows.append({
            "日付": str(r["report_date"]),
            "作業員": r.get("worker_names", ""),
            "人数": r["worker_count"],
            "時間(h)": f"{float(r['total_hours']):.1f}",
            "残業(h)": f"{float(r['overtime_hours']):.1f}",
            "協力会社": r["sub_headcount"],
            "作業内容": (r.get("work_content") or "")[:60],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# --- 材料費 ---
def _render_materials(site_id: int) -> None:
    st.subheader("📦 この現場の材料費")

    mat_summary = db.get_site_material_summary(site_id)
    est_summary = db.get_site_estimate_summary(site_id)
    orders = db.list_site_orders(site_id)

    # KPI
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("発注件数", f"{mat_summary['order_count']} 件")
    mc2.metric("発注合計", f"¥{mat_summary['total_amount']:,}")
    mc3.metric("付帯コスト（輸送費等）", f"¥{mat_summary['overhead']:,}")

    if est_summary:
        total_ordered = mat_summary["total_amount"] + mat_summary["overhead"]
        est_total = est_summary.get("total_amount", 0) or 0
        if est_total > 0:
            consumption_rate = total_ordered / est_total * 100
            st.progress(min(consumption_rate / 100, 1.0),
                        text=f"材料費消化率: ¥{total_ordered:,} / ¥{est_total:,} ({consumption_rate:.1f}%)")

    if not orders:
        st.info("この現場に紐づく発注はまだありません。材料管理アプリで発注を登録すると自動的にここに表示されます。")
        return

    # 日別材料費チャート
    daily_mat = db.get_daily_material_cost(site_id)
    if daily_mat:
        df_mat = pd.DataFrame(daily_mat)
        df_mat["order_date"] = pd.to_datetime(df_mat["order_date"])

        fig = px.bar(df_mat, x="order_date", y="daily_amount",
                     title="日別 材料発注金額", labels={"daily_amount": "金額(円)", "order_date": ""},
                     color_discrete_sequence=["#22c55e"])
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

    # 発注テーブル
    rows = []
    for o in orders:
        rows.append({
            "発注日": str(o["order_date"]),
            "品目": o["item_name"],
            "仕様": o.get("spec") or "",
            "数量": o["quantity"],
            "単位": o["unit"],
            "単価": f"¥{o['unit_price']:,}",
            "金額": f"¥{o['amount']:,}",
            "仕入先": o.get("supplier_name", ""),
            "付帯": f"¥{o['overhead']:,}" if o["overhead"] else "",
            "状態": o["status"],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _site_gantt(site: dict, phases: list[dict]) -> None:
    rows = []
    for p in phases:
        p_start = _to_date(p.get("start_date"))
        p_end = _to_date(p.get("end_date"))
        if not p_start or not p_end:
            continue
        rows.append({
            "工程": p["name"], "Start": p_start, "Finish": p_end,
            "進捗": f"{p.get('progress', 0)}%",
            "color": p.get("color") or "#3b82f6",
        })

    if not rows:
        return

    df = pd.DataFrame(rows)
    color_map = {r["進捗"]: r["color"] for r in rows}

    fig = px.timeline(df, x_start="Start", x_end="Finish", y="工程", color="進捗",
                      color_discrete_map=color_map)
    fig.update_yaxes(autorange="reversed", title="")
    fig.update_xaxes(title="")
    fig.add_vline(x=datetime.combine(date.today(), datetime.min.time()), line_dash="dash", line_color="red",
                  annotation_text="今日")
    fig.update_layout(
        height=max(250, len(rows) * 40 + 80),
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=True, legend_title_text="進捗率",
    )

    milestones = db.list_milestones(site["id"])
    for ms in milestones:
        td_d = _to_date(ms["target_date"])
        if not td_d:
            continue
        td_dt = datetime.combine(td_d, datetime.min.time())
        fig.add_vline(x=td_dt, line_dash="dot", line_color="#f59e0b", line_width=1)
        fig.add_annotation(x=td_dt, y=0, text=f"◆{ms['name']}", showarrow=False,
                           yshift=15, font=dict(size=10, color="#f59e0b"))

    st.plotly_chart(fig, use_container_width=True)


# ===================================================================
# 3. 進捗サマリー
# ===================================================================
def page_summary() -> None:
    st.header("📊 進捗サマリー")

    sites = db.list_sites()
    if not sites:
        st.info("現場が登録されていません。")
        return

    today = date.today()

    status_counts = {}
    for s in sites:
        st_name = s.get("status", "不明")
        status_counts[st_name] = status_counts.get(st_name, 0) + 1

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("全現場数", len(sites))
    c2.metric("施工中", status_counts.get("施工中", 0))
    c3.metric("着工前", status_counts.get("着工前", 0))
    c4.metric("完了", status_counts.get("完了", 0))

    st.divider()

    # 遅延警告
    st.subheader("遅延・注意が必要な現場")
    alerts = []
    for s in sites:
        if s.get("status") in ("完了", "中断"):
            continue
        ed_d = _to_date(s.get("end_date"))
        if not ed_d:
            continue
        days_left = (ed_d - today).days
        if days_left <= 14:
            phases = db.list_phases(s["id"])
            avg_progress = (sum(p.get("progress", 0) for p in phases) / len(phases)) if phases else 0
            alerts.append({
                "現場名": s["name"], "工期終了": str(ed_d), "残日数": days_left,
                "平均進捗": f"{avg_progress:.0f}%",
                "状態": "超過" if days_left < 0 else "要注意",
            })

    if alerts:
        alerts.sort(key=lambda x: x["残日数"])
        st.dataframe(pd.DataFrame(alerts), use_container_width=True, hide_index=True)
    else:
        st.success("工期が2週間以内に迫っている現場はありません。")

    st.divider()

    # 現場別進捗一覧（材料費も含む）
    st.subheader("現場別 進捗・コスト一覧")
    progress_rows = []
    for s in sites:
        phases = db.list_phases(s["id"])
        avg_progress = (sum(p.get("progress", 0) for p in phases) / len(phases)) if phases else 0
        work = db.get_site_work_summary(s["id"])
        mat = db.get_site_material_summary(s["id"])

        sd = s.get("start_date")
        ed = s.get("end_date")
        progress_rows.append({
            "現場名": s["name"],
            "状態": s.get("status", ""),
            "工期": f"{str(sd or '?')} ~ {str(ed or '?')}",
            "工程数": len(phases),
            "平均進捗": f"{avg_progress:.0f}%",
            "作業日数": work["work_days"],
            "総時間(h)": f"{float(work['total_hours']):.1f}",
            "材料費": f"¥{mat['total_amount']:,}",
        })

    if progress_rows:
        st.dataframe(pd.DataFrame(progress_rows), use_container_width=True, hide_index=True)

    if status_counts:
        fig = px.pie(
            names=list(status_counts.keys()), values=list(status_counts.values()),
            title="現場ステータス分布",
            color=list(status_counts.keys()),
            color_discrete_map={"着工前": "#94a3b8", "施工中": "#3b82f6", "完了": "#22c55e", "中断": "#ef4444"},
        )
        fig.update_layout(height=350)
        st.plotly_chart(fig, use_container_width=True)


# ===================================================================
# ルーティング
# ===================================================================
PAGES = {
    "全現場ガントチャート": page_gantt_all,
    "現場別 詳細管理": page_site_detail,
    "進捗サマリー": page_summary,
}

st.sidebar.title("📅 工期管理")
st.sidebar.caption("株式会社ケンモチ電機")

default = st.session_state.get("page", "全現場ガントチャート")
choice = st.sidebar.radio(
    "メニュー", list(PAGES.keys()),
    index=list(PAGES.keys()).index(default) if default in PAGES else 0,
)
st.session_state["page"] = choice
PAGES[choice]()
