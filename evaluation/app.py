"""人事評価管理アプリ

作業日報（sagyo-nippou）の勤怠データを自動参照し、
事務方・現場方・役員の3役割で人事評価を行う。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# ---------------------------------------------------------------------------
# パス設定
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
EVAL_DB_PATH = BASE_DIR / "evaluation.db"
NIPPOU_DB_PATH = BASE_DIR.parent / "sagyo-nippou" / "database.db"

# ---------------------------------------------------------------------------
# 評価項目定義
# ---------------------------------------------------------------------------
COMMON_ITEMS = [
    {"num": 1, "name": "勤怠・規律", "desc": "出勤率、遅刻・早退の頻度、就業規則の遵守", "max_score": 10},
    {"num": 2, "name": "コミュニケーション", "desc": "報連相の的確さ、社内外との連携・調整力", "max_score": 10},
    {"num": 3, "name": "責任感", "desc": "期限遵守、自発的な行動、最後までやり切る姿勢", "max_score": 10},
    {"num": 4, "name": "成長意欲", "desc": "自己研鑽、資格取得への取り組み", "max_score": 5},
]

ROLE_ITEMS = {
    "事務方": [
        {"num": 5, "name": "業務処理の正確性", "desc": "書類・データ入力のミスの少なさ、チェック体制の構築", "max_score": 15},
        {"num": 6, "name": "業務効率", "desc": "処理スピード、業務改善の工夫、ムダの排除", "max_score": 15},
        {"num": 7, "name": "PCスキル / AIスキル", "desc": "Excel・システム操作・事務ツールの活用力・AIを活用した改善提案", "max_score": 10},
        {"num": 8, "name": "入札・契約対応 / 給与計算", "desc": "入札書類の準備、提出期限管理の確実さ / 給与算出の速さ・正確さ", "max_score": 15},
        {"num": 9, "name": "経費・原価管理の成長", "desc": "コスト意識、予算管理の精度、経費削減の取り組み", "max_score": 10},
    ],
    "現場方": [
        {"num": 5, "name": "施工品質", "desc": "仕上がりの丁寧さ、手直しの少なさ、検査合格率", "max_score": 15},
        {"num": 6, "name": "安全管理", "desc": "KY活動の実施、保護具着用、事故・ヒヤリハット報告", "max_score": 15},
        {"num": 7, "name": "技術力・資格", "desc": "電気工事士・特殊作業車運転等の保有資格、技術の幅と深さ", "max_score": 15},
        {"num": 8, "name": "工程管理", "desc": "工期遵守、段取り力、無駄のない作業進行", "max_score": 10},
        {"num": 9, "name": "後輩指導 (シニア)", "desc": "若手への技術指導、若手の成長速度、現場でのチームワーク", "max_score": 10, "choice_group": "field-level"},
        {"num": 10, "name": "学ぶ姿勢 (ジュニア)", "desc": "先輩から学ぶ姿勢、現場での気つかい、成長速度、現場でのチームワーク", "max_score": 10, "choice_group": "field-level"},
    ],
    "役員": [
        {"num": 5, "name": "経営判断", "desc": "受注判断・投資判断の的確さ・現場での判断の的確さ、意思決定のスピード", "max_score": 15},
        {"num": 6, "name": "業績貢献", "desc": "売上・利益目標の達成度、新規顧客の獲得、現場の予算の範囲内で最も効率よく施工するための判断ができているか", "max_score": 20},
        {"num": 7, "name": "組織マネジメント", "desc": "部下の育成、チーム全体の生産性向上、離職防止", "max_score": 15},
        {"num": 8, "name": "リスク管理", "desc": "安全・法令遵守・財務リスクへの対応、危機管理", "max_score": 5},
        {"num": 9, "name": "対外関係", "desc": "顧客・取引先・官公庁との関係構築、業界内の信頼", "max_score": 10},
    ],
}

RANK_TABLE = [
    ("S", 90, 100, "極めて優秀"),
    ("A", 75, 89, "期待以上"),
    ("B", 60, 74, "期待通り（標準）"),
    ("C", 40, 59, "改善が必要"),
    ("D", 0, 39, "大幅な改善が必要"),
]


def get_rank(score: int) -> str:
    for rank, lo, hi, _ in RANK_TABLE:
        if lo <= score <= hi:
            return rank
    return "-"


# ---------------------------------------------------------------------------
# 評価DB
# ---------------------------------------------------------------------------
EVAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    employee     TEXT NOT NULL,
    role         TEXT NOT NULL,
    period       TEXT NOT NULL,
    evaluator    TEXT,
    choice_field TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_scores (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluation_id INTEGER NOT NULL,
    item_num      INTEGER NOT NULL,
    item_name     TEXT NOT NULL,
    score         INTEGER NOT NULL DEFAULT 0,
    comment       TEXT,
    FOREIGN KEY (evaluation_id) REFERENCES evaluations(id) ON DELETE CASCADE
);
"""


