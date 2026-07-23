"""作業日報 自動抽出・勤怠管理システム (Streamlit)

画面構成:
    1. 日報入力・自動抽出   … 日報テキストを貼り付け → 自動抽出 → 確認して登録
    2. 日報一覧表           … 明細/日報単位の一覧・絞り込み・CSV出力・編集
    3. 社員別記録           … 社員ごとの勤怠記録(早朝/通常/残業)とグラフ
    4. 勤怠集計             … 全社員の期間集計(月次など)
    5. 社員マスタ           … 社員の登録・編集
    6. 設定                 … 規定時間の指定・全件再計算
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

import config
import database as db
import extractor
import importer

st.set_page_config(page_title=config.APP_TITLE, page_icon="🗒️", layout="wide")

EDITOR_COLS = ["日付", "現場名", "社員名", "出勤", "退勤", "休憩(分)", "作業内容", "備考"]


# ---------------------------------------------------------------------------
# 共通ヘルパ
# ---------------------------------------------------------------------------
@st.cache_resource
def _bootstrap() -> bool:
    db.init_db()
    return True


def h(minutes) -> float:
    return config.fmt_hours(minutes)


def download_csv(df: pd.DataFrame, filename: str, label: str = "⬇ CSVダウンロード", key=None):
    st.download_button(
        label,
        df.to_csv(index=False).encode("utf-8-sig"),
        file_name=filename,
        mime="text/csv",
        key=key,
    )


def entries_to_df(rows) -> pd.DataFrame:
    """勤怠明細 Row のリスト → 表示用 DataFrame。"""
    data = []
    for r in rows:
        data.append({
            "日付": r["report_date"],
            "曜日": config.weekday_jp(r["report_date"]),
            "社員名": r["employee_name"],
            "社員コード": r["employee_code"] or "",
            "部署": r["department"] or "",
            "現場名": r["site_name"],
            "出勤": r["start_time"],
            "退勤": r["end_time"],
            "休憩(分)": r["break_minutes"],
            "早朝(h)": h(r["early_minutes"]),
            "通常(h)": h(r["normal_minutes"]),
            "残業(h)": h(r["overtime_minutes"]),
            "合計(h)": h(r["total_minutes"]),
            "作業内容": r["work_content"],
            "ステータス": r["status"],
            "日報ID": r["report_id"],
        })
    return pd.DataFrame(data, columns=[
        "日付", "曜日", "社員名", "社員コード", "部署", "現場名", "出勤", "退勤",
        "休憩(分)", "早朝(h)", "通常(h)", "残業(h)", "合計(h)", "作業内容",
        "ステータス", "日報ID",
    ])


def kpi_row(df: pd.DataFrame, extra_label: str = "延べ人日"):
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(extra_label, f"{len(df):,}")
    c2.metric("早朝出勤 合計", f"{df['早朝(h)'].sum():,.2f} h" if len(df) else "0.00 h")
    c3.metric("通常勤務 合計", f"{df['通常(h)'].sum():,.2f} h" if len(df) else "0.00 h")
    c4.metric("残業 合計", f"{df['残業(h)'].sum():,.2f} h" if len(df) else "0.00 h")
    c5.metric("総労働時間", f"{df['合計(h)'].sum():,.2f} h" if len(df) else "0.00 h")


def period_picker(key: str, default_days: int = 30):
    today = date.today()
    value = (today - timedelta(days=default_days), today)
    picked = st.date_input("対象期間", value=value, key=key, format="YYYY/MM/DD")
    if isinstance(picked, (list, tuple)):
        if len(picked) == 2:
            return picked[0].isoformat(), picked[1].isoformat()
        if len(picked) == 1:
            return picked[0].isoformat(), picked[0].isoformat()
        return "", ""
    return picked.isoformat(), picked.isoformat()


def resolve_employee(name: str, settings: dict) -> int | None:
    """氏名から社員 ID を解決。未登録なら設定に応じて自動登録。"""
    name = (name or "").strip()
    if not name:
        return None
    emp = db.get_employee_by_name(name)
    if emp:
        return int(emp["id"])
    if settings.get("auto_register_employee"):
        return db.add_employee(name=name, note="日報から自動登録")
    return None


_bootstrap()
SETTINGS = db.get_settings()


# ---------------------------------------------------------------------------
# サイドバー
# ---------------------------------------------------------------------------
st.sidebar.title("🗒️ " + config.APP_TITLE)
st.sidebar.caption(config.COMPANY_NAME)
PAGE = st.sidebar.radio(
    "メニュー",
    ["📝 日報入力・自動抽出", "📋 日報一覧表", "👤 社員別記録",
     "📊 勤怠集計", "🔄 別アプリ連携", "👥 社員マスタ", "⚙️ 設定"],
    label_visibility="collapsed",
)
st.sidebar.divider()
st.sidebar.markdown(
    f"""**現在の規定時間**
