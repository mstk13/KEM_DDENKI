"""人事評価 — 入力アプリ

評価者がアンケートに回答して評価を登録するための画面のみを持つ。
集計・閲覧・評価基準の編集は管理アプリ（admin_app.py）側。

起動: streamlit run app.py --server.port 8504
"""
from __future__ import annotations

import base64
import json
import os
import sys
from datetime import date
from pathlib import Path

import streamlit as st

# core / views はこのファイルと同じフォルダにある（起動ディレクトリに依存しないようにする）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import core          # noqa: E402
import pdf_export    # noqa: E402
import views         # noqa: E402

st.set_page_config(page_title="人事評価 入力", page_icon="📝", layout="wide")
# 設問文がブラウザに翻訳され別の意味に書き換わるのを防ぐ（title より先に実行する）
views.disable_browser_translation()
views.compact_score_buttons()
st.title("📝 人事評価 入力")

ALL_ROLES = core.get_all_roles() or ["事務", "電工", "役員"]

st.sidebar.caption("集計・従業員別の一覧は **管理アプリ** で確認できます。")

# =====================================================================
# ステップ1: 評価者の選択
# =====================================================================
st.header("評価入力")

today = date.today()
fy_start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
fy_end = date(fy_start.year + 1, 3, 31)

col_ev, col_period = st.columns(2)
with col_ev:
    evaluator_options = core.get_evaluator_options()
    if evaluator_options:
        evaluator = st.selectbox("評価者（あなた）", [""] + evaluator_options,
                                 format_func=lambda x: "選択してください" if x == "" else x)
        if evaluator == "":
            evaluator = ""
    else:
        evaluator = st.text_input("評価者名")
with col_period:
    period = st.text_input("評価期間", f"{fy_start} 〜 {fy_end}")

if not evaluator:
    st.info("評価者を選択してください。")
    st.stop()

# =====================================================================
# ステップ2: 評価対象者の一覧 + PDF / 取り込み
# =====================================================================
target_candidates = core.get_evaluation_targets(evaluator)
if not target_candidates:
    target_candidates = core.get_nippou_workers()

# 対象者が選ばれていない場合 → 一覧を表示
selected_target = st.session_state.get("selected_target")

if selected_target is None:
    st.subheader(f"📋 {evaluator} さんの評価対象者")
    st.caption(f"{len(target_candidates)} 名が対象です。評価する人をクリックしてください。")

    cols_per_row = 3
    for i in range(0, len(target_candidates), cols_per_row):
        cols = st.columns(cols_per_row)
        for j, col in enumerate(cols):
            idx = i + j
            if idx >= len(target_candidates):
                break
            name = target_candidates[idx]
            emp_role = core.get_employee_role(name) or "—"
            is_self = name.strip() == evaluator.strip()
            label = f"👤 {name}（本人）" if is_self else f"👤 {name}"
            with col:
                with st.container(border=True):
                    st.markdown(f"**{label}**")
                    st.caption(f"役割: {emp_role}")
                    if st.button("評価する", key=f"sel_{idx}", use_container_width=True):
                        st.session_state["selected_target"] = name
                        st.rerun()

    # =================================================================
    # アンケートPDFダウンロード
    # =================================================================
    st.divider()
    st.subheader("📄 アンケート用紙（PDF）")
    st.caption("対象者ごとの空白アンケートをPDFでダウンロードできます。印刷して手書きで回答してもらう場合にご利用ください。")

    pdf_target = st.selectbox("PDF出力する対象者", target_candidates, key="pdf_target")
    if pdf_target and st.button("PDFを生成", key="gen_pdf"):
        pdf_role = core.get_employee_role(pdf_target) or ALL_ROLES[0]
        common_items = core.load_common_items()
        role_items = core.load_role_items(pdf_role)
        questions_by_item = {}
        for item in common_items + role_items:
            questions_by_item[item["id"]] = core.load_questions(item["id"])
        overall_questions = core.get_overall_questions()
        pdf_bytes = pdf_export.build_blank_questionnaire(
            evaluator=evaluator,
            employee=pdf_target,
            role=pdf_role,
            period=period,
            common_items=common_items,
            role_items=role_items,
            questions_by_item=questions_by_item,
            overall_questions=overall_questions,
        )
        st.download_button(
            "📥 PDFをダウンロード",
            pdf_bytes,
            file_name=f"アンケート_{pdf_target}_{evaluator}.pdf",
            mime="application/pdf",
            key="dl_pdf",
        )

    # =================================================================
    # 回答の取り込み（画像 / PDF アップロード → Claude API で読み取り）
    # =================================================================
    st.divider()
    st.subheader("📤 回答の取り込み")
    st.caption(
        "手書き回答をスキャン／撮影した画像やPDFをアップロードすると、"
        "AIが回答内容を読み取り、対象者を識別してデータベースに保存します。"
    )

    uploaded = st.file_uploader(
        "回答画像またはPDFをアップロード",
        type=["png", "jpg", "jpeg", "pdf"],
        accept_multiple_files=True,
        key="upload_answers",
    )

    if uploaded and st.button("回答を読み取って保存", type="primary", key="import_btn"):
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            st.error("ANTHROPIC_API_KEY が設定されていません。.env ファイルを確認してください。")
        else:
            with st.spinner("AIが回答を読み取り中..."):
                result = _import_answers(uploaded, evaluator, period, api_key, target_candidates)
            if result["success"]:
                st.success(result["message"])
                st.balloons()
            else:
                st.error(result["message"])
            if result.get("details"):
                with st.expander("読み取り詳細"):
                    st.json(result["details"])

    st.stop()


