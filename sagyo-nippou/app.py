"""作業日報管理システム — Streamlit メインアプリ。

株式会社ケンモチ電機向け。紙の「作業日報」フォーム（1現場×1日で複数作業員＋協力会社を
1枚にまとめる形式）に準拠。項目: 現場名 / 発注先 / 年月日 / 曜日 / 作業員名 /
作業時間 / 残業 / 宿泊 / 作業内容・使用材料 / 交通手段・交通費 / 協力会社 / 現場代理人。

起動:
    streamlit run app.py
"""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

import config
import database as db

st.set_page_config(page_title="作業日報管理", page_icon="🛠️", layout="wide")
db.init_db()


# --------------------------------------------------------------------------
# 変換ヘルパー
# --------------------------------------------------------------------------
def _t(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def _time_to_str(v) -> str | None:
    """data_editor のセル値（time/str/NaT）→ 'HH:MM'。"""
    try:
        if v is None or pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, str):
        return v[:5] or None
    try:
        return v.strftime("%H:%M")
    except Exception:
        return None


def _str_to_time(s: str | None) -> dtime | None:
    if not s:
        return None
    try:
        return _t(s)
    except (ValueError, AttributeError):
        return None


def _num(v, cast=float, default=0):
    try:
        if v is None or pd.isna(v):
            return default
    except (TypeError, ValueError):
        pass
    try:
        return cast(v)
    except (TypeError, ValueError):
        return default


def _txt(v) -> str:
    try:
        if v is None or pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v).strip()


# --------------------------------------------------------------------------
# 明細エディタの列定義
# --------------------------------------------------------------------------
def _worker_col_config(worker_names: list[str]):
    name_col = (
        st.column_config.SelectboxColumn("作業員名", options=worker_names, width="medium")
        if worker_names
        else st.column_config.TextColumn("作業員名", width="medium")
    )
    return {
        "作業員名": name_col,
        "開始": st.column_config.TimeColumn("開始", format="HH:mm"),
        "終了": st.column_config.TimeColumn("終了", format="HH:mm"),
        "残業(h)": st.column_config.NumberColumn("残業(h)", min_value=0.0, step=0.5, format="%.1f"),
        "宿泊": st.column_config.CheckboxColumn("宿泊"),
    }


_SUB_COL_CONFIG = {
    "会社名": st.column_config.TextColumn("会社名", width="medium"),
    "作業員名": st.column_config.TextColumn("作業員名", width="medium"),
    "人数": st.column_config.NumberColumn("人数", min_value=0, step=1),
    "開始": st.column_config.TimeColumn("開始", format="HH:mm"),
    "終了": st.column_config.TimeColumn("終了", format="HH:mm"),
    "作業内容": st.column_config.TextColumn("作業内容", width="large"),
    "車": st.column_config.CheckboxColumn("車"),
    "乗合": st.column_config.CheckboxColumn("乗合"),
    "電車": st.column_config.CheckboxColumn("電車"),
    "台数": st.column_config.NumberColumn("台数", min_value=0, step=1),
    "交通費(円)": st.column_config.NumberColumn("交通費(円)", min_value=0, step=100),
    "承認": st.column_config.CheckboxColumn("承認"),
}


def _empty_workers_df(n: int = 3) -> pd.DataFrame:
    return pd.DataFrame({
        "作業員名": [None] * n,
        "開始": [_t(config.DEFAULT_START_TIME)] * n,
        "終了": [_t(config.DEFAULT_END_TIME)] * n,
        "残業(h)": [0.0] * n,
        "宿泊": [False] * n,
    })


def _empty_subs_df(n: int = 2) -> pd.DataFrame:
    return pd.DataFrame({
        "会社名": [None] * n, "作業員名": [None] * n, "人数": [0] * n,
        "開始": [_t(config.DEFAULT_START_TIME)] * n, "終了": [_t(config.DEFAULT_END_TIME)] * n,
        "作業内容": [None] * n, "車": [False] * n, "乗合": [False] * n, "電車": [False] * n,
        "台数": [0] * n, "交通費(円)": [0] * n, "承認": [False] * n,
    })