- 始業 `{SETTINGS['standard_start']}` / 終業 `{SETTINGS['standard_end']}`
- 早朝境界 `{SETTINGS['early_boundary']}`
- 所定労働 `{SETTINGS['standard_hours']} h` / 休憩 `{SETTINGS['break_minutes']} 分`
"""
)


# ===========================================================================
# 1. 日報入力・自動抽出
# ===========================================================================
if PAGE == "📝 日報入力・自動抽出":
    st.header("📝 日報入力・自動抽出")
    st.caption("作業日報のテキストを貼り付けると、日付・現場・社員名・出退勤時刻を自動で抽出します。")

    tab_auto, tab_manual = st.tabs(["🤖 テキストから自動抽出", "✍️ 手入力"])

    with tab_auto:
        with st.expander("📎 対応フォーマット例を見る"):
            st.code(
                "2026/07/21(火) 現場: A様邸 新築工事\n"
                "作業内容: 1F配線工事、分電盤取付\n"
                "田中太郎 7:30〜19:00 休憩60分\n"
                "佐藤花子 出勤 8:00 退勤 17:00\n"
                "備考: 材料追加発注あり\n"
                "---\n"
                "7月22日 現場:B工場 改修工事\n"
                "作業員: 田中太郎、鈴木一郎\n"
                "8:00-20:30 休憩1時間",
                language="text",
            )
            st.caption("複数の日報は空行または `---` で区切ってください。日付・時刻の表記ゆれ"
                       "(7時30分 / 07:30 / 令和8年7月21日 など)は自動で吸収します。")

        raw = st.text_area("日報テキスト", height=260, key="raw_text",
                           placeholder="ここに日報を貼り付けてください…")
        c1, c2, _ = st.columns([1, 1, 4])
        if c1.button("🤖 自動抽出", type="primary"):
            blocks = extractor.extract(raw)
            st.session_state["ext_rows"] = extractor.to_rows(blocks)
            st.session_state["ext_warn"] = [w for b in blocks for w in b.get("warnings", [])]
            st.session_state["ext_raw"] = raw
            if not st.session_state["ext_rows"]:
                st.warning("抽出できる勤怠情報が見つかりませんでした。")
        if c2.button("🧹 抽出結果をクリア"):
            for k in ("ext_rows", "ext_warn", "ext_raw"):
                st.session_state.pop(k, None)

        rows = st.session_state.get("ext_rows")
        if rows:
            st.success(f"{len(rows)} 件の勤怠明細を抽出しました。内容を確認・修正して登録してください。")
            for w in st.session_state.get("ext_warn", []):
                st.warning("⚠ " + w)

            base = pd.DataFrame(rows, columns=EDITOR_COLS)
            base["休憩(分)"] = pd.to_numeric(base["休憩(分)"], errors="coerce")
            edited = st.data_editor(
                base,
                num_rows="dynamic",
                width="stretch",
                key="ext_editor",
                column_config={
                    "日付": st.column_config.TextColumn("日付", help="YYYY-MM-DD", width="small"),
                    "出勤": st.column_config.TextColumn("出勤", width="small"),
                    "退勤": st.column_config.TextColumn("退勤", width="small"),
                    "休憩(分)": st.column_config.NumberColumn(
                        "休憩(分)", min_value=0, max_value=600, step=5,
                        help=f"空欄なら既定値 {SETTINGS['break_minutes']} 分を適用"),
                },
            )

            # --- 計算プレビュー ---
            preview = []
            for _, r in edited.iterrows():
                brk = None if pd.isna(r["休憩(分)"]) else int(r["休憩(分)"])
                calc = config.calc_attendance(r["出勤"], r["退勤"], brk, SETTINGS)
                preview.append({
                    "日付": r["日付"], "社員名": r["社員名"], "現場名": r["現場名"],
                    "出勤": r["出勤"], "退勤": r["退勤"], "休憩(分)": calc["break"],
                    "早朝(h)": h(calc["early"]), "通常(h)": h(calc["normal"]),
                    "残業(h)": h(calc["overtime"]), "合計(h)": h(calc["total"]),
                })
            pv = pd.DataFrame(preview)
            st.markdown("##### 勤怠計算プレビュー(現在の規定時間で計算)")
            st.dataframe(pv, width="stretch", hide_index=True)

            merge = st.checkbox("同じ日付・現場の日報が既にある場合は追記する", value=True)
            status = st.selectbox("登録時のステータス", config.REPORT_STATUSES, index=0)

            if st.button("💾 この内容で登録する", type="primary"):
                valid = [r for _, r in edited.iterrows()
                         if str(r["日付"]).strip() and str(r["社員名"]).strip()]
                invalid = len(edited) - len(valid)
                if not valid:
                    st.error("日付と社員名が入力された行がありません。")
                else:
                    groups: dict[tuple, list[dict]] = {}
                    for r in valid:
                        key = (str(r["日付"]).strip(), str(r["現場名"] or "").strip(),
                               str(r["作業内容"] or "").strip(), str(r["備考"] or "").strip())
                        brk = None if pd.isna(r["休憩(分)"]) else int(r["休憩(分)"])
                        groups.setdefault(key, []).append({
                            "employee_id": resolve_employee(r["社員名"], SETTINGS),
                            "employee_name": str(r["社員名"]).strip(),
                            "start_time": str(r["出勤"] or "").strip(),
                            "end_time": str(r["退勤"] or "").strip(),
                            "break_minutes": brk,
                        })
                    created = appended = 0
                    for (d, site, content, note), items in groups.items():
                        rid = db.find_report_id(d, site) if merge else None
                        if rid:
                            existing = [{
                                "employee_id": e["employee_id"],
                                "employee_name": e["employee_name"],
                                "start_time": e["start_time"],
                                "end_time": e["end_time"],
                                "break_minutes": e["break_minutes"],
                                "note": e["note"],
                            } for e in db.get_report_entries(rid)]
                            db.update_report(rid, entries=existing + items, settings=SETTINGS)
                            appended += len(items)
                        else:
                            db.add_report(
                                report_date=d, site_name=site, work_content=content, note=note,
                                status=status, source_text=st.session_state.get("ext_raw", ""),
                                entries=items, settings=SETTINGS,
                            )
                            created += 1
                    db.link_entries_to_employees()
                    msg = f"✅ 日報 {created} 件を新規登録しました。"
                    if appended:
                        msg += f" 既存日報へ {appended} 名分を追記しました。"
                    if invalid:
                        msg += f"(日付/社員名が空の {invalid} 行はスキップ)"
                    st.success(msg)
                    for k in ("ext_rows", "ext_warn", "ext_raw"):
                        st.session_state.pop(k, None)
                    st.rerun()

    with tab_manual:
        employees = db.list_employees(active_only=True)
        names = [e["name"] for e in employees]
        with st.form("manual_form"):
            c1, c2, c3 = st.columns(3)
            m_date = c1.date_input("日付", value=date.today(), format="YYYY/MM/DD")
            m_site = c2.text_input("現場名")
            m_status = c3.selectbox("ステータス", config.REPORT_STATUSES, index=0)
            m_names = st.multiselect("社員(複数選択可)", names)
            m_free = st.text_input("社員名(マスタ未登録の場合はここに入力・カンマ区切り)")
            c4, c5, c6 = st.columns(3)
            m_start = c4.text_input("出勤時刻", value=SETTINGS["standard_start"])
            m_end = c5.text_input("退勤時刻", value=SETTINGS["standard_end"])
            m_break = c6.number_input("休憩(分)", min_value=0, max_value=600,
                                      value=int(SETTINGS["break_minutes"]), step=5)
            m_content = st.text_area("作業内容", height=80)
            m_note = st.text_input("備考")
            submitted = st.form_submit_button("💾 登録", type="primary")

        if submitted:
            targets = list(m_names) + [n.strip() for n in m_free.replace("、", ",").split(",") if n.strip()]
            if not targets:
                st.error("社員を1名以上指定してください。")
            else:
                items = [{
                    "employee_id": resolve_employee(n, SETTINGS),
                    "employee_name": n,
                    "start_time": m_start,
                    "end_time": m_end,
                    "break_minutes": int(m_break),
                } for n in targets]
                d = m_date.isoformat()
                rid = db.find_report_id(d, m_site.strip())
                if rid:
                    existing = [{
                        "employee_id": e["employee_id"], "employee_name": e["employee_name"],
                        "start_time": e["start_time"], "end_time": e["end_time"],
                        "break_minutes": e["break_minutes"], "note": e["note"],
                    } for e in db.get_report_entries(rid)]
                    db.update_report(rid, entries=existing + items, settings=SETTINGS)
                    st.success(f"✅ 既存の日報(ID {rid})に {len(items)} 名分を追記しました。")
                else:
                    rid = db.add_report(report_date=d, site_name=m_site.strip(),
                                        work_content=m_content, note=m_note, status=m_status,
                                        entries=items, settings=SETTINGS)
                    st.success(f"✅ 日報(ID {rid})を登録しました。")


# ===========================================================================
# 2. 日報一覧表
# ===========================================================================
elif PAGE == "📋 日報一覧表":
    st.header("📋 日報一覧表")

    with st.container(border=True):
        c1, c2 = st.columns([2, 3])
        with c1:
            d_from, d_to = period_picker("list_period", 30)
        with c2:
            sites = st.multiselect("現場名", db.list_sites())
            statuses = st.multiselect("ステータス", config.REPORT_STATUSES)
        keyword = st.text_input("キーワード検索(現場名・作業内容・社員名)")

    entry_rows = db.list_entries(d_from, d_to, sites=sites or None,
                                 statuses=statuses or None, keyword=keyword)
    df = entries_to_df(entry_rows)
    kpi_row(df)

    tab1, tab2 = st.tabs(["🧾 明細(社員 × 日)", "📁 日報単位"])

    with tab1:
        if df.empty:
            st.info("該当するデータがありません。")
        else:
            st.dataframe(df, width="stretch", hide_index=True)
            download_csv(df, f"日報明細_{d_from}_{d_to}.csv", key="dl_detail")

    with tab2:
        report_rows = db.list_reports(d_from, d_to, sites=sites or None,
                                      statuses=statuses or None, keyword=keyword)
        rdf = pd.DataFrame([{
            "日報ID": r["id"],
            "日付": r["report_date"],
            "曜日": config.weekday_jp(r["report_date"]),
            "現場名": r["site_name"],
            "人数": r["worker_count"],
            "作業員": r["worker_names"],
            "早朝(h)": h(r["early_minutes"]),
            "通常(h)": h(r["normal_minutes"]),
            "残業(h)": h(r["overtime_minutes"]),
            "合計(h)": h(r["total_minutes"]),
            "作業内容": r["work_content"],
            "備考": r["note"],
            "ステータス": r["status"],
        } for r in report_rows])
        if rdf.empty:
            st.info("該当する日報がありません。")
        else:
            st.dataframe(rdf, width="stretch", hide_index=True)
            download_csv(rdf, f"日報一覧_{d_from}_{d_to}.csv", key="dl_report")

            st.divider()
            st.subheader("✏️ 日報の編集・削除")
            options = {f"ID {r['id']} | {r['report_date']} | {r['site_name'] or '(現場未設定)'}": r["id"]
                       for r in report_rows}
            picked = st.selectbox("編集する日報", list(options.keys()))
            rid = options[picked]
            rep = db.get_report(rid)
            ents = db.get_report_entries(rid)

            with st.form(f"edit_{rid}"):
                c1, c2, c3 = st.columns(3)
                e_date = c1.text_input("日付", value=rep["report_date"])
                e_site = c2.text_input("現場名", value=rep["site_name"])
                e_status = c3.selectbox(
                    "ステータス", config.REPORT_STATUSES,
                    index=config.REPORT_STATUSES.index(rep["status"])
                    if rep["status"] in config.REPORT_STATUSES else 0)
                e_content = st.text_area("作業内容", value=rep["work_content"], height=70)
                e_note = st.text_input("備考", value=rep["note"])
                edf = pd.DataFrame([{
                    "社員名": e["employee_name"], "出勤": e["start_time"],
                    "退勤": e["end_time"], "休憩(分)": e["break_minutes"], "備考": e["note"],
                } for e in ents], columns=["社員名", "出勤", "退勤", "休憩(分)", "備考"])
                e_entries = st.data_editor(edf, num_rows="dynamic", width="stretch",
                                           key=f"ed_{rid}")
                c4, c5 = st.columns(2)
                do_save = c4.form_submit_button("💾 更新", type="primary")
                do_del = c5.form_submit_button("🗑 この日報を削除")

            if do_save:
                items = []
                for _, r in e_entries.iterrows():
                    if not str(r["社員名"] or "").strip():
                        continue
                    brk = None if pd.isna(r["休憩(分)"]) else int(r["休憩(分)"])
                    items.append({
                        "employee_id": resolve_employee(r["社員名"], SETTINGS),
                        "employee_name": str(r["社員名"]).strip(),
                        "start_time": str(r["出勤"] or "").strip(),
                        "end_time": str(r["退勤"] or "").strip(),
                        "break_minutes": brk,
                        "note": str(r["備考"] or ""),
                    })
                db.update_report(rid, report_date=e_date, site_name=e_site,
                                 work_content=e_content, note=e_note, status=e_status,
                                 entries=items, settings=SETTINGS)
                st.success("✅ 更新しました。")
                st.rerun()
            if do_del:
                db.delete_report(rid)
                st.success(f"🗑 日報 ID {rid} を削除しました。")
                st.rerun()

            if rep and rep["source_text"]:
                with st.expander("📄 抽出元のテキストを見る"):
                    st.code(rep["source_text"], language="text")


# ===========================================================================
# 3. 社員別記録
# ===========================================================================
elif PAGE == "👤 社員別記録":
    st.header("👤 社員別の記録・勤怠")

    employees = db.list_employees()
    if not employees:
        st.info("社員が登録されていません。日報を登録するか、社員マスタから追加してください。")
        st.stop()

    c1, c2 = st.columns([2, 3])
    with c1:
        labels = {f"{e['name']}{'（退職/無効）' if not e['active'] else ''}": e["name"]
                  for e in employees}
        picked = st.selectbox("社員", list(labels.keys()))
        emp_name = labels[picked]
    with c2:
        d_from, d_to = period_picker("emp_period", 30)

    rows = db.list_entries(d_from, d_to, employee_names=[emp_name])
    df = entries_to_df(rows)

    st.subheader(f"{emp_name} さんの勤怠サマリ")
    c1, c2, c3, c4, c5 = st.columns(5)
    workdays = df["日付"].nunique() if not df.empty else 0
    c1.metric("出勤日数", f"{workdays} 日")
    c2.metric("早朝出勤時間", f"{df['早朝(h)'].sum() if not df.empty else 0:,.2f} h")
    c3.metric("通常勤務時間", f"{df['通常(h)'].sum() if not df.empty else 0:,.2f} h")
    c4.metric("残業時間", f"{df['残業(h)'].sum() if not df.empty else 0:,.2f} h")
    c5.metric("総労働時間", f"{df['合計(h)'].sum() if not df.empty else 0:,.2f} h")

    if df.empty:
        st.info("この期間の記録はありません。")
    else:
        daily = (df.groupby(["日付", "曜日"], as_index=False)[["早朝(h)", "通常(h)", "残業(h)", "合計(h)"]]
                 .sum().sort_values("日付"))
        long = daily.melt(id_vars="日付", value_vars=["早朝(h)", "通常(h)", "残業(h)"],
                          var_name="区分", value_name="時間")
        fig = px.bar(long, x="日付", y="時間", color="区分", barmode="stack",
                     title="日別の勤務時間内訳",
                     color_discrete_map={"早朝(h)": "#7FB3D5", "通常(h)": "#5D9C59",
                                         "残業(h)": "#E88873"})
        fig.update_layout(height=380, margin=dict(t=50, b=10))
        st.plotly_chart(fig, width="stretch")

        st.markdown("##### 日別記録")
        show = df[["日付", "曜日", "現場名", "出勤", "退勤", "休憩(分)",
                   "早朝(h)", "通常(h)", "残業(h)", "合計(h)", "作業内容", "ステータス"]]
        st.dataframe(show.sort_values("日付"), width="stretch", hide_index=True)
        download_csv(show, f"{emp_name}_勤怠_{d_from}_{d_to}.csv", key="dl_emp")

        st.markdown("##### 現場別の内訳")
        by_site = (df.groupby("現場名", as_index=False)[["早朝(h)", "通常(h)", "残業(h)", "合計(h)"]]
                   .sum().sort_values("合計(h)", ascending=False))
        st.dataframe(by_site, width="stretch", hide_index=True)


# ===========================================================================
# 4. 勤怠集計(全社員)
# ===========================================================================
elif PAGE == "📊 勤怠集計":
    st.header("📊 勤怠集計(全社員)")

    mode = st.radio("集計期間", ["月次", "期間指定"], horizontal=True)
    if mode == "月次":
        today = date.today()
        c1, c2 = st.columns(2)
        year = c1.number_input("年", min_value=2000, max_value=2100, value=today.year, step=1)
        month = c2.number_input("月", min_value=1, max_value=12, value=today.month, step=1)
        first = date(int(year), int(month), 1)
        last = date(int(year) + (int(month) == 12), (int(month) % 12) + 1, 1) - timedelta(days=1)
        d_from, d_to = first.isoformat(), last.isoformat()
        st.caption(f"対象: {d_from} 〜 {d_to}")
    else:
        d_from, d_to = period_picker("agg_period", 30)

    rows = db.list_entries(d_from, d_to)
    df = entries_to_df(rows)
    kpi_row(df)

    if df.empty:
        st.info("該当するデータがありません。")
        st.stop()

    summary = df.groupby("社員名").agg(
        出勤日数=("日付", "nunique"),
        早朝=("早朝(h)", "sum"),
        通常=("通常(h)", "sum"),
        残業=("残業(h)", "sum"),
        合計=("合計(h)", "sum"),
    ).reset_index()
    summary = summary.rename(columns={"早朝": "早朝出勤(h)", "通常": "通常勤務(h)",
                                      "残業": "残業(h)", "合計": "総労働(h)"})
    summary["1日平均(h)"] = (summary["総労働(h)"] / summary["出勤日数"]).round(2)
    for col in ["早朝出勤(h)", "通常勤務(h)", "残業(h)", "総労働(h)"]:
        summary[col] = summary[col].round(2)
    summary = summary.sort_values("総労働(h)", ascending=False)

    st.markdown("##### 社員別集計")
    st.dataframe(summary, width="stretch", hide_index=True)
    download_csv(summary, f"勤怠集計_{d_from}_{d_to}.csv", key="dl_sum")

    long = summary.melt(id_vars="社員名",
                        value_vars=["早朝出勤(h)", "通常勤務(h)", "残業(h)"],
                        var_name="区分", value_name="時間")
    fig = px.bar(long, x="社員名", y="時間", color="区分", barmode="stack",
                 title="社員別 勤務時間の内訳",
                 color_discrete_map={"早朝出勤(h)": "#7FB3D5", "通常勤務(h)": "#5D9C59",
                                     "残業(h)": "#E88873"})
    fig.update_layout(height=420, margin=dict(t=50, b=10))
    st.plotly_chart(fig, width="stretch")

    st.markdown("##### 社員 × 日付(総労働時間 h)")
    pivot = df.pivot_table(index="社員名", columns="日付", values="合計(h)",
                           aggfunc="sum", fill_value=0).round(2)
    st.dataframe(pivot, width="stretch")
    download_csv(pivot.reset_index(), f"勤務表_{d_from}_{d_to}.csv", key="dl_pivot")

    over = summary[summary["残業(h)"] > 0]
    if not over.empty:
        st.markdown("##### 残業時間ランキング")
        st.dataframe(over[["社員名", "残業(h)", "出勤日数"]]
                     .sort_values("残業(h)", ascending=False),
                     width="stretch", hide_index=True)


# ===========================================================================
# 5. 別アプリ連携(sagyo-nippou からの取り込み)
# ===========================================================================
elif PAGE == "🔄 別アプリ連携":
    st.header("🔄 別アプリ連携 — 作業日報システムから取り込み")
    st.caption("別アプリ(sagyo-nippou)は独立したデータベースを使っているため、"
               "ここで取り込むことでこのアプリの一覧・勤怠集計に反映されます。")

    src = st.text_input("取込元 DB のパス", value=str(importer.DEFAULT_SOURCE_DB))

    try:
        info = importer.peek(src)
    except Exception as exc:
        st.error(f"取込元を読み込めませんでした: {exc}")
        st.stop()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("向こうの日報件数", f"{info.get('reports', 0):,}")
    c2.metric("勤怠明細の行数", f"{info.get('workers_rows', 0):,}")
    c3.metric("事務日報", f"{info.get('office_reports', 0):,}")
    c4.metric("取込済み(このアプリ)", f"{importer.imported_count():,}")
    st.caption(f"向こうのデータ期間: {info.get('date_from', '-')} 〜 {info.get('date_to', '-')}")

    st.divider()
    st.subheader("取り込み設定")
    c1, c2 = st.columns([2, 3])
    with c1:
        all_period = st.checkbox("全期間を取り込む", value=True)
        if all_period:
            i_from = i_to = ""
        else:
            i_from, i_to = period_picker("imp_period", 30)
    with c2:
        i_break = st.number_input(
            "控除する休憩時間(分)", min_value=0, max_value=300,
            value=int(SETTINGS["break_minutes"]), step=5,
            help="別アプリは休憩時間を保持していないため、一律でこの値を差し引いて計算します")
        i_office = st.checkbox("事務日報も取り込む", value=True)
        i_workers = st.checkbox("作業員マスタも社員マスタへ取り込む", value=True)

    st.info("💡 同じ日報を何度取り込んでも重複しません(2回目以降は上書き更新)。"
            "取込元の DB には一切書き込みません(読み取り専用)。")

    if st.button("🔄 取り込みを実行", type="primary"):
        with st.spinner("取り込み中…"):
            try:
                res = importer.sync(src, i_from, i_to, break_minutes=int(i_break),
                                    include_office=i_office, with_workers=i_workers,
                                    settings=SETTINGS)
            except Exception as exc:
                st.error(f"取り込みに失敗しました: {exc}")
                res = None
        if res:
            st.success(
                f"✅ 新規 {res['created']} 件 / 更新 {res['updated']} 件 を取り込みました。"
                f"(勤怠明細 {res['entries']} 行、社員 {res['workers_added']} 名を追加)")
            for e in res["errors"]:
                st.warning("⚠ " + e)

    st.divider()
    with st.expander("🗑 取り込んだデータだけを削除する"):
        st.caption("手入力・自動抽出で登録したデータは残ります。取込元の DB には影響しません。")
        if st.button("取込分を削除"):
            n = importer.delete_imported()
            st.success(f"🗑 取込済みの日報 {n} 件を削除しました。")
            st.rerun()

    with st.expander("⏱ 定期的に自動取り込みしたい場合"):
        st.markdown(
            f"""
