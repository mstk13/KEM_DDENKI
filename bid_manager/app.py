"""入札案件管理システム — Streamlit メインアプリ。

サイドバーから5画面を切り替える:
  案件一覧 / 案件詳細 / ダッシュボード / 対象サイト管理 / 単価マスタ
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

import config
import database as db

st.set_page_config(page_title="入札案件管理 | ケンモチ電機", page_icon="⚡", layout="wide")
db.init_db()


def _rows_to_df(rows) -> pd.DataFrame:
    return pd.DataFrame([dict(r) for r in rows])


# --------------------------------------------------------------------------- #
# 1. 案件一覧
# --------------------------------------------------------------------------- #
def page_list() -> None:
    st.header("📋 案件一覧")

    c1, c2, c3, c4 = st.columns(4)
    status = c1.selectbox("ステータス", ["（すべて）"] + config.STATUSES)
    region = c2.selectbox("エリア", ["（すべて）"] + config.REGIONS)
    within = c3.selectbox("締め切り", ["（すべて）", "3日以内", "7日以内", "14日以内"])
    order = c4.selectbox("並び順", ["締め切り日順", "登録日順"])
    keyword = st.text_input("キーワード検索（案件名・発注機関）", "")

    within_days = {"3日以内": 3, "7日以内": 7, "14日以内": 14}.get(within)
    rows = db.list_projects(
        status=None if status == "（すべて）" else status,
        region=None if region == "（すべて）" else region,
        keyword=keyword or None,
        within_days=within_days,
        order_by="created" if order == "登録日順" else "deadline",
    )

    st.caption(f"{len(rows)} 件")
    if not rows:
        st.info("該当する案件がありません。対象サイトを登録してスクレイピングするか、デモデータを投入してください。")
        return

    df = _rows_to_df(rows)[
        ["id", "title", "client", "region", "category", "deadline", "budget", "status"]
    ].rename(
        columns={
            "id": "ID", "title": "案件名", "client": "発注機関", "region": "エリア",
            "category": "種別", "deadline": "締切", "budget": "予定価格", "status": "状態",
        }
    )
    st.dataframe(df, use_container_width=True, hide_index=True)

    ids = [r["id"] for r in rows]
    pid = st.selectbox("詳細を見る案件IDを選択", ids, format_func=lambda i: f"#{i} {db.get_project(i)['title']}")
    if st.button("詳細を開く ▶"):
        st.session_state["selected_project"] = pid
        st.session_state["page"] = "案件詳細"
        st.rerun()


# --------------------------------------------------------------------------- #
# 2. 案件詳細
# --------------------------------------------------------------------------- #
def page_detail() -> None:
    st.header("🔍 案件詳細")
    pid = st.session_state.get("selected_project")
    all_ids = [p["id"] for p in db.list_projects(order_by="created")]
    if not all_ids:
        st.info("案件がありません。")
        return
    pid = st.selectbox(
        "案件", all_ids,
        index=all_ids.index(pid) if pid in all_ids else 0,
        format_func=lambda i: f"#{i} {db.get_project(i)['title']}",
    )
    st.session_state["selected_project"] = pid
    p = db.get_project(pid)

    # 基本情報
    st.subheader(p["title"])
    c1, c2, c3 = st.columns(3)
    c1.metric("発注機関", p["client"] or "—")
    c2.metric("エリア", p["region"] or "—")
    c3.metric("締切", p["deadline"] or "—")
    if p["source_url"]:
        st.markdown(f"🔗 [元ページを開く]({p['source_url']})")

    # ステータス変更
    with st.form("status_form"):
        new_status = st.selectbox(
            "ステータス", config.STATUSES, index=config.STATUSES.index(p["status"])
        )
        if st.form_submit_button("ステータスを更新"):
            db.update_status(pid, new_status)
            st.success(f"ステータスを「{new_status}」に更新しました。")
            st.rerun()

    st.divider()

    # 費用入力
    st.subheader("💰 費用管理")
    cost = db.get_cost(pid)
    with st.form("cost_form"):
        c1, c2 = st.columns(2)
        est = c1.number_input(
            "見積金額（円）", min_value=0, step=10000,
            value=int(cost["estimate_amount"]) if cost and cost["estimate_amount"] else 0,
        )
        act = c2.number_input(
            "実際の工事原価（円）", min_value=0, step=10000,
            value=int(cost["actual_cost"]) if cost and cost["actual_cost"] else 0,
        )
        memo = st.text_area("備考（なぜこの金額にしたか等）", value=cost["memo"] if cost else "")
        if st.form_submit_button("費用を保存"):
            db.upsert_cost(
                pid,
                estimate_amount=est or None,
                actual_cost=act or None,
                memo=memo or None,
            )
            st.success("費用を保存しました。")
            st.rerun()

    cost = db.get_cost(pid)
    if cost and cost["profit"] is not None:
        c1, c2 = st.columns(2)
        c1.metric("利益（見積 − 原価）", f"{cost['profit']:,} 円")
        c2.metric("原価率", f"{cost['profit_rate']} %")

    st.divider()

    # 競合情報（失注時）
    st.subheader("🏢 競合情報")
    with st.form("competitor_form"):
        c1, c2 = st.columns(2)
        cname = c1.text_input("落札会社名")
        camount = c2.number_input("落札金額（円）", min_value=0, step=10000)
        source = st.text_input("情報源（例：官報、自治体サイト）")
        cmemo = st.text_area("備考（どこで負けたか等）")
        if st.form_submit_button("競合情報を追加"):
            db.add_competitor(
                pid,
                competitor_name=cname or None,
                competitor_amount=camount or None,
                source=source or None,
                memo=cmemo or None,
            )
            st.success("競合情報を追加しました。")
            st.rerun()

    comps = db.list_competitors(pid)
    if comps:
        df = _rows_to_df(comps)[
            ["competitor_name", "competitor_amount", "diff_amount", "source", "memo"]
        ].rename(columns={
            "competitor_name": "落札会社", "competitor_amount": "落札金額",
            "diff_amount": "自社との差額", "source": "情報源", "memo": "備考",
        })
        st.dataframe(df, use_container_width=True, hide_index=True)


# --------------------------------------------------------------------------- #
# 3. ダッシュボード
# --------------------------------------------------------------------------- #
def page_dashboard() -> None:
    import plotly.express as px

    st.header("📊 ダッシュボード")
    rows = db.list_projects(order_by="created")
    if not rows:
        st.info("データがありません。")
        return
    df = _rows_to_df(rows)
    df["created_at"] = pd.to_datetime(df["created_at"])
    this_month = datetime.now().strftime("%Y-%m")
    month_df = df[df["created_at"].dt.strftime("%Y-%m") == this_month]

    bid_done = df[df["status"].isin(["入札済", "受注", "失注"])]
    won = df[df["status"] == config.WON_STATUS]
    win_rate = (len(won) / len(bid_done) * 100) if len(bid_done) else 0.0

    # 原価率・受注金額（costs から集計）
    cost_rows = [db.get_cost(int(r["id"])) for r in rows]
    rates = [c["profit_rate"] for c in cost_rows if c and c["profit_rate"] is not None]
    avg_rate = sum(rates) / len(rates) if rates else 0.0
    won_ids = set(won["id"].tolist())
    won_amount = sum(
        c["estimate_amount"] for c in cost_rows
        if c and c["project_id"] in won_ids and c["estimate_amount"]
    )

    # KPIカード
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("今月の登録案件", f"{len(month_df)} 件")
    c2.metric("受注件数 / 受注率", f"{len(won)} 件", f"{win_rate:.1f}%")
    c3.metric("平均原価率", f"{avg_rate:.1f}%")
    c4.metric("受注金額合計", f"{won_amount:,} 円")

    st.divider()

    # 月別件数・受注の推移
    df["month"] = df["created_at"].dt.strftime("%Y-%m")
    monthly = df.groupby("month").size().reset_index(name="件数")
    if len(monthly):
        st.plotly_chart(
            px.line(monthly, x="month", y="件数", markers=True, title="月別 案件件数の推移"),
            use_container_width=True,
        )

    # エリア別件数
    c1, c2 = st.columns(2)
    by_region = df.groupby("region").size().reset_index(name="件数")
    if len(by_region):
        c1.plotly_chart(
            px.bar(by_region, x="region", y="件数", title="エリア別 案件件数"),
            use_container_width=True,
        )
    by_cat = df.groupby("category").size().reset_index(name="件数")
    if len(by_cat):
        c2.plotly_chart(
            px.bar(by_cat, x="category", y="件数", title="種別 案件件数"),
            use_container_width=True,
        )

    # 原価率の分布
    if rates:
        st.plotly_chart(
            px.histogram(pd.DataFrame({"原価率": rates}), x="原価率", nbins=20,
                         title="原価率の分布"),
            use_container_width=True,
        )


# --------------------------------------------------------------------------- #
# 4. 対象サイト管理
# --------------------------------------------------------------------------- #
def page_targets() -> None:
    st.header("🌐 対象サイト管理")

    with st.form("add_target"):
        st.subheader("サイトを追加")
        c1, c2, c3 = st.columns([2, 3, 1])
        name = c1.text_input("サイト名")
        url = c2.text_input("URL")
        region = c3.selectbox("エリア", ["（指定なし）"] + config.REGIONS)
        if st.form_submit_button("追加"):
            if name and url:
                rid = db.add_target(name, url, None if region == "（指定なし）" else region)
                if rid:
                    st.success(f"「{name}」を追加しました。")
                    st.rerun()
                else:
                    st.warning("同じURLが既に登録されています。")
            else:
                st.error("サイト名とURLは必須です。")

    targets = db.list_targets()
    if not targets:
        st.info("対象サイトが未登録です。")
        return

    st.subheader("登録済みサイト")
    for t in targets:
        c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
        c1.write(f"**{t['name']}**\n\n{t['url']}")
        c2.write(f"エリア: {t['region'] or '—'}\n\n最終取得: {t['last_scraped_at'] or '未'}")
        active = c3.toggle("有効", value=bool(t["is_active"]), key=f"act_{t['id']}")
        if active != bool(t["is_active"]):
            db.set_target_active(t["id"], active)
            st.rerun()
        if c4.button("削除", key=f"del_{t['id']}"):
            db.delete_target(t["id"])
            st.rerun()

    st.divider()
    if st.button("🔄 今すぐスクレイピング実行"):
        import scraper
        with st.spinner("収集中…"):
            results = scraper.scrape_all()
        for r in results:
            if r.errors:
                st.error(f"[{r.target_name}] {'; '.join(r.errors)}")
            else:
                st.success(f"[{r.target_name}] 取得 {r.found} 件 / 新規保存 {r.saved} 件")


# --------------------------------------------------------------------------- #
# 5. 単価マスタ
# --------------------------------------------------------------------------- #
def page_unit_prices() -> None:
    st.header("📐 単価マスタ")
    with st.form("add_unit"):
        c1, c2, c3, c4 = st.columns([2, 3, 1, 2])
        category = c1.selectbox("工事種別", config.CATEGORIES)
        item = c2.text_input("項目名（例：VVFケーブル2.0mm）")
        unit = c3.text_input("単位（m/本/式）")
        price = c4.number_input("単価（円）", min_value=0, step=100)
        memo = st.text_input("備考")
        if st.form_submit_button("追加"):
            if item:
                db.add_unit_price(
                    category=category, item_name=item, unit=unit, unit_price=int(price), memo=memo or None
                )
                st.success("単価を追加しました。")
                st.rerun()
            else:
                st.error("項目名は必須です。")

    rows = db.list_unit_prices()
    if rows:
        df = _rows_to_df(rows)[["category", "item_name", "unit", "unit_price", "memo"]].rename(
            columns={"category": "種別", "item_name": "項目", "unit": "単位",
                     "unit_price": "単価", "memo": "備考"}
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("単価が未登録です。")


# --------------------------------------------------------------------------- #
# ルーティング
# --------------------------------------------------------------------------- #
PAGES = {
    "案件一覧": page_list,
    "案件詳細": page_detail,
    "ダッシュボード": page_dashboard,
    "対象サイト管理": page_targets,
    "単価マスタ": page_unit_prices,
}

st.sidebar.title("⚡ 入札案件管理")
st.sidebar.caption("株式会社ケンモチ電機")
default = st.session_state.get("page", "案件一覧")
choice = st.sidebar.radio("メニュー", list(PAGES.keys()), index=list(PAGES.keys()).index(default))
st.session_state["page"] = choice
PAGES[choice]()