def _parse_workers(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, r in df.iterrows():
        name = _txt(r.get("作業員名"))
        if not name:
            continue
        out.append({
            "worker_name": name,
            "start_time": _time_to_str(r.get("開始")),
            "end_time": _time_to_str(r.get("終了")),
            "overtime_h": _num(r.get("残業(h)"), float, 0),
            "lodging": bool(r.get("宿泊")),
        })
    return out


def _parse_subs(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, r in df.iterrows():
        company = _txt(r.get("会社名"))
        if not company:
            continue
        out.append({
            "company_name": company,
            "worker_name": _txt(r.get("作業員名")),
            "headcount": _num(r.get("人数"), int, 0),
            "start_time": _time_to_str(r.get("開始")),
            "end_time": _time_to_str(r.get("終了")),
            "work_content": _txt(r.get("作業内容")),
            "transport_car": bool(r.get("車")),
            "transport_share": bool(r.get("乗合")),
            "transport_train": bool(r.get("電車")),
            "car_count": _num(r.get("台数"), int, 0),
            "transport_cost": _num(r.get("交通費(円)"), int, 0),
            "approved": bool(r.get("承認")),
        })
    return out


def site_options(active_only: bool = False) -> dict[str, int]:
    return {s["name"]: s["id"] for s in db.list_sites(active_only)}


# --------------------------------------------------------------------------
# 画面: 日報入力
# --------------------------------------------------------------------------
def _time_str(t) -> str:
    try:
        return t.strftime("%H:%M")
    except Exception:
        return ""


def _render_added_workers() -> None:
    """追加済みの自社作業員を一覧表示（削除ボタン付き）。"""
    workers = st.session_state.get("entry_workers", [])
    if not workers:
        st.caption("まだ追加されていません。")
        return
    total_h = sum(db.calc_span_hours(w["start_time"], w["end_time"]) for w in workers)
    st.caption(f"追加済み {len(workers)} 名 / 作業時間合計 {total_h:.1f} 時間")
    for i, w in enumerate(workers):
        col1, col2 = st.columns([6, 1])
        badge = "　🏠宿泊" if w.get("lodging") else ""
        ot = f"　残業{w['overtime_h']:.1f}h" if w.get("overtime_h") else ""
        col1.markdown(f"**{w['worker_name']}**　{w['start_time']}〜{w['end_time']}{ot}{badge}")
        if col2.button("❌", key=f"delw_{i}", help="削除"):
            st.session_state["entry_workers"].pop(i)
            st.rerun()


def _render_added_subs() -> None:
    subs = st.session_state.get("entry_subs", [])
    if not subs:
        return
    st.caption(f"追加済み協力会社 {len(subs)} 件")
    for i, s in enumerate(subs):
        col1, col2 = st.columns([6, 1])
        col1.markdown(
            f"**{s['company_name']}**　{s.get('worker_name') or ''}（{s['headcount']}名）"
            f"　交通費{s['transport_cost']:,}円"
        )
        if col2.button("❌", key=f"dels_{i}", help="削除"):
            st.session_state["entry_subs"].pop(i)
            st.rerun()


def page_entry() -> None:
    st.header("📝 日報入力")
    st.caption("🎤 「🎤」が付いた欄はタップして、スマホのキーボードのマイクで話すと入力できます。")

    if st.session_state.get("entry_flash"):
        st.success(st.session_state.pop("entry_flash"))

    sites = site_options(active_only=False)
    if not sites:
        st.warning("先に「現場管理」で現場を登録してください。")
        return
    st.session_state.setdefault("entry_workers", [])
    st.session_state.setdefault("entry_subs", [])
    n = st.session_state.get("entry_nonce", 0)
    wn = st.session_state.get("wname_nonce", 0)
    sn = st.session_state.get("sub_nonce", 0)

    # ---- ヘッダー（現場名・発注先は音声対象外） ----
    c1, c2 = st.columns([2, 1])
    report_date = c1.date_input("作業日", value=date.today(), key=f"e_date_{n}")
    # 曜日は作業日から毎回算出（key を付けると古い値が残るため付けない）
    c2.text_input("曜日", value=f"{config.weekday_jp(report_date.isoformat())}曜日", disabled=True)
    site_label = st.selectbox("現場名", list(sites.keys()), key=f"e_site_{n}")
    site = db.get_site(sites[site_label])
    client = st.text_input("発注先", value=(site or {}).get("client") or "", key=f"e_client_{n}")

    work_content = st.text_area("作業内容・使用材料　🎤", height=120, key=f"e_content_{n}",
                                placeholder="本日の作業内容・使用した材料")

    # ---- 自社作業員 ----
    st.markdown("#### 自社作業員")
    _render_added_workers()

    with st.container(border=True):
        st.markdown("##### ＋ 作業員を追加")
        cc = st.columns(4)
        w_start = cc[0].time_input("開始", value=_t(config.DEFAULT_START_TIME), key=f"w_start_{n}")
        w_end = cc[1].time_input("終了", value=_t(config.DEFAULT_END_TIME), key=f"w_end_{n}")
        w_ot = cc[2].number_input("残業(h)", min_value=0.0, step=0.5, key=f"w_ot_{n}")
        w_lodge = cc[3].checkbox("宿泊", key=f"w_lodge_{n}")

        active = db.list_workers(active_only=True)
        if active:
            st.caption("↓ 登録済みの作業員は名前をタップで追加（上の時間が入ります）")
            bcols = st.columns(3)
            for i, wk in enumerate(active):
                if bcols[i % 3].button(f"＋ {wk['name']}", key=f"pick_{wk['id']}_{n}",
                                       use_container_width=True):
                    st.session_state["entry_workers"].append({
                        "worker_name": wk["name"], "start_time": _time_str(w_start),
                        "end_time": _time_str(w_end), "overtime_h": float(w_ot),
                        "lodging": bool(w_lodge),
                    })
                    st.rerun()

        st.caption("↓ 名簿にない人・音声入力で追加（話した読みは漢字に変換されます）")
        wname = st.text_input("作業員名（ひらがな可）　🎤", key=f"w_name_{wn}",
                              placeholder="例：けんもち")
        if st.button("➕ この作業員を追加", key=f"w_add_{n}", use_container_width=True):
            if wname.strip():
                kanji, matched = db.match_worker_name(wname.strip())
                st.session_state["entry_workers"].append({
                    "worker_name": kanji, "start_time": _time_str(w_start),
                    "end_time": _time_str(w_end), "overtime_h": float(w_ot),
                    "lodging": bool(w_lodge),
                })
                st.session_state["wname_nonce"] = wn + 1
                st.session_state["entry_flash2"] = (
                    f"「{wname.strip()}」→ **{kanji}** に変換して追加しました。" if matched
                    else f"「{kanji}」を追加しました（名簿に一致なし・そのまま登録）。"
                )
                st.rerun()
            else:
                st.warning("作業員名を入力してください。")
    if st.session_state.get("entry_flash2"):
        st.info(st.session_state.pop("entry_flash2"))

    # ---- 交通手段等（自社） ----
    st.markdown("**交通手段等（自社）　🎤（交通費は数字）**")
    t1, t2, t3, t4 = st.columns([1, 1, 1, 1.5])
    own_car = t1.checkbox("車", key=f"e_car_{n}")
    own_car_count = t2.number_input("台数", min_value=0, step=1, key=f"e_carcnt_{n}")
    own_train = t3.checkbox("電車", key=f"e_train_{n}")
    own_cost = t4.number_input("交通費(円)", min_value=0, step=100, key=f"e_cost_{n}")

    # ---- 協力会社 ----
    st.markdown("#### 協力会社（任意）")
    _render_added_subs()
    with st.expander("＋ 協力会社を追加"):
        s_company = st.text_input("会社名　🎤", key=f"s_company_{sn}")
        s_worker = st.text_input("作業員名　🎤", key=f"s_worker_{sn}")
        sc = st.columns(3)
        s_head = sc[0].number_input("人数", min_value=0, step=1, key=f"s_head_{sn}")
        s_start = sc[1].time_input("開始", value=_t(config.DEFAULT_START_TIME), key=f"s_start_{sn}")
        s_end = sc[2].time_input("終了", value=_t(config.DEFAULT_END_TIME), key=f"s_end_{sn}")
        s_content = st.text_input("作業内容　🎤", key=f"s_content_{sn}")
        sc2 = st.columns(4)
        s_car = sc2[0].checkbox("車", key=f"s_car_{sn}")
        s_share = sc2[1].checkbox("乗合", key=f"s_share_{sn}")
        s_train = sc2[2].checkbox("電車", key=f"s_train_{sn}")
        s_approved = sc2[3].checkbox("承認", key=f"s_appr_{sn}")
        sc3 = st.columns(2)
        s_carcnt = sc3[0].number_input("台数", min_value=0, step=1, key=f"s_carcnt_{sn}")
        s_cost = sc3[1].number_input("交通費(円)", min_value=0, step=100, key=f"s_cost_{sn}")
        if st.button("➕ この協力会社を追加", key=f"s_add_{sn}", use_container_width=True):
            if s_company.strip():
                st.session_state["entry_subs"].append({
                    "company_name": s_company.strip(), "worker_name": s_worker.strip(),
                    "headcount": int(s_head), "start_time": _time_str(s_start),
                    "end_time": _time_str(s_end), "work_content": s_content.strip(),
                    "transport_car": s_car, "transport_share": s_share,
                    "transport_train": s_train, "car_count": int(s_carcnt),
                    "transport_cost": int(s_cost), "approved": s_approved,
                })
                st.session_state["sub_nonce"] = sn + 1
                st.rerun()
            else:
                st.warning("会社名を入力してください。")

    # ---- フッター ----
    manager = st.text_input("現場代理人又は責任者　🎤", key=f"e_mgr_{n}")
    status = st.selectbox("ステータス", config.REPORT_STATUSES, index=1, key=f"e_status_{n}")

    if st.button("✅ 日報を登録", type="primary", use_container_width=True):
        workers = st.session_state.get("entry_workers", [])
        if not workers:
            st.error("自社作業員を1名以上追加してください。")
            return
        subs = st.session_state.get("entry_subs", [])
        rid = db.add_report(
            report_date=report_date.isoformat(), site_id=sites[site_label],
            client=client.strip(), work_content=work_content.strip(),
            own_car=own_car, own_train=own_train,
            own_car_count=int(own_car_count), own_transport_cost=int(own_cost),
            manager=manager.strip(), status=status,
            workers=workers, subcontractors=subs,
        )
        new_names = db.register_new_workers([w["worker_name"] for w in workers])
        msg = f"日報を登録しました（ID: {rid}・作業員{len(workers)}名・協力会社{len(subs)}件）。"
        if new_names:
            msg += f"　🆕 名簿に新規登録: {'、'.join(new_names)}"
        st.session_state["entry_flash"] = msg
        st.session_state["entry_workers"] = []
        st.session_state["entry_subs"] = []
        st.session_state["entry_nonce"] = n + 1
        st.rerun()


# --------------------------------------------------------------------------
# 画面: 日報一覧
# --------------------------------------------------------------------------
def page_list() -> None:
    st.header("📋 日報一覧")
    sites = {"（すべて）": None} | site_options(active_only=False)

    with st.expander("🔍 フィルタ", expanded=True):
        f1, f2, f3 = st.columns(3)
        with f1:
            date_from = st.date_input("開始日", value=date.today() - timedelta(days=14))
            site_sel = st.selectbox("現場", list(sites.keys()))
        with f2:
            date_to = st.date_input("終了日", value=date.today())
            status_sel = st.selectbox("ステータス", ["（すべて）"] + config.REPORT_STATUSES)
        with f3:
            keyword = st.text_input("キーワード検索", placeholder="作業内容・作業員・責任者")

    reports = db.list_reports(
        date_from=date_from.isoformat(), date_to=date_to.isoformat(),
        site_id=sites[site_sel], status=None if status_sel == "（すべて）" else status_sel,
        keyword=keyword.strip() or None,
    )
    if not reports:
        st.info("該当する日報がありません。")
        return

    total_h = sum(r["total_hours"] for r in reports)
    total_p = sum(r["worker_count"] + r["sub_headcount"] for r in reports)
    st.caption(f"{len(reports)} 枚 / のべ {total_p} 名 / 総作業時間 {total_h:.1f} 時間")

    # 各行の右端に「詳細」ボタン（下までスクロール不要で遷移）
    widths = [1.7, 3, 0.9, 1.1, 1.1, 1]
    hcols = st.columns(widths)
    for col, label in zip(hcols, ["作業日", "現場", "人数", "作業時間", "状態", ""]):
        col.markdown(f"**{label}**")
    for r in reports:
        wd = config.weekday_jp(r["report_date"])
        cols = st.columns(widths)
        cols[0].write(f"{r['report_date']}（{wd}）")
        cols[1].write(r["site_name"])
        cols[2].write(f"{r['worker_count'] + r['sub_headcount']}名")
        cols[3].write(f"{r['total_hours']:.1f}h")
        cols[4].write(r["status"])
        if cols[5].button("詳細", key=f"detail_{r['id']}", use_container_width=True):
            st.session_state["selected_report"] = r["id"]
            st.session_state["page"] = "日報詳細"
            st.rerun()

    with st.expander("📊 表で見る（発注先・残業・交通費など）"):
        df = pd.DataFrame(reports)
        df["曜日"] = df["report_date"].map(config.weekday_jp)
        view = df[["id", "report_date", "曜日", "site_name", "client", "worker_count",
                   "sub_headcount", "total_hours", "total_overtime", "total_transport_cost",
                   "status"]].rename(columns={
            "id": "ID", "report_date": "作業日", "site_name": "現場", "client": "発注先",
            "worker_count": "自社人数", "sub_headcount": "協力人数", "total_hours": "作業時間",
            "total_overtime": "残業", "total_transport_cost": "交通費", "status": "状態"})
        st.dataframe(view, use_container_width=True, hide_index=True)


# --------------------------------------------------------------------------
# 画面: 日報詳細
# --------------------------------------------------------------------------
def page_detail() -> None:
    rid = st.session_state.get("selected_report")
    if not rid:
        st.info("「日報一覧」から日報を選択してください。")
        return
    r = db.get_report(rid)
    if not r:
        st.error("日報が見つかりません。")
        return
    workers = db.get_report_workers(rid)
    subs = db.get_report_subcontractors(rid)

    wd = config.weekday_jp(r["report_date"])
    st.header(f"🔎 作業日報  #{r['id']}")
    st.caption(f"{r['report_date']}（{wd}） ／ 現場: {r['site_name']} ／ 発注先: {r['client'] or '-'}")

    total_h = sum(w["work_hours"] for w in workers)
    total_ot = sum(w["overtime_h"] for w in workers)
    sub_head = sum(s["headcount"] for s in subs)
    sub_cost = sum(s["transport_cost"] for s in subs)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("自社人数", f"{len(workers)} 名")
    m2.metric("作業時間合計", f"{total_h:.1f} h")
    m3.metric("残業合計", f"{total_ot:.1f} h")
    m4.metric("交通費合計", f"{r['own_transport_cost'] + sub_cost:,} 円")

    st.markdown("#### 作業内容・使用材料")
    st.write(r["work_content"] or "-")

    st.markdown("#### 自社作業員")
    if workers:
        wdf = pd.DataFrame(workers)
        wdf["宿泊"] = wdf["lodging"].map({1: "○", 0: ""})
        wview = wdf[["worker_name", "start_time", "end_time", "work_hours", "overtime_h", "宿泊"]] \
            .rename(columns={"worker_name": "作業員名", "start_time": "開始", "end_time": "終了",
                             "work_hours": "作業時間", "overtime_h": "残業(h)"})
        st.dataframe(wview, use_container_width=True, hide_index=True)
    else:
        st.caption("（なし）")

    tp = []
    if r["own_car"]:
        tp.append(f"車{('（' + str(r['own_car_count']) + '台）') if r['own_car_count'] else ''}")
    if r["own_train"]:
        tp.append("電車")
    st.caption(f"交通手段（自社）: {'・'.join(tp) or '-'} ／ 交通費 {r['own_transport_cost']:,} 円")

    st.markdown("#### 協力会社")
    if subs:
        sdf = pd.DataFrame(subs)
        sdf["交通手段"] = sdf.apply(
            lambda x: "・".join([n for n, v in
                                 [("車", x["transport_car"]), ("乗合", x["transport_share"]),
                                  ("電車", x["transport_train"])] if v]) or "-", axis=1)
        sdf["承認"] = sdf["approved"].map({1: "○", 0: ""})
        sview = sdf[["company_name", "worker_name", "headcount", "start_time", "end_time",
                     "work_content", "交通手段", "transport_cost", "承認"]].rename(columns={
            "company_name": "会社名", "worker_name": "作業員名", "headcount": "人数",
            "start_time": "開始", "end_time": "終了", "work_content": "作業内容",
            "transport_cost": "交通費(円)"})
        st.dataframe(sview, use_container_width=True, hide_index=True)
        st.caption(f"協力会社 のべ {sub_head} 名 / 交通費 {sub_cost:,} 円")
    else:
        st.caption("（なし）")

    st.divider()
    st.markdown(f"**現場代理人又は責任者：** {r['manager'] or '-'}　／　**状態：** {r['status']}")

    _detail_edit(r, workers, subs)


def _detail_edit(r: dict, workers: list[dict], subs: list[dict]) -> None:
    rid = r["id"]
    with st.expander("✏️ 編集"):
        client = st.text_input("発注先", value=r["client"] or "", key="d_client")
        content = st.text_area("作業内容・使用材料", value=r["work_content"] or "", height=100,
                               key="d_content")

        st.markdown("**自社作業員**")
        wdf = pd.DataFrame([{
            "作業員名": w["worker_name"], "開始": _str_to_time(w["start_time"]),
            "終了": _str_to_time(w["end_time"]), "残業(h)": w["overtime_h"],
            "宿泊": bool(w["lodging"]),
        } for w in workers]) if workers else _empty_workers_df(1)
        worker_names = [w["name"] for w in db.list_workers(active_only=True)]
        ed_w = st.data_editor(wdf, num_rows="dynamic", use_container_width=True,
                              column_config=_worker_col_config(worker_names), key="d_workers")

        t1, t2, t3, t4 = st.columns([1, 1, 1, 1.5])
        own_car = t1.checkbox("車", value=bool(r["own_car"]), key="d_car")
        own_cnt = t2.number_input("台数", min_value=0, step=1, value=int(r["own_car_count"]),
                                  key="d_carcnt")
        own_train = t3.checkbox("電車", value=bool(r["own_train"]), key="d_train")
        own_cost = t4.number_input("交通費(円)", min_value=0, step=100,
                                   value=int(r["own_transport_cost"]), key="d_cost")

        st.markdown("**協力会社**")
        sdf = pd.DataFrame([{
            "会社名": s["company_name"], "作業員名": s["worker_name"], "人数": s["headcount"],
            "開始": _str_to_time(s["start_time"]), "終了": _str_to_time(s["end_time"]),
            "作業内容": s["work_content"], "車": bool(s["transport_car"]),
            "乗合": bool(s["transport_share"]), "電車": bool(s["transport_train"]),
            "台数": s["car_count"], "交通費(円)": s["transport_cost"], "承認": bool(s["approved"]),
        } for s in subs]) if subs else _empty_subs_df(1)
        ed_s = st.data_editor(sdf, num_rows="dynamic", use_container_width=True,
                              column_config=_SUB_COL_CONFIG, key="d_subs")

        e1, e2 = st.columns([2, 1])
        manager = e1.text_input("現場代理人又は責任者", value=r["manager"] or "", key="d_mgr")
        status = e2.selectbox("ステータス", config.REPORT_STATUSES,
                              index=config.REPORT_STATUSES.index(r["status"])
                              if r["status"] in config.REPORT_STATUSES else 1, key="d_status")

        if st.button("更新する", type="primary", key="d_save"):
            db.update_report(
                rid, client=client.strip(), work_content=content.strip(),
                own_car=own_car, own_train=own_train, own_car_count=int(own_cnt),
                own_transport_cost=int(own_cost), manager=manager.strip(), status=status,
                workers=_parse_workers(ed_w), subcontractors=_parse_subs(ed_s),
            )
            st.success("更新しました。")
            st.rerun()

    with st.expander("🗑️ 削除"):
        st.warning("この操作は取り消せません。")
        if st.button("この日報を削除", key="d_del"):
            db.delete_report(rid)
            st.session_state["selected_report"] = None
            st.session_state["page"] = "日報一覧"
            st.rerun()


# --------------------------------------------------------------------------
# 画面: ダッシュボード
# --------------------------------------------------------------------------
def page_dashboard() -> None:
    st.header("📊 ダッシュボード")
    today = date.today()
    month_start = today.replace(day=1)

    reports = db.list_reports(date_from=(today - timedelta(days=90)).isoformat())
    lines = db.list_worker_lines(date_from=(today - timedelta(days=90)).isoformat())
    if not reports:
        st.info("日報がまだありません。`python seed.py` でデモデータを投入できます。")
        return

    rdf = pd.DataFrame(reports)
    rdf["report_date"] = pd.to_datetime(rdf["report_date"])
    mrdf = rdf[rdf["report_date"] >= pd.Timestamp(month_start)]

    ldf = pd.DataFrame(lines)
    if not ldf.empty:
        ldf["report_date"] = pd.to_datetime(ldf["report_date"])
    mldf = ldf[ldf["report_date"] >= pd.Timestamp(month_start)] if not ldf.empty else ldf

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("今月の総作業時間", f"{(mldf['work_hours'].sum() if not mldf.empty else 0):.1f} h")
    k2.metric("今月の残業時間", f"{(mldf['overtime_h'].sum() if not mldf.empty else 0):.1f} h")
    people = int((mrdf["worker_count"] + mrdf["sub_headcount"]).sum()) if not mrdf.empty else 0
    k3.metric("今月ののべ人数", f"{people} 名")
    active_sites = len([s for s in db.list_sites() if s["status"] in config.ACTIVE_SITE_STATUSES])
    k4.metric("稼働中の現場", f"{active_sites} 件")

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("日別 作業時間の推移")
        if not ldf.empty:
            daily = ldf.groupby("report_date")["work_hours"].sum().reset_index()
            fig = px.line(daily, x="report_date", y="work_hours", markers=True,
                          labels={"report_date": "日付", "work_hours": "作業時間(h)"})
            st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.subheader("作業員別 作業時間")
        if not ldf.empty:
            byw = ldf.groupby("worker_name")["work_hours"].sum().reset_index() \
                .sort_values("work_hours")
            fig = px.bar(byw, x="work_hours", y="worker_name", orientation="h",
                         labels={"worker_name": "作業員", "work_hours": "作業時間(h)"})
            st.plotly_chart(fig, use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        st.subheader("現場別 作業時間")
        if not ldf.empty:
            bys = ldf.groupby("site_name")["work_hours"].sum().reset_index() \
                .sort_values("work_hours")
            fig = px.bar(bys, x="work_hours", y="site_name", orientation="h",
                         labels={"site_name": "現場", "work_hours": "作業時間(h)"})
            st.plotly_chart(fig, use_container_width=True)
    with c4:
        st.subheader("現場別 交通費")
        byc = rdf.groupby("site_name")["total_transport_cost"].sum().reset_index() \
            .sort_values("total_transport_cost")
        fig = px.bar(byc, x="total_transport_cost", y="site_name", orientation="h",
                     labels={"site_name": "現場", "total_transport_cost": "交通費(円)"})
        st.plotly_chart(fig, use_container_width=True)


# --------------------------------------------------------------------------
# 画面: 作業員管理
# --------------------------------------------------------------------------
def page_workers() -> None:
    st.header("👷 作業員管理")
    st.caption("よみがなを登録すると、日報入力で作業員名を音声入力したとき漢字に自動変換されます。")
    with st.expander("➕ 作業員を追加", expanded=not db.list_workers()):
        with st.form("add_worker", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name = c1.text_input("氏名（漢字）", placeholder="例：剣持 大輔")
            kana = c2.text_input("よみがな", placeholder="例：けんもちだいすけ")
            c3, c4 = st.columns(2)
            role = c3.text_input("役職", placeholder="職長 / 電工 / 見習い")
            phone = c4.text_input("電話番号")
            if st.form_submit_button("追加", type="primary"):
                if name.strip():
                    db.add_worker(name.strip(), role.strip(), phone.strip(), kana.strip())
                    st.success(f"{name} を追加しました。")
                    st.rerun()
                else:
                    st.error("氏名を入力してください。")

    workers = db.list_workers()
    if not workers:
        st.info("作業員が登録されていません。")
        return
    df = pd.DataFrame(workers)
    df["状態"] = df["is_active"].map({1: "有効", 0: "無効"})
    st.dataframe(df[["id", "name", "kana", "role", "phone", "状態"]].rename(
        columns={"id": "ID", "name": "氏名", "kana": "よみがな", "role": "役職",
                 "phone": "電話番号"}),
        use_container_width=True, hide_index=True)

    st.markdown("**作業員情報の編集**")
    wopts = {f"#{w['id']} {w['name']}": w for w in workers}
    wk_pick = st.selectbox("編集する作業員", list(wopts.keys()), key="w_edit_pick")
    wk = wopts[wk_pick]
    # 選択中の作業員IDをキーに含め、切替時に各欄へ現在値を反映
    e1, e2 = st.columns(2)
    new_name = e1.text_input("氏名（漢字）", value=wk["name"], key=f"edit_name_{wk['id']}")
    new_kana = e2.text_input("よみがな", value=wk.get("kana") or "", key=f"edit_kana_{wk['id']}")
    e3, e4, e5 = st.columns(3)
    new_role = e3.text_input("役職", value=wk.get("role") or "", key=f"edit_role_{wk['id']}")
    new_phone = e4.text_input("電話番号", value=wk.get("phone") or "", key=f"edit_phone_{wk['id']}")
    new_active = e5.selectbox("状態", ["有効", "無効"], index=0 if wk["is_active"] else 1,
                              key=f"edit_active_{wk['id']}")
    if st.button("変更を保存", type="primary", key="w_edit_save"):
        if new_name.strip():
            db.update_worker(wk["id"], name=new_name.strip(), kana=new_kana.strip(),
                             role=new_role.strip(), phone=new_phone.strip(),
                             is_active=1 if new_active == "有効" else 0)
            st.success("保存しました。")
            st.rerun()
        else:
            st.error("氏名を入力してください。")


# --------------------------------------------------------------------------
# 画面: 現場管理
# --------------------------------------------------------------------------
def page_sites() -> None:
    st.header("🏗️ 現場管理")
    with st.expander("➕ 現場を追加"):
        with st.form("add_site", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name = c1.text_input("現場名")
            client = c2.text_input("発注先")
            c3, c4, c5 = st.columns(3)
            address = c3.text_input("所在地")
            category = c4.selectbox("工事種別", config.WORK_TYPES)
            status = c5.selectbox("ステータス", config.SITE_STATUSES)
            c6, c7 = st.columns(2)
            start_date = c6.date_input("着工日", value=date.today())
            end_date = c7.date_input("完了予定日", value=date.today() + timedelta(days=30))
            memo = st.text_area("備考", height=68)
            if st.form_submit_button("追加", type="primary"):
                if name.strip():
                    db.add_site(name.strip(), client.strip(), address.strip(), category,
                                start_date.isoformat(), end_date.isoformat(), status, memo.strip())
                    st.success(f"{name} を追加しました。")
                    st.rerun()
                else:
                    st.error("現場名を入力してください。")

    sites = db.list_sites()
    if not sites:
        st.info("現場が登録されていません。")
        return
    df = pd.DataFrame(sites)
    st.dataframe(df[["id", "name", "client", "address", "category", "status",
                     "start_date", "end_date"]].rename(columns={
        "id": "ID", "name": "現場名", "client": "発注先", "address": "所在地",
        "category": "工事種別", "status": "状態", "start_date": "着工日", "end_date": "完了予定"}),
        use_container_width=True, hide_index=True)

    opts = {f"#{s['id']} {s['name']}": s for s in sites}
    picked = st.selectbox("現場", list(opts.keys()))
    s = opts[picked]
    new_status = st.selectbox("新しいステータス", config.SITE_STATUSES,
                              index=config.SITE_STATUSES.index(s["status"])
                              if s["status"] in config.SITE_STATUSES else 0)
    if st.button("更新する", type="primary"):
        db.update_site(s["id"], status=new_status)
        st.success("更新しました。")
        st.rerun()


# --------------------------------------------------------------------------
# ルーティング
# --------------------------------------------------------------------------
PAGES = {
    "日報入力": page_entry,
    "日報一覧": page_list,
    "日報詳細": page_detail,
    "ダッシュボード": page_dashboard,
    "作業員管理": page_workers,
    "現場管理": page_sites,
}

st.sidebar.title("🛠️ 作業日報管理")
st.sidebar.caption(config.COMPANY_NAME)

if "page" not in st.session_state:
    st.session_state["page"] = "日報入力"
choice = st.sidebar.radio("メニュー", list(PAGES.keys()),
                          index=list(PAGES.keys()).index(st.session_state["page"]))
if choice != st.session_state["page"]:
    st.session_state["page"] = choice

st.sidebar.divider()
today_count = len(db.list_reports(date_from=date.today().isoformat(),
                                  date_to=date.today().isoformat()))
st.sidebar.metric("本日の提出枚数", f"{today_count} 枚")

PAGES[st.session_state["page"]]()
