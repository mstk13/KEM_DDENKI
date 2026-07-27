"""入力アプリ・管理アプリで共通のStreamlit表示部品。"""
from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import core


def disable_browser_translation():
    """ブラウザの自動翻訳がページを書き換えるのを防ぐ。

    Chrome/Edge が日本語ページを翻訳すると設問文が別の語に置き換わり
    （例:「着替え」→「交換」、「行っているか」→「行ってください」）、
    評価者が誤った文面を読むことになる。Streamlit(React) の再描画とも
    衝突して removeChild エラーの原因にもなる。
    親ドキュメントに translate=no / notranslate を設定して抑止する。
    """
    components.html(
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


def render_criteria_table(items: list[dict], show_questions: bool):
    """評価項目の表と、その設問・判断基準を表示する。"""
    counts = core.count_questions([i["id"] for i in items])
    rows = []
    for i in items:
        label = i["name"] + (" ※択一" if i["choice_group"] else "")
        rows.append({"#": i["num"], "項目": label, "評価内容": i["description"],
                     "配点": i["max_score"], "設問数": counts.get(i["id"], 0)})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if not show_questions:
        return
    for i in items:
        questions = core.load_questions(i["id"])
        anchors = [(5, i["anchor_5"]), (3, i["anchor_3"]), (1, i["anchor_1"])]
        if not questions and not any(t for _, t in anchors):
            continue
        with st.expander(f"{i['num']}. {i['name']} の設問（{len(questions)}問）"):
            if questions:
                st.dataframe(
                    pd.DataFrame([{"#": q["qnum"], "設問": q["text"]} for q in questions]),
                    use_container_width=True, hide_index=True,
                )
            if any(t for _, t in anchors):
                st.markdown("**判断基準**")
                for level, text in anchors:
                    if text:
                        st.markdown(f"- **{level}** … {text}")
            if i["free_text"]:
                st.caption(f"自由記述: {i['free_text']}")


def render_criteria_page(all_roles: list[str]):
    """「評価基準の閲覧」画面。"""
    st.header("評価基準一覧")

    st.subheader("評価ランク")
    rank_df = pd.DataFrame(core.RANK_TABLE, columns=["ランク", "下限", "上限", "意味"])
    rank_df["達成率"] = rank_df["下限"].astype(str) + " 〜 " + rank_df["上限"].astype(str) + " %"
    st.dataframe(rank_df[["ランク", "達成率", "意味"]], use_container_width=True, hide_index=True)

    st.subheader("5段階の評価尺度")
    st.dataframe(
        pd.DataFrame([{"評価": v, "意味": core.SCALE_TEXT[v]} for v in reversed(core.SCALE_VALUES)]),
        use_container_width=True, hide_index=True,
    )

    show_questions = st.toggle("設問も表示する", value=True)

    common_items = core.load_common_items()
    common_total = sum(i["max_score"] for i in common_items)
    st.subheader(f"共通評価項目（全役割共通）— {common_total}点")
    render_criteria_table(common_items, show_questions)

    for role_name in all_roles:
        items = core.load_role_items(role_name)
        # 択一は片方のみ加算
        role_total = 0
        seen_cg = set()
        for i in items:
            if i["choice_group"]:
                if i["choice_group"] not in seen_cg:
                    role_total += i["max_score"]
                    seen_cg.add(i["choice_group"])
            else:
                role_total += i["max_score"]

        grand = common_total + role_total
        warn = "　⚠️ 満点が100点ではありません" if grand != 100 else ""
        st.subheader(f"{role_name} 固有の評価項目 — {role_total}点（合計: {grand}点）{warn}")
        render_criteria_table(items, show_questions)

    st.divider()
    st.subheader("総合設問（自由記述）")
    overall = core.get_overall_questions()
    if overall:
        st.dataframe(
            pd.DataFrame([{"#": q["qnum"], "設問": q["text"],
                           "回答者": "本人" if q.get("by_self") else "評価者"} for q in overall]),
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("総合設問は登録されていません。")