# =====================================================================
# 回答取り込みロジック
# =====================================================================
def _import_answers(files, evaluator: str, period: str, api_key: str,
                    candidates: list[str]) -> dict:
    """アップロードされたファイルからClaude APIで回答を読み取り、DBに保存する。"""
    import anthropic

    # 全評価項目と設問を取得してプロンプトに含める
    all_roles = core.get_all_roles() or []
    items_info = []
    for section in ["共通"] + all_roles:
        for item in core.load_items(section):
            qs = core.load_questions(item["id"])
            items_info.append({
                "section": section,
                "item_id": item["id"],
                "item_name": item["name"],
                "max_score": item["max_score"],
                "questions": [{"qnum": q["qnum"], "text": q["text"]} for q in qs],
            })

    items_json = json.dumps(items_info, ensure_ascii=False, indent=2)
    candidates_str = ", ".join(candidates)

    prompt = f"""この画像は人事評価アンケートの手書き回答です。以下の情報を読み取ってJSON形式で返してください。

【対象者の候補】
{candidates_str}

【評価項目と設問の一覧】
{items_json}

【出力形式】
以下のJSON形式で出力してください。JSONのみを出力し、他のテキストは含めないでください。
```json
{{
  "employee": "被評価者の名前（上記候補から最も近いものを選ぶ）",
  "role": "被評価者の役割（用紙に記載があれば）",
  "answers": [
    {{
      "item_id": 評価項目ID（数値）,
      "item_name": "評価項目名",
      "qnum": "設問番号",
      "answer": 回答（1-5の数値、読み取れない場合はnull）
    }}
  ],
  "comments": [
    {{
      "item_name": "評価項目名",
      "text": "自由記述の内容（読み取れない場合は空文字）"
    }}
  ],
  "overall": [
    {{
      "qnum": "総合設問番号",
      "text": "回答テキスト"
    }}
  ]
}}
```

注意:
- 被評価者名は候補リストから最も近い名前を選んでください
- ○がついている数字を回答値としてください
- 読み取れない部分はnullまたは空文字にしてください
"""

    # 画像をBase64エンコード
    content_blocks = []
    for f in files:
        data = f.read()
        if f.type == "application/pdf":
            # PDFの場合はそのままdocumentとして送る
            content_blocks.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.b64encode(data).decode(),
                },
            })
        else:
            media_type = f.type or "image/png"
            content_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.b64encode(data).decode(),
                },
            })

    content_blocks.append({"type": "text", "text": prompt})

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": content_blocks}],
        )
        raw = response.content[0].text

        # JSON部分を抽出
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0]

        parsed = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        return {"success": False, "message": f"AIの応答をJSONとして解析できませんでした: {e}",
                "details": {"raw_response": raw}}
    except Exception as e:
        return {"success": False, "message": f"AI読み取りに失敗しました: {e}"}

    # DBに保存
    employee = parsed.get("employee", "")
    if not employee:
        return {"success": False, "message": "被評価者を特定できませんでした。", "details": parsed}

    role = parsed.get("role") or core.get_employee_role(employee) or "事務"

    # 回答データを core.save_evaluation 互換の形式に変換
    answers_by_item: dict[int, list] = {}
    comments_by_item: dict[str, str] = {}

    for a in parsed.get("answers", []):
        item_id = a.get("item_id")
        if item_id is not None:
            answers_by_item.setdefault(item_id, []).append(a)

    for c in parsed.get("comments", []):
        if c.get("text"):
            comments_by_item[c["item_name"]] = c["text"]

    # results を組み立て
    results = []
    all_items = core.load_common_items() + core.load_role_items(role)
    for item in all_items:
        item_answers = answers_by_item.get(item["id"], [])
        answer_rows = []
        for a in item_answers:
            answer_rows.append({
                "item_id": item["id"],
                "item_name": item["name"],
                "qnum": a.get("qnum", ""),
                "question_text": "",
                "answer": a.get("answer"),
            })
        comment = comments_by_item.get(item["name"], "")
        results.append({
            "item": item,
            "score": None,
            "comment": comment,
            "answers": answer_rows,
        })

    overall_answers = []
    for o in parsed.get("overall", []):
        if o.get("text"):
            overall_answers.append({
                "qnum": o.get("qnum", ""),
                "question_text": "",
                "answer_text": o.get("text", ""),
            })

    try:
        core.save_evaluation(employee, role, period, evaluator, {}, results, overall_answers)
    except Exception as e:
        return {"success": False, "message": f"DB保存に失敗しました: {e}", "details": parsed}

    n_answers = sum(1 for a in parsed.get("answers", []) if a.get("answer") is not None)
    return {
        "success": True,
        "message": f"✅ {employee} さんの評価を取り込みました（{n_answers}問の回答を読み取り）",
        "details": parsed,
    }


# =====================================================================
# ステップ3: アンケート入力（対象者が選ばれた状態）
# =====================================================================
employee = selected_target

if st.button("← 対象者一覧に戻る"):
    st.session_state.pop("selected_target", None)
    st.rerun()

is_self = employee.strip() == evaluator.strip()
label = f"{employee}（本人評価）" if is_self else employee
st.subheader(f"👤 {label} の評価")

# 対象者の職種区分を自動検出
emp_role = core.get_employee_role(employee)
default_role_idx = 0
if emp_role and emp_role in ALL_ROLES:
    default_role_idx = ALL_ROLES.index(emp_role)
role = st.selectbox("役割", ALL_ROLES, index=default_role_idx)

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

            score = None
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
