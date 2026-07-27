"""入札案件管理システム — Streamlit メインアプリ。

サイドバーから6画面を切り替える:
  案件一覧 / 案件詳細 / ダッシュボード / 対象サイト管理 / 単価マスタ / 入札資格管理
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as _components

import config
import database as db

st.set_page_config(page_title="入札案件管理 | ケンモチ電機", page_icon="⚡", layout="wide")

def _disable_browser_translation():
    """ブラウザの自動翻訳がページを書き換えるのを防ぐ。

    Chrome/Edge が日本語ページを翻訳すると表示文が別の語に置き換わり、
    Streamlit(React) の再描画とも衝突して removeChild エラーの原因になる。
    """
    _components.html(
        """
        <script>
        try {
          const doc = window.parent.document;
          doc.documentElement.setAttribute('translate', 'no');
          doc.documentElement.lang = 'ja';
          doc.documentElement.classList.add('notranslate');
          if (!doc.querySelector('meta[name="google"][content="notranslate"]')) {
            const m = doc.createElement('meta');
            m.name = 'google'; m.content = 'notranslate';
            doc.head.appendChild(m);
          }
        } catch (e) {}
        </script>
        """,
        height=0,
    )


_disable_browser_translation()

db.init_db()


def _rows_to_df(rows) -> pd.DataFrame:
    return pd.DataFrame([dict(r) for r in rows])


# --------------------------------------------------------------------------- #
# 1. 案件一覧
# --------------------------------------------------------------------------- #
def page_list() -> None:
    st.header("📋 案件一覧")

    # --- 手動追加フォーム ---
    with st.expander("➕ 案件を手動で追加", expanded=False):
        with st.form("manual_add_form"):
            m_title = st.text_input("案件名 *", placeholder="例：〇〇基地 電気設備改修工事")
            mc1, mc2, mc3 = st.columns(3)
            m_client = mc1.text_input("発注機関", placeholder="例：防衛省 航空自衛隊")
            m_region = mc2.selectbox("エリア", ["（未指定）"] + config.REGIONS, key="m_region")
            m_category = mc3.selectbox("工事種別", ["（未指定）"] + config.CATEGORIES, key="m_category")
            mc4, mc5 = st.columns(2)
            m_deadline = mc4.date_input("入札締め切り日", value=None)
            m_budget = mc5.number_input("予定価格（円）※分かれば", min_value=0, step=100000, value=0)
            m_url = st.text_input("元ページURL", placeholder="https://...")
            if st.form_submit_button("登録", type="primary"):
                if not m_title:
                    st.error("案件名は必須です。")
                else:
                    pid = db.add_project(
                        title=m_title,
                        client=m_client or None,
                        region=None if m_region == "（未指定）" else m_region,
                        category=None if m_category == "（未指定）" else m_category,
                        deadline=m_deadline.isoformat() if m_deadline else None,
                        budget=m_budget or None,
                        source_url=m_url or None,
                    )
                    if pid:
                        st.success(f"案件「{m_title}」を登録しました（ID: {pid}）。")
                        st.rerun()
                    else:
                        st.warning("同じ案件名・URLの組み合わせが既に登録されています。")

    st.divider()

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

    # 未入力件数の警告
    incomplete = [r for r in rows if not r["client"] or not r["region"] or not r["category"]]
    if incomplete:
        st.warning(f"⚠️ {len(incomplete)} 件の案件で発注機関・エリア・工事種別が未入力です。「案件詳細」から入力してください。")

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
    # 未入力セルを目立たせる
    df = df.fillna("❌ 未入力")
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

    # 元ページリンク（編集時に参照しやすいよう上部に常時表示）
    if p["source_url"]:
        st.markdown(f"🔗 [元ページを開く]({p['source_url']})")

    # 未入力フィールドの警告
    missing = []
    if not p["client"]:
        missing.append("発注機関")
    if not p["region"]:
        missing.append("エリア")
    if not p["category"]:
        missing.append("工事種別")
    if not p["deadline"]:
        missing.append("締切日")
    if not p["budget"]:
        missing.append("予定価格")
    if missing:
        st.warning(f"⚠️ 未入力: {' / '.join(missing)}　— 下の「基本情報を編集」から入力してください")

    # 基本情報の表示
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("発注機関", p["client"] or "—")
    c2.metric("エリア", p["region"] or "—")
    c3.metric("工事種別", p["category"] or "—")
    c4.metric("締切", p["deadline"] or "—")
    c5, c6 = st.columns(2)
    c5.metric("予定価格", f"{p['budget']:,} 円" if p["budget"] else "—")
    c6.metric("ステータス", p["status"])

    # --- 基本情報の編集フォーム ---
    with st.expander("✏️ 基本情報を編集", expanded=bool(missing)):
        with st.form("edit_project_form"):
            e_title = st.text_input("案件名", value=p["title"])

            ec1, ec2, ec3 = st.columns(3)
            e_client = ec1.text_input("発注機関", value=p["client"] or "", placeholder="例：防衛省 航空自衛隊")
            region_opts = ["（未指定）"] + config.REGIONS
            cur_region_idx = region_opts.index(p["region"]) if p["region"] in region_opts else 0
            e_region = ec2.selectbox("エリア", region_opts, index=cur_region_idx, key="e_region")
            cat_opts = ["（未指定）"] + config.CATEGORIES
            cur_cat_idx = cat_opts.index(p["category"]) if p["category"] in cat_opts else 0
            e_category = ec3.selectbox("工事種別", cat_opts, index=cur_cat_idx, key="e_category")

            ec4, ec5 = st.columns(2)
            e_deadline = ec4.date_input(
                "入札締め切り日",
                value=date.fromisoformat(p["deadline"]) if p["deadline"] else None,
            )
            e_budget = ec5.number_input(
                "予定価格（円）",
                min_value=0, step=100000,
                value=int(p["budget"]) if p["budget"] else 0,
            )

            e_status = st.selectbox(
                "ステータス", config.STATUSES,
                index=config.STATUSES.index(p["status"]),
            )
            e_url = st.text_input("元ページURL", value=p["source_url"] or "")

            if st.form_submit_button("保存", type="primary"):
                if not e_title:
                    st.error("案件名は必須です。")
                else:
                    new_region = None if e_region == "（未指定）" else e_region
                    new_category = None if e_category == "（未指定）" else e_category
                    new_deadline = e_deadline.isoformat() if e_deadline else None
                    # 全フィールドを直接 UPDATE する
                    with db.get_conn() as conn:
                        conn.execute(
                            """UPDATE projects SET
                                title=?, client=?, region=?, category=?,
                                deadline=?, budget=?, source_url=?, status=?,
                                updated_at=?
                               WHERE id=?""",
                            (e_title, e_client or None, new_region, new_category,
                             new_deadline, e_budget or None, e_url or None, e_status,
                             datetime.now().isoformat(timespec="seconds"), pid),
                        )
                    st.success("基本情報を更新しました。")
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
# 6. 入札資格管理
# --------------------------------------------------------------------------- #
def page_qualifications() -> None:
    st.header("🏛 入札参加資格管理")

    quals = db.list_qualifications()

    # --- ステータスバナー（一目で状態がわかる） ---
    if quals:
        _show_qualification_status(quals)
    else:
        st.info(
            "資格データが未登録です。\n\n"
            "**初回のみ**、お持ちの入札参加資格一覧（Excel / PDF）をアップロードしてください。\n"
            "一度登録すれば、有効期限が近づくまで更新は不要です。"
        )

    st.divider()

    # --- ファイルインポート ---
    with st.expander("📥 資格データのインポート（Excel / PDF）", expanded=not quals):
        st.caption("初回登録 or 資格更新時のみ使用。通常は触る必要はありません。")
        uploaded = st.file_uploader(
            "ファイルを選択（.xlsx または .pdf）",
            type=["xlsx", "pdf"],
            key="qual_upload",
        )
        if uploaded is not None:
            import tempfile
            from pathlib import Path
            import importer

            suffix = Path(uploaded.name).suffix.lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(uploaded.read())
                tmp_path = tmp.name

            try:
                if suffix == ".xlsx":
                    records = importer.import_excel(tmp_path)
                elif suffix == ".pdf":
                    records = importer.import_pdf(tmp_path)
                else:
                    st.error("対応していないファイル形式です。")
                    return

                if not records:
                    st.warning("資格データが見つかりませんでした。ファイルの形式を確認してください。")
                    return

                st.success(f"{len(records)} 件の資格データを検出しました。")

                preview_df = pd.DataFrame(records)
                st.dataframe(
                    preview_df.rename(columns={
                        "issuer": "発注先", "category": "認定種目", "grade": "等級",
                        "keisin_score": "経審", "total_score": "総合",
                        "vendor_number": "業者番号", "valid_from": "開始日",
                        "valid_until": "終了日", "application_type": "申請区分",
                        "application_method": "申請方法",
                    }),
                    use_container_width=True, hide_index=True, height=300,
                )

                col1, col2 = st.columns(2)
                replace = col1.checkbox("既存データを全て置き換える", value=True)
                if col2.button("インポート実行", type="primary"):
                    if replace:
                        db.delete_all_qualifications()
                    for rec in records:
                        db.add_qualification(**rec)
                    db.save_qualifications_to_json()
                    st.success(
                        f"{len(records)} 件をインポートしました。\n\n"
                        f"資格データは `data/qualifications.json` に保存されました。\n"
                        f"このファイルを Git にコミットすれば、別のPCでも自動で復元されます。"
                    )
                    st.rerun()
            finally:
                Path(tmp_path).unlink(missing_ok=True)

    if not quals:
        return

    st.divider()

    # --- 登録済み資格一覧 ---
    st.subheader("📋 登録済み資格一覧")

    df = _rows_to_df(quals)
    display_cols = {
        "id": "ID", "issuer": "発注先", "category": "認定種目", "grade": "等級",
        "keisin_score": "経審", "total_score": "総合", "vendor_number": "業者番号",
        "valid_from": "開始日", "valid_until": "終了日",
        "application_type": "申請区分", "application_method": "申請方法",
        "renewed": "更新済",
    }
    show_df = df[[c for c in display_cols if c in df.columns]].rename(columns=display_cols)
    show_df["更新済"] = show_df["更新済"].map({0: "—", 1: "✅"})

    # 残り日数の列を追加
    today = date.today()
    remaining_days = []
    for _, row in df.iterrows():
        vu = row.get("valid_until")
        if vu:
            try:
                days_left = (date.fromisoformat(str(vu)) - today).days
                remaining_days.append(f"{days_left}日" if days_left >= 0 else "期限切れ")
            except (ValueError, TypeError):
                remaining_days.append("—")
        else:
            remaining_days.append("—")
    show_df.insert(show_df.columns.get_loc("終了日") + 1, "残り", remaining_days)

    # フィルタ
    c1, c2 = st.columns(2)
    issuers = ["（すべて）"] + sorted(df["issuer"].dropna().unique().tolist())
    sel_issuer = c1.selectbox("発注先で絞り込み", issuers, key="q_issuer")
    sel_renewed = c2.selectbox("更新状態", ["（すべて）", "未更新のみ", "更新済のみ"], key="q_renewed")

    if sel_issuer != "（すべて）":
        show_df = show_df[show_df["発注先"] == sel_issuer]
    if sel_renewed == "未更新のみ":
        show_df = show_df[show_df["更新済"] == "—"]
    elif sel_renewed == "更新済のみ":
        show_df = show_df[show_df["更新済"] == "✅"]

    st.caption(f"{len(show_df)} 件")
    st.dataframe(show_df, use_container_width=True, hide_index=True)

    # 更新済みマーク（期限切れ間近のみ表示）
    expiring = db.list_qualifications_expiring(within_days=90)
    if expiring:
        st.subheader("✅ 更新手続き完了を記録する")
        st.caption("更新手続きが済んだ資格にチェックを付けると、アラートが消えます。")
        qid = st.selectbox(
            "資格を選択",
            [q["id"] for q in expiring],
            format_func=lambda i: f"#{i} {db.get_qualification(i)['issuer']} / {db.get_qualification(i)['category']} (期限: {db.get_qualification(i)['valid_until']})",
            key="q_renew_select",
        )
        if st.button("この資格を「更新済み」にする"):
            db.mark_qualification_renewed(qid)
            st.success("更新済みにしました。アラートは消えます。")
            st.rerun()


def _show_qualification_status(quals) -> None:
    """資格の全体ステータスを表示する。
    - 全て有効: 緑バナー「次回確認: YYYY年MM月」
    - 期限間近: 黄色/赤で警告
    """
    from datetime import timedelta

    today = date.today()

    # 最も早い有効期限を見つける
    earliest_expiry = None
    for q in quals:
        vu = q["valid_until"]
        if vu and not q["renewed"]:
            try:
                d = date.fromisoformat(str(vu))
                if earliest_expiry is None or d < earliest_expiry:
                    earliest_expiry = d
            except (ValueError, TypeError):
                pass

    if earliest_expiry is None:
        st.success("✅ **全ての資格が有効 or 更新済みです。** 現時点で対応は不要です。")
        return

    days_until = (earliest_expiry - today).days
    # 2ヶ月前から警告開始
    warn_date = earliest_expiry - timedelta(days=60)

    if days_until < 0:
        st.error(
            f"🚨 **有効期限が切れた資格があります！**（{earliest_expiry}）\n\n"
            f"至急更新手続きを行い、下の一覧で「更新済み」にチェックしてください。"
        )
    elif days_until <= 30:
        st.error(
            f"🚨 **あと{days_until}日で期限切れの資格があります！**（{earliest_expiry}）\n\n"
            f"更新手続きを急いでください。完了したら「更新済み」にチェックしてください。"
        )
        _show_expiring_list(quals, today, 30)
    elif days_until <= 60:
        st.warning(
            f"⚠️ **あと{days_until}日で期限切れの資格があります。**（{earliest_expiry}）\n\n"
            f"更新準備を始めてください。完了したら「更新済み」にチェックしてください。"
        )
        _show_expiring_list(quals, today, 60)
    else:
        next_check_date = warn_date
        st.success(
            f"✅ **全ての資格が有効です。** 次に確認が必要な時期: **{next_check_date.year}年{next_check_date.month}月**\n\n"
            f"最も早い有効期限: {earliest_expiry}（あと{days_until}日）— それまで更新作業は不要です。"
        )


def _show_expiring_list(quals, today, within_days: int) -> None:
    """期限間近の資格リストを表示する。"""
    for q in quals:
        vu = q["valid_until"]
        if not vu or q["renewed"]:
            continue
        try:
            d = date.fromisoformat(str(vu))
            days_left = (d - today).days
            if days_left <= within_days:
                st.warning(
                    f"　・{q['issuer']} / {q['category']}（等級: {q['grade'] or '—'}）"
                    f"— 期限: {vu}（あと{days_left}日）"
                )
        except (ValueError, TypeError):
            pass


# --------------------------------------------------------------------------- #
# ルーティング
# --------------------------------------------------------------------------- #
PAGES = {
    "案件一覧": page_list,
    "案件詳細": page_detail,
    "ダッシュボード": page_dashboard,
    "対象サイト管理": page_targets,
    "単価マスタ": page_unit_prices,
    "入札資格管理": page_qualifications,
}

st.sidebar.title("⚡ 入札案件管理")
st.sidebar.caption("株式会社ケンモチ電機")

# サイドバーに資格アラートバッジ
_qual_alerts = db.list_qualifications_expiring(within_days=60)
_alert_badge = f" ({len(_qual_alerts)})" if _qual_alerts else ""

default = st.session_state.get("page", "案件一覧")
choice = st.sidebar.radio(
    "メニュー",
    list(PAGES.keys()),
    index=list(PAGES.keys()).index(default),
    format_func=lambda x: f"{x}🔴{_alert_badge}" if x == "入札資格管理" and _alert_badge else x,
)
st.session_state["page"] = choice
PAGES[choice]()
