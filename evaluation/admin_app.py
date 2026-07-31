"""人事評価 — 管理アプリ

従業員ごとの評価一覧・詳細・集計と、評価基準／設問の編集を行う。
評価の入力は入力アプリ（app.py）側。

閲覧には社員IDによるログインが必要（admin_users.json で許可した社員のみ）。

起動: streamlit run admin_app.py --server.port 8505
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# core / views / pdf_export はこのファイルと同じフォルダにある（起動ディレクトリに依存しない）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth          # noqa: E402
import core          # noqa: E402
import pdf_export    # noqa: E402
import views         # noqa: E402

st.set_page_config(page_title="人事評価 管理", page_icon="🗂️", layout="wide")
# 設問文がブラウザに翻訳され別の意味に書き換わるのを防ぐ（title より先に実行する）
views.disable_browser_translation()
st.title("🗂️ 人事評価 管理")

# ログインしていなければ、ここでログイン画面を出して以降を実行しない。
current_user = auth.require_login()
auth.render_sidebar_user()
st.sidebar.divider()

ALL_ROLES = core.get_all_roles() or ["事務", "電工", "役員"]

menu = st.sidebar.radio(
    "メニュー", ["従業員一覧", "評価の履歴", "評価対象の設定", "評価基準の閲覧", "評価基準の編集"]
)

# 従業員一覧で行が選ばれている間は、詳細画面に切り替える
if menu == "従業員一覧" and st.session_state.get("detail_employee"):
    menu = "__detail__"
elif menu != "従業員一覧":
    st.session_state.pop("detail_employee", None)

st.sidebar.divider()
st.sidebar.caption("評価の入力は **入力アプリ** で行います。")


def render_answer_comparison(employee: str, evals: list[dict]):
    """設問ごとの回答を評価者別に横並びで表示する。"""
    matrix, self_labels, other_labels = core.build_answer_matrix(employee, evals)
    if matrix.empty:
        st.caption("設問ごとの回答が記録された評価がありません。")
        return None

    score_cols = self_labels + other_labels
    extra_cols = [c for c in ["他者平均", "差（本人−他者）"] if c in matrix.columns]

    if self_labels:
        st.caption(f"左端の **{self_labels[0]}** が自己評価です（回答者と対象者が一致）。")
    else:
        st.caption("自己評価（評価者名＝対象者名）の記録はまだありません。"
                   "入力アプリの「評価者」欄に本人の氏名を入れて保存すると本人列になります。")
    st.caption(core.SCALE_LEGEND)

    # ------------------------------------------------------------------
    # 設問ごとの得点を評価者別に横並び表示（この画面のメイン）
    # ------------------------------------------------------------------
    display_cols = ["項目", "#", "設問"] + score_cols + extra_cols
    col_config = {
        "項目": st.column_config.TextColumn("項目", width="medium", pinned=True),
        "#": st.column_config.TextColumn("#", width="small", pinned=True),
        "設問": st.column_config.TextColumn("設問", width="large", pinned=True),
    }
    col_config.update({c: st.column_config.NumberColumn(c, format="%d", width="small")
                       for c in score_cols})
    col_config.update({c: st.column_config.NumberColumn(c, format="%.2f", width="small")
                       for c in extra_cols})

    group_by_item = st.toggle("評価項目ごとに分けて表示する", value=False, key="cmp_grouped")

    if group_by_item:
        for item_name, group in matrix.groupby("項目", sort=False):
            means = group[score_cols].mean().round(2)
            head = "　".join(f"{c}: {means[c]:.2f}" for c in score_cols if pd.notna(means[c]))
            with st.expander(f"{item_name}（{len(group)}問）　{head}", expanded=True):
                st.dataframe(group[["#", "設問"] + score_cols + extra_cols],
                             use_container_width=True, hide_index=True,
                             column_config={k: v for k, v in col_config.items() if k != "項目"})
    else:
        st.dataframe(
            matrix[display_cols],
            use_container_width=True,
            hide_index=True,
            column_config=col_config,
            height=min(1000, 36 * len(matrix) + 40),
        )

    st.download_button(
        "この比較表をCSVでダウンロード",
        matrix[display_cols].to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{employee}_設問別比較.csv",
        mime="text/csv",
        key="dl_cmp",
    )

    # ------------------------------------------------------------------
    # 評価項目ごとの平均（サマリー）
    # ------------------------------------------------------------------
    st.divider()
    st.markdown("**評価項目ごとの平均（5点満点）**")
    avg_cols = score_cols + [c for c in ["他者平均"] if c in matrix.columns]
    by_item = matrix.groupby("項目", sort=False)[avg_cols].mean().round(2).reset_index()
    if "差（本人−他者）" in matrix.columns and self_labels:
        by_item["差（本人−他者）"] = (by_item[self_labels].mean(axis=1)
                                 - by_item["他者平均"]).round(2)
    st.dataframe(
        by_item, use_container_width=True, hide_index=True,
        column_config={c: st.column_config.NumberColumn(c, format="%.2f")
                       for c in by_item.columns if c != "項目"},
    )

    if len(score_cols) > 1:
        long = by_item.melt(id_vars="項目", value_vars=score_cols,
                            var_name="評価者", value_name="平均")
        fig = px.bar(long, x="項目", y="平均", color="評価者", barmode="group",
                     title="評価項目ごとの平均（評価者別）")
        fig.update_yaxes(range=[0, 5])
        fig.update_layout(height=380, margin=dict(t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

        if "差（本人−他者）" in by_item.columns and not by_item["差（本人−他者）"].isna().all():
            gaps = by_item.reindex(by_item["差（本人−他者）"].abs().sort_values(ascending=False).index)
            top_gap = gaps.iloc[0]
            direction = "高く" if top_gap["差（本人−他者）"] > 0 else "低く"
            st.info(f"自己評価と他者評価の差が最も大きい項目: **{top_gap['項目']}**"
                    f"（本人が {abs(top_gap['差（本人−他者）']):.2f} ポイント{direction}評価）")

    return {"matrix": matrix, "by_item": by_item, "score_cols": score_cols,
            "extra_cols": extra_cols, "self_labels": self_labels}


def employee_summary(evals: list[dict]) -> pd.DataFrame:
    """従業員ごとに集約したサマリーを作る（最新評価を代表値とする）。"""
    rows = []
    for name, group in pd.DataFrame(evals).groupby("employee", sort=False):
        group = group.sort_values("created_at", ascending=False)
        latest = group.iloc[0]
        rows.append({
            "対象者": name,
            "役割": latest["role"],
            "評価回数": len(group),
            "最新評価日": str(latest["created_at"])[:10],
            "最新得点": f"{latest['total_score']} / {latest['max_total']}" if latest["max_total"]
                        else str(latest["total_score"]),
            "達成率": round(float(latest["rate"]), 1),
            "ランク": latest["rank"],
            "平均達成率": round(float(group["rate"].mean()), 1),
            "評価者": latest["evaluator"] or "—",
        })
    return pd.DataFrame(rows)


# =====================================================================
# 従業員一覧
# =====================================================================
if menu == "従業員一覧":
    st.header("従業員一覧")

    evals = core.load_evaluations()
    if not evals:
        st.info("まだ評価データがありません。入力アプリの「評価入力」から登録してください。")
        st.stop()

    # --- 絞り込み ---
    f1, f2, f3 = st.columns([2, 3, 3])
    with f1:
        role_filter = st.multiselect("役割で絞り込み", ALL_ROLES, default=[])
    with f2:
        periods = sorted({e["period"] for e in evals})
        period_filter = st.multiselect("評価期間で絞り込み", periods, default=[])
    with f3:
        keyword = st.text_input("対象者名で検索", placeholder="氏名の一部")

    filtered = [
        e for e in evals
        if (not role_filter or e["role"] in role_filter)
        and (not period_filter or e["period"] in period_filter)
        and (not keyword or keyword.strip() in e["employee"])
    ]
    if not filtered:
        st.warning("条件に一致する評価がありません。")
        st.stop()

    summary = employee_summary(filtered)

    # --- 全体サマリー ---
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("対象者数", f"{len(summary)} 名")
    m2.metric("評価件数", f"{len(filtered)} 件")
    m3.metric("平均達成率", f"{summary['達成率'].mean():.1f} %")
    top = summary.sort_values("達成率", ascending=False).iloc[0]
    m4.metric("最高達成率", f"{top['達成率']:.1f} %", delta=str(top["対象者"]), delta_color="off")

    st.divider()

    # --- 一覧表（行をタップすると詳細画面へ切り替わる）---
    st.caption("行をタップすると、その従業員の詳細画面に切り替わります。")
    sorted_summary = summary.sort_values("達成率", ascending=False).reset_index(drop=True)
    event = st.dataframe(
        sorted_summary,
        use_container_width=True,
        hide_index=True,
        key="emp_table",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "達成率": st.column_config.ProgressColumn(
                "達成率", format="%.1f %%", min_value=0, max_value=100,
            ),
            "平均達成率": st.column_config.NumberColumn("平均達成率", format="%.1f %%"),
        },
    )

    # 行が選ばれたら詳細画面へ遷移する
    selected_rows = event.selection["rows"] if event and event.selection else []
    if selected_rows:
        st.session_state["detail_employee"] = sorted_summary.iloc[selected_rows[0]]["対象者"]
        st.rerun()

    # --- グラフ ---
    g1, g2 = st.columns([3, 2])
    with g1:
        chart_df = summary.sort_values("達成率", ascending=True)
        fig = px.bar(chart_df, x="達成率", y="対象者", orientation="h", text="ランク",
                     color="役割", labels={"達成率": "達成率 (%)", "対象者": ""},
                     title="従業員別の達成率（最新評価）")
        fig.update_layout(height=max(260, 34 * len(chart_df) + 120), margin=dict(t=40, b=20))
        fig.update_xaxes(range=[0, 100])
        st.plotly_chart(fig, use_container_width=True)
    with g2:
        rank_counts = summary["ランク"].value_counts().reindex(
            [r[0] for r in core.RANK_TABLE], fill_value=0
        ).reset_index()
        rank_counts.columns = ["ランク", "人数"]
        fig2 = px.bar(rank_counts, x="ランク", y="人数", text="人数", title="ランク分布")
        fig2.update_layout(height=300, margin=dict(t=40, b=20))
        st.plotly_chart(fig2, use_container_width=True)

    st.info("上の表から従業員をタップすると、その人の詳細画面（設問ごとの回答比較・PDF出力）が開きます。")


# =====================================================================
# 従業員の詳細（別画面）
# =====================================================================
elif menu == "__detail__":
    target_name = st.session_state.get("detail_employee")

    if st.button("← 従業員一覧に戻る", key="back_to_list"):
        st.session_state.pop("detail_employee", None)
        st.session_state.pop("emp_table", None)      # 表の選択状態もリセットする
        st.rerun()

    all_evals = core.load_evaluations()
    history = [e for e in all_evals if e["employee"] == target_name]
    if not history:
        st.warning(f"「{target_name}」の評価が見つかりません。")
        st.stop()

    latest = history[0]
    st.header(f"👤 {target_name}")
    h1, h2, h3, h4 = st.columns(4)
    h1.metric("役割", latest["role"])
    h2.metric("評価件数", f"{len(history)} 件")
    h3.metric("最新達成率", f"{latest['rate']:.1f} %")
    h4.metric("最新ランク", latest["rank"])

    # --- 設問別の比較（自己評価 vs 他者評価）: この画面のメイン ---
    st.subheader("設問ごとの回答（評価者を横並びで比較）")
    cmp_periods = ["すべての期間"] + sorted({e["period"] for e in history})
    default_period = history[0]["period"]
    cmp_period = st.selectbox(
        "比較する評価期間", cmp_periods,
        index=cmp_periods.index(default_period) if default_period in cmp_periods else 0,
        help="同じ期間の評価どうしを比べると、自己評価と他者評価の差が分かります。",
    )
    cmp_evals = history if cmp_period == "すべての期間" else \
        [e for e in history if e["period"] == cmp_period]
    st.caption(f"比較対象: {len(cmp_evals)} 件の評価")
    comparison = render_answer_comparison(target_name, cmp_evals)

    # --- PDF出力 ---
    st.divider()
    st.subheader("📄 PDFで出力")
    if comparison is None:
        st.caption("設問ごとの回答が記録されていないため、PDFを作成できません。")
    else:
        try:
            pdf_bytes = pdf_export.build_employee_report(
                employee=target_name,
                meta={"role": latest["role"], "period": cmp_period, "count": len(cmp_evals)},
                matrix=comparison["matrix"],
                by_item=comparison["by_item"],
                history=cmp_evals,
                score_cols=comparison["score_cols"],
                extra_cols=comparison["extra_cols"],
                self_labels=comparison["self_labels"],
            )
            st.caption("評価履歴・評価項目ごとの平均・設問ごとの回答比較を1つのPDFにまとめます（A4横）。")
            st.download_button(
                "PDFをダウンロード", pdf_bytes,
                file_name=f"人事評価レポート_{target_name}_{datetime.now():%Y%m%d}.pdf",
                mime="application/pdf", type="primary", key="dl_pdf",
            )
        except Exception as e:      # PDF生成の失敗で画面全体を壊さない
            st.error(f"PDFの作成に失敗しました: {e}")

    st.divider()

    history_df = pd.DataFrame([{
        "評価日": e["created_at"][:16],
        "役割": e["role"],
        "評価期間": e["period"],
        "評価者": e["evaluator"] or "—",
        "得点": f"{e['total_score']} / {e['max_total']}" if e["max_total"] else str(e["total_score"]),
        "達成率": round(e["rate"], 1),
        "ランク": e["rank"],
    } for e in history])
    st.subheader("評価履歴")
    st.dataframe(history_df, use_container_width=True, hide_index=True)

    if len(history) > 1:
        trend = pd.DataFrame([{"評価日": e["created_at"][:10], "達成率": round(e["rate"], 1)}
                              for e in reversed(history)])
        fig3 = px.line(trend, x="評価日", y="達成率", markers=True, text="達成率",
                       title="達成率の推移")
        fig3.update_traces(textposition="top center")
        fig3.update_yaxes(range=[0, 100])
        fig3.update_layout(height=280, margin=dict(t=40, b=20))
        st.plotly_chart(fig3, use_container_width=True)

    # --- 1件の評価を掘り下げる ---
    st.divider()
    st.subheader("評価の詳細（1件ずつ）")
    labels = [f"{e['created_at'][:16]}　{e['role']}　{e['total_score']}点（{e['rank']}）" for e in history]
    idx = st.selectbox("表示する評価", range(len(labels)), format_func=lambda i: labels[i])
    ev = history[idx]
    detail = core.load_evaluation_detail(ev["id"])

    d1, d2, d3 = st.columns(3)
    d1.metric("合計点", f"{ev['total_score']} / {ev['max_total']}" if ev["max_total"] else str(ev["total_score"]))
    d2.metric("達成率", f"{ev['rate']:.1f} %")
    d3.metric("ランク", ev["rank"])

    # 項目別得点
    if detail["scores"]:
        score_df = pd.DataFrame([{"#": s["item_num"], "項目": s["item_name"],
                                  "得点": s["score"], "コメント": s["comment"] or ""}
                                 for s in detail["scores"]])
        col_s1, col_s2 = st.columns([3, 4])
        with col_s1:
            st.dataframe(score_df, use_container_width=True, hide_index=True)
        with col_s2:
            fig4 = px.bar(score_df.iloc[::-1], x="得点", y="項目", orientation="h",
                          text="得点", title="項目別の得点")
            fig4.update_layout(height=max(260, 30 * len(score_df) + 100), margin=dict(t=40, b=20))
            st.plotly_chart(fig4, use_container_width=True)

    # 設問別の回答
    if detail["answers"]:
        st.subheader("設問別の回答")
        by_item: dict[str, list] = {}
        for a in detail["answers"]:
            by_item.setdefault(a["item_name"], []).append(a)
        for item_name, rows_a in by_item.items():
            valid = [r["answer"] for r in rows_a if r["answer"] is not None]
            avg_label = f"平均 {sum(valid) / len(valid):.2f}" if valid else "回答なし"
            with st.expander(f"{item_name}（{len(rows_a)}問・{avg_label}）"):
                st.dataframe(
                    pd.DataFrame([{"#": r["qnum"], "設問": r["question_text"],
                                   "評価": r["answer"] if r["answer"] is not None else "—",
                                   "意味": core.SCALE_TEXT.get(r["answer"], "わからない / 該当なし")}
                                  for r in rows_a]),
                    use_container_width=True, hide_index=True,
                )
    else:
        st.caption("この評価には設問ごとの回答が記録されていません（設問機能の導入前に登録されたデータです）。")

    # 総合設問
    if detail["overall"]:
        st.subheader("総合設問")
        for o in detail["overall"]:
            st.markdown(f"**{o['qnum']}　{o['question_text']}**")
            st.write(o["answer_text"])

    with st.expander("⚠️ この評価を削除する"):
        st.caption("削除すると、項目別得点・設問の回答・総合設問もまとめて消えます。元に戻せません。")
        if st.button("削除する", type="secondary", key=f"del_eval_{ev['id']}"):
            core.delete_evaluation(ev["id"])
            st.success("削除しました。")
            st.rerun()


# =====================================================================
# 評価の履歴（全件）
# =====================================================================
elif menu == "評価の履歴":
    st.header("評価の履歴（全件）")

    evals = core.load_evaluations()
    if not evals:
        st.info("まだ評価データがありません。入力アプリの「評価入力」から登録してください。")
        st.stop()

    df = pd.DataFrame([{
        "評価日": e["created_at"][:16],
        "対象者": e["employee"],
        "役割": e["role"],
        "評価期間": e["period"],
        "評価者": e["evaluator"] or "—",
        "得点": e["total_score"],
        "満点": e["max_total"] or "—",
        "達成率": round(e["rate"], 1),
        "ランク": e["rank"],
    } for e in evals])
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.download_button(
        "CSVでダウンロード",
        df.to_csv(index=False).encode("utf-8-sig"),
        file_name="評価履歴.csv",
        mime="text/csv",
    )

    st.divider()
    st.subheader("役割別の平均達成率")
    by_role = df.groupby("役割", as_index=False)["達成率"].mean().round(1)
    fig = px.bar(by_role, x="役割", y="達成率", text="達成率")
    fig.update_yaxes(range=[0, 100])
    fig.update_layout(height=320, margin=dict(t=30, b=20))
    st.plotly_chart(fig, use_container_width=True)


# =====================================================================
# 評価対象の設定
# =====================================================================
elif menu == "評価対象の設定":
    st.header("評価対象の設定")
    st.caption("評価者ごとに「誰を評価するか」を設定します。"
               "ここで設定すると、入力アプリで評価者を選んだとき対象者が自動的に絞り込まれます。")

    all_employees = core.get_nippou_workers()
    current_assignments = core.get_all_evaluator_assignments()

    # 評価者を選択
    evaluator_to_edit = st.selectbox(
        "評価者を選択", all_employees, key="et_evaluator",
    )

    if evaluator_to_edit:
        current_targets = current_assignments.get(evaluator_to_edit, [])
        other_employees = [e for e in all_employees if e != evaluator_to_edit]

        st.markdown(f"**{evaluator_to_edit}** が評価する対象者を選んでください。")
        selected_targets = st.multiselect(
            "評価対象者",
            other_employees,
            default=[t for t in current_targets if t in other_employees],
            key="et_targets",
        )

        if st.button("保存", type="primary", use_container_width=True, key="et_save"):
            core.save_evaluator_targets(evaluator_to_edit, selected_targets)
            st.success(f"**{evaluator_to_edit}** の評価対象を {len(selected_targets)} 名に設定しました。")
            st.rerun()

    # 現在の割り当て一覧
    st.divider()
    st.subheader("現在の割り当て一覧")
    if current_assignments:
        for ev_name, targets in sorted(current_assignments.items()):
            st.markdown(f"- **{ev_name}** → {', '.join(targets)}")
    else:
        st.info("まだ割り当てが設定されていません。上のフォームから設定してください。"
                "未設定の評価者は、従来の職種区分ベースで対象者が表示されます。")


# =====================================================================
# 評価基準の閲覧
# =====================================================================
elif menu == "評価基準の閲覧":
    views.render_criteria_page(ALL_ROLES)


# =====================================================================
# 評価基準の編集
# =====================================================================
elif menu == "評価基準の編集":
    st.header("評価基準の編集")
    st.caption("項目名・内容・配点を変更して「保存」を押してください。行の追加・削除もできます。")

    edit_section = st.selectbox("編集するセクション", ["共通"] + ALL_ROLES)
    items = core.load_items(edit_section)

    # --- 既存項目の編集 ---
    if items:
        st.subheader(f"「{edit_section}」の評価項目")

        edited_items = []
        delete_ids = []

        for i, item in enumerate(items):
            with st.container(border=True):
                cols = st.columns([0.5, 2, 4, 1, 1.5, 0.5])
                with cols[0]:
                    new_num = st.number_input("番号", value=item["num"], key=f"num_{item['id']}",
                                              label_visibility="collapsed")
                with cols[1]:
                    new_name = st.text_input("項目名", value=item["name"], key=f"name_{item['id']}")
                with cols[2]:
                    new_desc = st.text_input("評価内容", value=item["description"], key=f"desc_{item['id']}")
                with cols[3]:
                    new_score = st.number_input("配点", value=item["max_score"], min_value=0, max_value=100,
                                                key=f"score_{item['id']}")
                with cols[4]:
                    new_cg = st.text_input("択一グループ", value=item["choice_group"] or "",
                                           key=f"cg_{item['id']}",
                                           help="同じグループ名の項目は択一になります（空欄＝通常項目）")
                with cols[5]:
                    if st.button("削除", key=f"del_{item['id']}", type="secondary"):
                        delete_ids.append(item["id"])

                edited_items.append({
                    "id": item["id"], "num": new_num, "name": new_name,
                    "description": new_desc, "max_score": new_score,
                    "choice_group": new_cg.strip() or None, "sort_order": i,
                })

        # 合計点の表示
        active_total = sum(it["max_score"] for it in edited_items if it["id"] not in delete_ids)
        if edit_section == "共通":
            st.info(f"共通 小計: **{active_total}点**")
        else:
            common_total = sum(i["max_score"] for i in core.load_common_items())
            st.info(f"固有 小計: **{active_total}点** ／ "
                    f"合計（共通{common_total} + 固有{active_total}）: **{common_total + active_total}点**")

        if delete_ids:
            with core.eval_conn() as conn:
                with conn.cursor() as cur:
                    for did in delete_ids:
                        cur.execute("DELETE FROM eval.eval_items WHERE id = %s", (did,))
            st.success(f"{len(delete_ids)} 件削除しました。")
            st.rerun()

        if st.button("変更を保存", type="primary", use_container_width=True):
            with core.eval_conn() as conn:
                with conn.cursor() as cur:
                    for it in edited_items:
                        cur.execute(
                            "UPDATE eval.eval_items SET num=%s, name=%s, description=%s, max_score=%s, "
                            "choice_group=%s, sort_order=%s WHERE id=%s",
                            (it["num"], it["name"], it["description"], it["max_score"],
                             it["choice_group"], it["sort_order"], it["id"]),
                        )
            st.success("保存しました。")
            st.rerun()
    else:
        st.info(f"「{edit_section}」にはまだ項目がありません。下のフォームから追加してください。")

    # --- 設問の編集 ---
    if items:
        st.divider()
        st.subheader("設問（アンケート）の編集")
        st.caption("評価項目を選び、その項目にぶら下がる設問と判断基準を編集します。"
                   "表の最終行に入力すると設問を追加、行を選択して Delete キーで削除できます。")

        target = st.selectbox(
            "設問を編集する項目", items,
            format_func=lambda i: f"{i['num']}. {i['name']}（配点{i['max_score']}）",
            key="q_target",
        )
        existing = core.load_questions(target["id"])
        st.caption(f"現在 {len(existing)} 問。得点は「設問平均 ÷ 5 × 配点」で換算されます。")

        q_table = pd.DataFrame(
            [{"番号": q["qnum"], "設問": q["text"]} for q in existing]
            or [{"番号": "", "設問": ""}]
        )
        edited_qs = st.data_editor(
            q_table,
            key=f"qedit_{target['id']}",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "番号": st.column_config.TextColumn("番号", width="small", help="例: 1-1"),
                "設問": st.column_config.TextColumn("設問", width="large"),
            },
        )

        st.markdown("**判断基準（5 / 3 / 1 の目安）**")
        a5 = st.text_area("5 期待を大きく上回る", value=target["anchor_5"], key=f"a5_{target['id']}", height=68)
        a3 = st.text_area("3 期待通り（標準）", value=target["anchor_3"], key=f"a3_{target['id']}", height=68)
        a1 = st.text_area("1 大きく不足", value=target["anchor_1"], key=f"a1_{target['id']}", height=68)
        ft = st.text_area("自由記述欄の設問文", value=target["free_text"], key=f"ft_{target['id']}", height=68)

        if st.button("設問と判断基準を保存", type="primary", use_container_width=True, key="save_questions"):
            new_rows = [
                (str(r["番号"] or "").strip(), str(r["設問"] or "").strip())
                for _, r in edited_qs.iterrows()
            ]
            new_rows = [(qnum, text) for qnum, text in new_rows if text]
            with core.eval_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM eval.survey_questions WHERE item_id = %s", (target["id"],))
                    for order, (qnum, text) in enumerate(new_rows):
                        cur.execute(
                            "INSERT INTO eval.survey_questions (item_id, qnum, text, sort_order) VALUES (%s, %s, %s, %s)",
                            (target["id"], qnum, text, order),
                        )
                    cur.execute(
                        "UPDATE eval.eval_items SET anchor_5 = %s, anchor_3 = %s, anchor_1 = %s, free_text = %s WHERE id = %s",
                        (a5, a3, a1, ft, target["id"]),
                    )
            st.success(f"「{target['name']}」の設問を保存しました（{len(new_rows)}問）。")
            st.rerun()

    # --- 新規項目の追加 ---
    st.divider()
    st.subheader("項目を追加")

    with st.form("add_item_form"):
        ac1, ac2 = st.columns([1, 3])
        with ac1:
            add_num = st.number_input("番号", value=(items[-1]["num"] + 1 if items else 1), min_value=1)
        with ac2:
            add_name = st.text_input("項目名", placeholder="例: 安全管理")
        add_desc = st.text_input("評価内容", placeholder="例: KY活動の実施、保護具着用")
        ac3, ac4 = st.columns(2)
        with ac3:
            add_score = st.number_input("配点", value=10, min_value=0, max_value=100)
        with ac4:
            add_cg = st.text_input("択一グループ（任意）", placeholder="空欄＝通常項目")

        submitted = st.form_submit_button("追加", type="primary", use_container_width=True)
        if submitted:
            if not add_name.strip():
                st.error("項目名を入力してください。")
            else:
                max_order = items[-1]["sort_order"] + 1 if items else 0
                with core.eval_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO eval.eval_items (section, num, name, description, max_score, choice_group, sort_order) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                            (edit_section, add_num, add_name.strip(), add_desc.strip(), add_score,
                             add_cg.strip() or None, max_order),
                        )
                st.success(f"「{add_name}」を追加しました。")
                st.rerun()

    # --- 新しい役割の追加 ---
    if edit_section == "共通":
        st.divider()
        st.subheader("新しい役割を追加")
        st.caption("事務・電工・役員以外の役割が必要な場合はここから追加できます。")
        with st.form("add_role_form"):
            new_role = st.text_input("役割名", placeholder="例: パート・アルバイト")
            role_submitted = st.form_submit_button("役割を追加")
            if role_submitted:
                if not new_role.strip():
                    st.error("役割名を入力してください。")
                elif new_role.strip() in ALL_ROLES:
                    st.error("その役割は既に存在します。")
                else:
                    with core.eval_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO eval.eval_items (section, num, name, description, max_score, sort_order) "
                                "VALUES (%s, 5, '（項目名を設定）', '（評価内容を設定）', 10, 0)",
                                (new_role.strip(),),
                            )
                    st.success(f"役割「{new_role}」を追加しました。「評価基準の編集」で項目を設定してください。")
                    st.rerun()

    # --- GitHubに反映（devブランチのみ表示） ---
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
    import git_sync  # noqa: E402
    if git_sync.is_dev():
        st.divider()
        st.subheader("🔄 GitHubに反映（dev）")
        st.caption("評価項目と設問をJSONに書き出してGitHubにプッシュします。")
        if st.button("GitHubに反映する", type="primary", use_container_width=True, key="push_github"):
            with st.spinner("GitHubに反映中..."):
                core.export_items_to_json()
                core.export_survey_to_json()
                ok, msg = git_sync.push_changes(
                    "evaluation",
                    ["evaluation/eval_items.json", "evaluation/survey_questions.json"],
                )
            if ok:
                st.success(msg)
            else:
                st.error(msg)
