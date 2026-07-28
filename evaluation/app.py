"""人事評価 — 入力アプリ

評価者がアンケートに回答して評価を登録するための画面のみを持つ。
集計・閲覧・評価基準の編集は管理アプリ（admin_app.py）側。

起動: streamlit run app.py --server.port 8504
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st

# core / views はこのファイルと同じフォルダにある（起動ディレクトリに依存しないようにする）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import core          # noqa: E402
import views         # noqa: E402

st.set_page_config(page_title="人事評価 入力", page_icon="📝", layout="wide")
# 設問文がブラウザに翻訳され別の意味に書き換わるのを防ぐ（title より先に実行する）
views.disable_browser_translation()
views.compact_score_buttons()
st.title("📝 人事評価 入力")

ALL_ROLES = core.get_all_roles() or ["事務方", "現場方", "役員"]

st.sidebar.caption("集計・従業員別の一覧は **管理アプリ** で確認できます。")

# =====================================================================
# 評価入力
# =====================================================================
st.header("評価入力")

nippou_workers = core.get_nippou_workers()
col1, col2, col3 = st.columns(3)
with col1:
    if nippou_workers:
        employee = st.selectbox("対象者", ["（手入力）"] + nippou_workers)
        if employee == "（手入力）":
            employee = st.text_input("対象者名を入力")
    else:
        employee = st.text_input("対象者名")
with col2:
    role = st.selectbox("役割", ALL_ROLES)
with col3:
    today = date.today()
    fy_start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    fy_end = date(fy_start.year + 1, 3, 31)
    period = st.text_input("評価期間", f"{fy_start} 〜 {fy_end}")
    # 評価者も対象者と同じくプルダウン選択。候補に無ければ手入力する。
    evaluator_options = core.get_evaluator_options()
    if evaluator_options:
        evaluator = st.selectbox("評価者", ["（手入力）"] + evaluator_options)
        if evaluator == "（手入力）":
            evaluator = st.text_input("評価者名を入力")
    else:
        evaluator = st.text_input("評価者名")

if not employee:
    st.info("対象者を選択または入力してください。")
    st.stop()

# 勤怠データ
st.subheader("📋 勤怠データ（作業日報から自動取得）")
stats = core.get_attendance_stats(employee, str(fy_start), str(fy_end))
if stats:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("出勤日数", f"{stats['work_days']} 日")
    c2.metric("総作業時間", f"{stats['total_hours']} h")
    c3.metric("総残業時間", f"{stats['total_overtime']} h")
    c4.metric("1日平均作業時間", f"{stats['avg_hours_per_day']} h")
    if stats["monthly"]:
        st.plotly_chart(
            views.monthly_attendance_chart(stats["monthly"], fy_start),
            use_container_width=True,
        )
else:
    st.warning("作業日報にこの対象者のデータがありません。手動で評価してください。")

st.divider()

common_items = core.load_common_items()
role_items = core.load_role_items(role)

# 択一選択
choice_groups = set(i["choice_group"] for i in role_items if i["choice_group"])
choice_selections = {}
for cg in choice_groups:
    cg_items = [i for i in role_items if i["choice_group"] == cg]
    choice_selections[cg] = st.radio(
        "以下の項目はどちらか一方を選択",
        [i["name"] for i in cg_items],
        horizontal=True,
    )

st.markdown(core.SCALE_BUTTON_CSS, unsafe_allow_html=True)
st.info(
    "各設問の **1〜5 のボタン** を押して回答してください。選んだボタンがグレー、"
    "選んでいないボタンは白になります。\n\n"
    f"{core.SCALE_LEGEND}\n\n"
    "判断に必要な事実がない設問は、選択中のボタンをもう一度押して解除してください"
    "（＝わからない / 該当なし）。集計は管理アプリ側で行います。"
)


# ------------------------------------------------------------------
# 評価項目1つ分のアンケートを描画し、回答・コメントを返す
# （得点の算出・表示はこの画面では行わない。保存時に core 側で換算する）
# ------------------------------------------------------------------
def render_item(item: dict, key_prefix: str, hint: str = "", fallback_default: int = 0) -> dict:
    questions = core.load_questions(item["id"])
    key = f"{key_prefix}_{item['id']}"

    with st.container(border=True):
        st.markdown(f"**{item['num']}. {item['name']}** — 配点 {item['max_score']}点")
        st.caption(item["description"])
        if hint:
            st.caption(f"📋 {hint}")

        anchors = [(5, item["anchor_5"]), (3, item["anchor_3"]), (1, item["anchor_1"])]
        if any(text for _, text in anchors):
            with st.expander("判断基準（5 / 3 / 1 の目安）"):
                for level, text in anchors:
                    if text:
                        st.markdown(f"- **{level}** … {text}")

        answers: list[int | None] = []
        answer_rows: list[dict] = []

        if questions:
            for q in questions:
                label = f"{q['qnum']}　{q['text']}" if q["qnum"] else q["text"]
                # 設問側を広くとる（文章は複数行に折り返してよい）。
                # スコア列は 1〜5 が横一列に収まる幅を確保し、右端に寄せる。
                col_q, col_a = st.columns([4, 1.2], vertical_alignment="center")
                with col_q:
                    st.markdown(label)
                with col_a:
                    value = st.segmented_control(
                        "評価",
                        core.SCALE_VALUES,
                        default=core.DEFAULT_ANSWER_VALUE,
                        format_func=lambda v: str(v),
                        key=f"q_{key}_{q['id']}",
                        label_visibility="collapsed",
                        help="もう一度押すと選択を解除できます（＝わからない / 該当なし）",
                    )
                answers.append(value)
                answer_rows.append({
                    "item_id": item["id"], "item_name": item["name"],
                    "qnum": q["qnum"], "question_text": q["text"], "answer": value,
                })

            score = None    # 得点は保存時に算出する（入力画面では扱わない）
            if all(a is None for a in answers):
                st.warning("この項目はすべて未選択です。")
        else:
            st.caption("この項目にはまだ設問がありません。評価を直接入力してください。")
            score = st.number_input(
                f"評価（0〜{item['max_score']}）", 0, item["max_score"], fallback_default,
                key=f"man_{key}",
            )

        comment = st.text_area(
            "自由記述",
            key=f"cmt_{key}",
            placeholder=item["free_text"] or "コメント（任意）",
            height=68,
        )

    return {"item": item, "score": score, "comment": comment, "answers": answer_rows}


# 共通評価
st.subheader("第1部　共通評価項目")
results = []
for item in common_items:
    hint = ""
    fallback = 0
    if item["name"] == "勤怠・規律" and stats:
        hint = (f"作業日報の実績: 出勤 {stats['work_days']}日 / 総作業 {stats['total_hours']}h "
                f"/ 残業 {stats['total_overtime']}h")
        fallback = min(item["max_score"], round(stats["work_days"] / 20))
    results.append(render_item(item, "common", hint=hint, fallback_default=fallback))

# 役割固有
st.subheader(f"第2部　{role} 固有の評価項目")
for item in role_items:
    if item["choice_group"]:
        if choice_selections.get(item["choice_group"]) != item["name"]:
            continue
    results.append(render_item(item, "role"))

# 総合設問（自由記述）
overall_questions = core.get_overall_questions()
overall_answers = []
if overall_questions:
    st.subheader("第3部　総合設問")
    for q in overall_questions:
        label = f"{q['qnum']}　{q['text']}" + ("（本人記入欄）" if q.get("by_self") else "")
        text = st.text_area(label, key=f"ov_{q['qnum']}", height=80)
        overall_answers.append({"qnum": q["qnum"], "question_text": q["text"], "answer_text": text})

st.divider()

answered = sum(1 for r in results for a in r["answers"] if a["answer"] is not None)
total_questions = sum(len(r["answers"]) for r in results)
if total_questions:
    st.caption(f"回答済み {answered} / {total_questions} 問")

if st.button("評価を保存", type="primary", use_container_width=True):
    if not employee.strip():
        st.error("対象者名を入力してください。")
    else:
        core.save_evaluation(
            employee.strip(), role, period, evaluator,
            choice_selections, results, overall_answers,
        )
        st.success(
            f"{employee} さんの評価を保存しました。"
            "集計結果は管理アプリの「従業員一覧」から確認できます。"
        )
        st.balloons()