コマンドラインからも取り込めます。タスクスケジューラに登録すれば自動同期になります。

```powershell
cd {config.BASE_DIR}
py -3 importer.py                        # 全期間
py -3 importer.py 2026-07-01 2026-07-31  # 期間指定
```
"""
        )

    st.subheader("取り込み結果の確認")
    rows = db.list_entries()
    if rows:
        df_all = entries_to_df(rows)
        st.caption(f"このアプリ全体の勤怠明細: {len(df_all):,} 行 "
                   f"/ 現場数 {df_all['現場名'].nunique()} / 社員数 {df_all['社員名'].nunique()}")
        st.dataframe(df_all.head(50), width="stretch", hide_index=True)
    else:
        st.info("まだデータがありません。")


# ===========================================================================
# 6. 社員マスタ
# ===========================================================================
elif PAGE == "👥 社員マスタ":
    st.header("👥 社員マスタ")

    with st.expander("➕ 社員を追加", expanded=False):
        with st.form("add_emp"):
            c1, c2, c3 = st.columns(3)
            n_code = c1.text_input("社員コード")
            n_name = c2.text_input("氏名 *")
            n_kana = c3.text_input("フリガナ")
            c4, c5, c6 = st.columns(3)
            n_dept = c4.selectbox("部署", [""] + config.DEPARTMENTS)
            n_pos = c5.selectbox("役職", [""] + config.POSITIONS)
            n_active = c6.checkbox("在籍中", value=True)
            n_note = st.text_input("備考")
            if st.form_submit_button("追加", type="primary"):
                if not n_name.strip():
                    st.error("氏名は必須です。")
                else:
                    db.add_employee(name=n_name.strip(), code=n_code, kana=n_kana,
                                    department=n_dept, position=n_pos,
                                    active=int(n_active), note=n_note)
                    db.link_entries_to_employees()
                    st.success(f"✅ {n_name} を追加しました。")
                    st.rerun()

    employees = db.list_employees()
    if not employees:
        st.info("社員が登録されていません。")
        st.stop()

    edf = pd.DataFrame([{
        "ID": e["id"], "社員コード": e["code"] or "", "氏名": e["name"],
        "フリガナ": e["kana"] or "", "部署": e["department"] or "",
        "役職": e["position"] or "", "在籍": bool(e["active"]), "備考": e["note"] or "",
    } for e in employees])

    edited = st.data_editor(
        edf, width="stretch", hide_index=True, key="emp_editor",
        disabled=["ID"],
        column_config={"在籍": st.column_config.CheckboxColumn("在籍")},
    )
    c1, c2 = st.columns([1, 3])
    if c1.button("💾 変更を保存", type="primary"):
        for _, r in edited.iterrows():
            db.update_employee(int(r["ID"]), code=r["社員コード"], name=str(r["氏名"]).strip(),
                               kana=r["フリガナ"], department=r["部署"], position=r["役職"],
                               active=int(bool(r["在籍"])), note=r["備考"])
        linked = db.link_entries_to_employees()
        st.success(f"✅ 保存しました。(勤怠明細 {linked} 件を社員に紐付け)")
        st.rerun()

    st.divider()
    st.subheader("🗑 社員の削除")
    del_map = {f"ID {e['id']} | {e['name']}": e["id"] for e in employees}
    target = st.selectbox("削除する社員", list(del_map.keys()))
    st.caption("削除しても登録済みの日報・勤怠記録(氏名)は残ります。")
    if st.button("削除する"):
        db.delete_employee(del_map[target])
        st.success("🗑 削除しました。")
        st.rerun()


# ===========================================================================
# 7. 設定
# ===========================================================================
elif PAGE == "⚙️ 設定":
    st.header("⚙️ 設定 — 規定時間の指定")
    st.caption("ここで指定した規定時間をもとに、早朝出勤・通常勤務・残業を自動判定します。")

    with st.form("settings_form"):
        c1, c2, c3 = st.columns(3)
        s_start = c1.text_input(config.SETTING_LABELS["standard_start"],
                                value=str(SETTINGS["standard_start"]))
        s_end = c2.text_input(config.SETTING_LABELS["standard_end"],
                              value=str(SETTINGS["standard_end"]))
        s_early = c3.text_input(config.SETTING_LABELS["early_boundary"],
                                value=str(SETTINGS["early_boundary"]),
                                help="この時刻より前の実働を『早朝出勤時間』として集計します")
        c4, c5, c6 = st.columns(3)
        s_hours = c4.number_input(config.SETTING_LABELS["standard_hours"],
                                  min_value=1.0, max_value=16.0,
                                  value=float(SETTINGS["standard_hours"]), step=0.5)
        s_break = c5.number_input(config.SETTING_LABELS["break_minutes"],
                                  min_value=0, max_value=300,
                                  value=int(SETTINGS["break_minutes"]), step=5)
        s_round = c6.selectbox(config.SETTING_LABELS["round_minutes"], [0, 5, 10, 15, 30],
                               index=[0, 5, 10, 15, 30].index(int(SETTINGS["round_minutes"]))
                               if int(SETTINGS["round_minutes"]) in [0, 5, 10, 15, 30] else 0,
                               help="0 は丸めなし。始業は繰り上げ・終業は切り捨てで丸めます")
        mode_keys = list(config.OVERTIME_MODES.keys())
        s_mode = st.radio(
            config.SETTING_LABELS["overtime_mode"], mode_keys,
            index=mode_keys.index(str(SETTINGS["overtime_mode"]))
            if str(SETTINGS["overtime_mode"]) in mode_keys else 0,
            format_func=lambda k: config.OVERTIME_MODES[k], horizontal=True)
        s_auto = st.checkbox(config.SETTING_LABELS["auto_register_employee"],
                             value=bool(SETTINGS["auto_register_employee"]),
                             help="日報に出てきた未登録の氏名を社員マスタへ自動追加します")
        saved = st.form_submit_button("💾 設定を保存", type="primary")

    if saved:
        errors = [label for label, v in [("規定始業時刻", s_start), ("規定終業時刻", s_end),
                                         ("早朝出勤の境界時刻", s_early)]
                  if config.parse_hhmm(v) is None]
        if errors:
            st.error("時刻の形式が不正です(HH:MM で入力してください): " + " / ".join(errors))
        else:
            db.save_settings({
                "standard_start": config.fmt_hhmm(config.parse_hhmm(s_start)),
                "standard_end": config.fmt_hhmm(config.parse_hhmm(s_end)),
                "early_boundary": config.fmt_hhmm(config.parse_hhmm(s_early)),
                "standard_hours": s_hours,
                "break_minutes": int(s_break),
                "round_minutes": int(s_round),
                "overtime_mode": s_mode,
                "auto_register_employee": int(bool(s_auto)),
            })
            st.success("✅ 設定を保存しました。既存データにも反映するには下の再計算を実行してください。")
            st.rerun()

    st.divider()
    st.subheader("🔄 登録済みデータの再計算")
    st.caption("規定時間を変更した後にこれを実行すると、過去の日報の早朝/通常/残業が新しい規定で計算し直されます。")
    if st.button("🔄 全件を再計算する"):
        n = db.recalculate_all(db.get_settings())
        st.success(f"✅ {n} 件の勤怠明細を再計算しました。")

    st.divider()
    st.subheader("🔗 メンテナンス")
    if st.button("勤怠明細を社員マスタに紐付け直す"):
        n = db.link_entries_to_employees()
        st.success(f"✅ {n} 件を紐付けました。")

    with st.expander("📐 判定ロジックの説明"):
        st.markdown(
            f"""
- **早朝出勤時間**: 早朝境界時刻(`{SETTINGS['early_boundary']}`)より前の実働時間
- **通常勤務時間**: 早朝境界〜規定終業時刻(`{SETTINGS['standard_end']}`)の実働。
  所定労働時間(`{SETTINGS['standard_hours']} h`)を上限とし、超過分は残業へ
- **残業時間**: 規定終業時刻以降の実働 + 通常帯の所定超過分
- **休憩**: 通常帯 → 残業帯 → 早朝帯 の順に控除
- **日跨ぎ勤務**(例 22:00→06:00)にも対応
"""
        )