def init_eval_db():
    conn = sqlite3.connect(EVAL_DB_PATH)
    conn.executescript(EVAL_SCHEMA)
    conn.close()


@contextmanager
def eval_conn():
    conn = sqlite3.connect(EVAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


init_eval_db()


# ---------------------------------------------------------------------------
# 作業日報DB連携 — 勤怠データ取得
# ---------------------------------------------------------------------------
def get_attendance_stats(worker_name: str, date_from: str, date_to: str) -> dict | None:
    """sagyo-nippou の DB から作業員の勤怠統計を取得する。"""
    if not NIPPOU_DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(NIPPOU_DB_PATH)
        conn.row_factory = sqlite3.Row

        # 出勤日数・総作業時間・総残業時間
        row = conn.execute("""
            SELECT
                COUNT(DISTINCT r.report_date) AS work_days,
                COALESCE(SUM(rw.work_hours), 0) AS total_hours,
                COALESCE(SUM(rw.overtime_h), 0) AS total_overtime,
                COUNT(DISTINCT r.site_id) AS site_count,
                MIN(r.report_date) AS first_date,
                MAX(r.report_date) AS last_date
            FROM report_workers rw
            JOIN reports r ON r.id = rw.report_id
            WHERE rw.worker_name = ?
              AND r.report_date BETWEEN ? AND ?
        """, (worker_name, date_from, date_to)).fetchone()

        # 月別の出勤日数
        monthly = conn.execute("""
            SELECT
                SUBSTR(r.report_date, 1, 7) AS month,
                COUNT(DISTINCT r.report_date) AS days,
                COALESCE(SUM(rw.work_hours), 0) AS hours,
                COALESCE(SUM(rw.overtime_h), 0) AS overtime
            FROM report_workers rw
            JOIN reports r ON r.id = rw.report_id
            WHERE rw.worker_name = ?
              AND r.report_date BETWEEN ? AND ?
            GROUP BY SUBSTR(r.report_date, 1, 7)
            ORDER BY month
        """, (worker_name, date_from, date_to)).fetchall()

        conn.close()

        if not row or row["work_days"] == 0:
            return None

        return {
            "work_days": row["work_days"],
            "total_hours": round(row["total_hours"], 1),
            "total_overtime": round(row["total_overtime"], 1),
            "avg_hours_per_day": round(row["total_hours"] / row["work_days"], 1) if row["work_days"] else 0,
            "site_count": row["site_count"],
            "first_date": row["first_date"],
            "last_date": row["last_date"],
            "monthly": [dict(m) for m in monthly],
        }
    except Exception:
        return None


def get_nippou_workers() -> list[str]:
    """作業日報DBから作業員名一覧を取得する。"""
    if not NIPPOU_DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(NIPPOU_DB_PATH)
        rows = conn.execute(
            "SELECT DISTINCT name FROM workers WHERE is_active = 1 ORDER BY name"
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Streamlit アプリ
# ---------------------------------------------------------------------------
st.set_page_config(page_title="人事評価管理", page_icon="📊", layout="wide")
st.title("📊 人事評価管理")

menu = st.sidebar.radio("メニュー", ["評価入力", "評価一覧", "評価基準"])

# ===== 評価入力 =====
if menu == "評価入力":
    st.header("評価入力")

    nippou_workers = get_nippou_workers()

    col1, col2, col3 = st.columns(3)
    with col1:
        if nippou_workers:
            employee = st.selectbox("対象者", ["（手入力）"] + nippou_workers)
            if employee == "（手入力）":
                employee = st.text_input("対象者名を入力")
        else:
            employee = st.text_input("対象者名")
    with col2:
        role = st.selectbox("役割", list(ROLE_ITEMS.keys()))
    with col3:
        today = date.today()
        fiscal_year_start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
        fiscal_year_end = date(fiscal_year_start.year + 1, 3, 31)
        period = st.text_input("評価期間", f"{fiscal_year_start} 〜 {fiscal_year_end}")
        evaluator = st.text_input("評価者")

    if not employee:
        st.info("対象者を選択または入力してください。")
        st.stop()

    # --- 勤怠データ（作業日報連携） ---
    st.subheader("📋 勤怠データ（作業日報から自動取得）")
    stats = get_attendance_stats(
        employee,
        str(fiscal_year_start),
        str(fiscal_year_end),
    )

    if stats:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("出勤日数", f"{stats['work_days']} 日")
        c2.metric("総作業時間", f"{stats['total_hours']} h")
        c3.metric("総残業時間", f"{stats['total_overtime']} h")
        c4.metric("1日平均作業時間", f"{stats['avg_hours_per_day']} h")

        if stats["monthly"]:
            df_m = pd.DataFrame(stats["monthly"])
            fig = px.bar(df_m, x="month", y="days", text="days",
                         labels={"month": "月", "days": "出勤日数"},
                         title="月別出勤日数")
            fig.update_layout(height=250, margin=dict(t=30, b=20))
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("作業日報にこの対象者のデータがありません。手動で評価してください。")

    st.divider()

    # --- 選択式項目の処理（現場方の9/10） ---
    choice_field = None
    if role == "現場方":
        choice_field = st.radio(
            "対象者のレベル（9/10の評価項目を選択）",
            ["senior", "junior"],
            format_func=lambda x: "シニア（後輩指導）" if x == "senior" else "ジュニア（学ぶ姿勢）",
            horizontal=True,
        )

    # --- 共通評価項目 ---
    st.subheader("共通評価項目")
    scores = {}
    comments = {}

    for item in COMMON_ITEMS:
        col_a, col_b, col_c = st.columns([2, 1, 3])
        with col_a:
            st.markdown(f"**{item['num']}. {item['name']}**")
            st.caption(item["desc"])
        with col_b:
            key = f"common_{item['num']}"
            if item["num"] == 1 and stats:
                # 勤怠の参考値を表示
                suggested = min(10, round(stats["work_days"] / 20))  # 月20日基準
                scores[key] = st.number_input(
                    f"配点（/{item['max_score']}）",
                    0, item["max_score"], suggested,
                    key=key,
                    help=f"参考: 出勤{stats['work_days']}日 → 推奨{suggested}点",
                )
            else:
                scores[key] = st.number_input(
                    f"配点（/{item['max_score']}）", 0, item["max_score"], 0, key=key,
                )
        with col_c:
            comments[key] = st.text_input("コメント", key=f"cmt_{key}", label_visibility="collapsed",
                                          placeholder="コメント（任意）")

    # --- 役割固有の評価項目 ---
    st.subheader(f"{role} 固有の評価項目")

    for item in ROLE_ITEMS[role]:
        # 選択式: 選ばれていない方はスキップ
        if "choice_group" in item:
            if choice_field == "senior" and item["num"] == 10:
                continue
            if choice_field == "junior" and item["num"] == 9:
                continue

        col_a, col_b, col_c = st.columns([2, 1, 3])
        with col_a:
            st.markdown(f"**{item['num']}. {item['name']}**")
            st.caption(item["desc"])
        with col_b:
            key = f"role_{item['num']}"
            scores[key] = st.number_input(
                f"配点（/{item['max_score']}）", 0, item["max_score"], 0, key=key,
            )
        with col_c:
            comments[key] = st.text_input("コメント", key=f"cmt_{key}", label_visibility="collapsed",
                                          placeholder="コメント（任意）")

    # --- 合計・ランク ---
    total = sum(scores.values())
    rank = get_rank(total)

    st.divider()
    col_t1, col_t2 = st.columns(2)
    col_t1.metric("合計点", f"{total} / 100")
    col_t2.metric("評価ランク", rank)

    # --- 保存 ---
    if st.button("評価を保存", type="primary", use_container_width=True):
        if not employee.strip():
            st.error("対象者名を入力してください。")
        else:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with eval_conn() as conn:
                cur = conn.execute(
                    "INSERT INTO evaluations (employee, role, period, evaluator, choice_field, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (employee.strip(), role, period, evaluator, choice_field, now, now),
                )
                eval_id = cur.lastrowid
                for key, score in scores.items():
                    # item_num を key から復元
                    num = int(key.split("_")[1])
                    # item_name を取得
                    item_name = key
                    for item in COMMON_ITEMS + ROLE_ITEMS[role]:
                        if item["num"] == num:
                            item_name = item["name"]
                            break
                    conn.execute(
                        "INSERT INTO eval_scores (evaluation_id, item_num, item_name, score, comment) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (eval_id, num, item_name, score, comments.get(key, "")),
                    )
            st.success(f"{employee} さんの評価を保存しました（ランク: {rank}）")
            st.balloons()


# ===== 評価一覧 =====
elif menu == "評価一覧":
    st.header("評価一覧")

    with eval_conn() as conn:
        evals = conn.execute("""
            SELECT e.*,
                   (SELECT COALESCE(SUM(es.score), 0) FROM eval_scores es WHERE es.evaluation_id = e.id) AS total_score
            FROM evaluations e
            ORDER BY e.created_at DESC
        """).fetchall()

    if not evals:
        st.info("まだ評価データがありません。「評価入力」から登録してください。")
        st.stop()

    # サマリテーブル
    rows = []
    for e in evals:
        d = dict(e)
        d["rank"] = get_rank(d["total_score"])
        rows.append(d)

    df = pd.DataFrame(rows)
    display_cols = {
        "employee": "対象者",
        "role": "役割",
        "period": "評価期間",
        "evaluator": "評価者",
        "total_score": "合計点",
        "rank": "ランク",
        "created_at": "作成日",
    }
    st.dataframe(
        df[list(display_cols.keys())].rename(columns=display_cols),
        use_container_width=True,
        hide_index=True,
    )

    # 詳細表示
    st.subheader("詳細を確認")
    options = [f"{dict(e)['employee']}（{dict(e)['role']}）— {dict(e)['created_at'][:10]}" for e in evals]
    selected_idx = st.selectbox("評価を選択", range(len(options)), format_func=lambda i: options[i])

    if selected_idx is not None:
        ev = dict(evals[selected_idx])
        with eval_conn() as conn:
            details = conn.execute(
                "SELECT * FROM eval_scores WHERE evaluation_id = ? ORDER BY item_num",
                (ev["id"],),
            ).fetchall()

        st.markdown(f"**{ev['employee']}** / {ev['role']} / 評価者: {ev['evaluator'] or '—'}")

        detail_rows = []
        for d in details:
            dd = dict(d)
            detail_rows.append({
                "#": dd["item_num"],
                "項目": dd["item_name"],
                "得点": dd["score"],
                "コメント": dd["comment"] or "",
            })

        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)
        st.metric("合計", f"{ev['total_score']} 点（ランク: {get_rank(ev['total_score'])}）")

        # 削除
        if st.button("この評価を削除", type="secondary"):
            with eval_conn() as conn:
                conn.execute("DELETE FROM evaluations WHERE id = ?", (ev["id"],))
            st.success("削除しました。")
            st.rerun()


# ===== 評価基準 =====
elif menu == "評価基準":
    st.header("評価基準一覧")

    # ランク表
    st.subheader("評価ランク")
    rank_df = pd.DataFrame(RANK_TABLE, columns=["ランク", "下限", "上限", "意味"])
    rank_df["点数"] = rank_df["下限"].astype(str) + " 〜 " + rank_df["上限"].astype(str)
    st.dataframe(rank_df[["ランク", "点数", "意味"]], use_container_width=True, hide_index=True)

    # 共通項目
    st.subheader("共通評価項目（全役割共通）— 35点")
    common_df = pd.DataFrame(COMMON_ITEMS)
    common_df.columns = ["#", "項目", "評価内容", "配点"]
    st.dataframe(common_df, use_container_width=True, hide_index=True)

    # 各役割
    for role_name, items in ROLE_ITEMS.items():
        role_total = sum(i["max_score"] for i in items if "choice_group" not in i)
        # 選択式は片方のみ加算
        choice_groups = set()
        for i in items:
            if "choice_group" in i and i["choice_group"] not in choice_groups:
                role_total += i["max_score"]
                choice_groups.add(i["choice_group"])

        st.subheader(f"{role_name} 固有の評価項目 — {role_total}点（合計: {35 + role_total}点）")
        rows = []
        for i in items:
            label = i["name"]
            if "choice_group" in i:
                label += " ※択一"
            rows.append({"#": i["num"], "項目": label, "評価内容": i["desc"], "配点": i["max_score"]})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
