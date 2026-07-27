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


def compact_score_buttons():
    """設問のスコア選択（1〜5）を右端に寄せ、必ず横一列に並べる。

    st.segmented_control は既定で左寄せのため、列幅より狭いぶんが
    右側の空白として残る。また列が狭いとボタンが折り返して2段になる。
    右寄せ＋折り返し禁止で、1〜5を常に横一列に保つ。
    設問文は複数行に折り返してよい。
    """
    st.markdown(
        """
        <style>
        /* スコア選択（1〜5）: 右端に寄せ、折り返さず横一列に保つ */
        div[data-testid="stButtonGroup"] {
            justify-content: flex-end;
            flex-wrap: nowrap;
        }
        div[data-testid="stButtonGroup"] > div {
            flex-wrap: nowrap;
            gap: 0.15rem;
        }
        /* ボタンが縮んで折り返さないようにする */
        div[data-testid="stButtonGroup"] button { flex: 0 0 auto; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# グラフの配色（1系列のみなのでカテゴリ1色を使う。凡例は不要でタイトルが系列を示す）
_BAR_COLOR = "#2a78d6"
_INK_SECONDARY = "#52514e"
_GRID = "#e6e5e1"


def monthly_attendance_chart(monthly: list[dict], fy_start):
    """月別出勤日数の棒グラフ。

    集計結果には出勤のあった月しか含まれないため、年度の12か月分を
    4月始まりで並べ、出勤の無い月は 0 として表示する。
    月ごとの多寡を隣同士で比べられるようにするのが狙い。
    """
    import plotly.graph_objects as go

    by_month = {m["month"]: m for m in monthly}

    labels, days, hovers = [], [], []
    for i in range(12):
        y = fy_start.year + (fy_start.month - 1 + i) // 12
        mth = (fy_start.month - 1 + i) % 12 + 1
        rec = by_month.get(f"{y:04d}-{mth:02d}")
        labels.append(f"{mth}月")
        d = int(rec["days"]) if rec else 0
        days.append(d)
        hovers.append(
            f"<b>{y}年{mth}月</b><br>出勤 {d} 日"
            + (f"<br>作業 {rec['hours']:.1f} h<br>残業 {rec['overtime']:.1f} h" if rec else "")
        )

    fig = go.Figure(
        go.Bar(
            x=labels, y=days,
            marker=dict(color=_BAR_COLOR, cornerradius=4),
            text=[str(d) if d else "" for d in days],   # 0 の月は数字を出さない
            textposition="outside",
            textfont=dict(color=_INK_SECONDARY, size=12),
            hovertext=hovers, hoverinfo="text",
            width=0.62,
        )
    )
    top = max(days) if days else 0
    fig.update_layout(
        title=dict(text="月別出勤日数", font=dict(size=15)),
        height=300,
        margin=dict(t=44, b=44, l=48, r=16),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        bargap=0.25, showlegend=False,
        xaxis=dict(
            title=None, type="category", automargin=True,
            tickfont=dict(color=_INK_SECONDARY, size=12),
            showgrid=False, showline=True, linecolor=_GRID, ticks="",
        ),
        yaxis=dict(
            title=None, rangemode="tozero", automargin=True,
            range=[0, max(top * 1.18, 1)],      # ラベルが上端で切れないようにする
            tickfont=dict(color=_INK_SECONDARY, size=11),
            gridcolor=_GRID, zerolinecolor=_GRID,
            dtick=1 if top <= 10 else (2 if top <= 20 else 5),
        ),
    )
    return fig


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
