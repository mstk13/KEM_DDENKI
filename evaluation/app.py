"""人事評価管理アプリ

作業日報アプリの勤怠データを自動参照し、
事務方・現場方・役員の3役割で人事評価を行う。
評価項目はブラウザ上で編集可能（DBに保存）。
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
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
REPO_DIR = BASE_DIR.parent
EVAL_DB_PATH = BASE_DIR / "evaluation.db"
EVAL_ITEMS_JSON = BASE_DIR / "eval_items.json"
NIPPOU_DB_PATH = REPO_DIR / "作業日報" / "database.db"

# ---------------------------------------------------------------------------
# デフォルト評価項目（初回DB投入用）
# ---------------------------------------------------------------------------
DEFAULT_COMMON_ITEMS = [
    {"num": 1, "name": "勤怠・規律", "desc": "出勤率、遅刻・早退の頻度、就業規則の遵守", "max_score": 10},
    {"num": 2, "name": "コミュニケーション", "desc": "報連相の的確さ、社内外との連携・調整力", "max_score": 10},
    {"num": 3, "name": "責任感", "desc": "期限遵守、自発的な行動、最後までやり切る姿勢", "max_score": 10},
    {"num": 4, "name": "成長意欲", "desc": "自己研鑽、資格取得への取り組み", "max_score": 5},
    {"num": 5, "name": "スケジュール管理", "desc": "自分の作業の進捗を管理できているか、現場の日程の管理ができているか、取引先とのやり取りや業務が決まった時間内にできているか", "max_score": 5},
]

DEFAULT_ROLE_ITEMS = {
    "事務方": [
        {"num": 5, "name": "業務処理の正確性", "desc": "書類・データ入力のミスの少なさ、チェック体制の構築", "max_score": 20},
        {"num": 6, "name": "業務効率", "desc": "処理スピード、業務改善の工夫、ムダの排除", "max_score": 15},
        {"num": 7, "name": "PCスキル / AIスキル", "desc": "Excel・システム操作・事務ツールの活用力・AIを活用した改善提案", "max_score": 10},
        {"num": 9, "name": "経費・原価管理の成長", "desc": "コスト意識、予算管理の精度、経費削減の取り組み", "max_score": 15},
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
        {"num": 5, "name": "経営判断", "desc": "受注判断・投資判断の的確さ・現場での判断の的確さ、意思決定のスピード", "max_score": 10},
        {"num": 6, "name": "業績貢献", "desc": "売上・利益目標の達成度、新規顧客の獲得、現場の予算の範囲内で最も効率よく施工するための判断ができているか", "max_score": 10},
        {"num": 7, "name": "組織マネジメント", "desc": "部下の育成、チーム全体の生産性向上、離職防止", "max_score": 10},
        {"num": 8, "name": "リスク管理", "desc": "安全・法令遵守・財務リスクへの対応、危機管理", "max_score": 5},
        {"num": 9, "name": "対外関係", "desc": "顧客・取引先・官公庁との関係構築、業界内の信頼", "max_score": 10},
        {"num": 10, "name": "原価管理", "desc": "無駄な材料の発注、材料の管理、人経費の管理", "max_score": 10},
        {"num": 11, "name": "資格取得 / 自己研鑽", "desc": "新しい資格の取得、自己研鑽のための取り組み（読書・セミナー参加など）", "max_score": 5},
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

CREATE TABLE IF NOT EXISTS eval_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    section      TEXT NOT NULL,
    num          INTEGER NOT NULL,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    max_score    INTEGER NOT NULL DEFAULT 10,
    choice_group TEXT,
    sort_order   INTEGER NOT NULL DEFAULT 0
);
"""


def init_eval_db():
    conn = sqlite3.connect(EVAL_DB_PATH)
    conn.executescript(EVAL_SCHEMA)
    count = conn.execute("SELECT COUNT(*) FROM eval_items").fetchone()[0]
    if count == 0:
        _seed_items(conn)
    conn.commit()
    conn.close()


def _seed_items(conn):
    """eval_items.json があればそこから、なければハードコードのデフォルトからDBに投入。"""
    if EVAL_ITEMS_JSON.exists():
        items = json.loads(EVAL_ITEMS_JSON.read_text(encoding="utf-8"))
        for it in items:
            conn.execute(
                "INSERT INTO eval_items (section, num, name, description, max_score, choice_group, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (it["section"], it["num"], it["name"], it["description"],
                 it["max_score"], it.get("choice_group"), it.get("sort_order", 0)),
            )
        return

    order = 0
    for item in DEFAULT_COMMON_ITEMS:
        conn.execute(
            "INSERT INTO eval_items (section, num, name, description, max_score, choice_group, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("共通", item["num"], item["name"], item["desc"], item["max_score"], None, order),
        )
        order += 1
    for role, items in DEFAULT_ROLE_ITEMS.items():
        for item in items:
            conn.execute(
                "INSERT INTO eval_items (section, num, name, description, max_score, choice_group, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (role, item["num"], item["name"], item["desc"], item["max_score"],
                 item.get("choice_group"), order),
            )
            order += 1


# ---------------------------------------------------------------------------
# GitHub反映: DB → JSON → git commit & push
# ---------------------------------------------------------------------------
def export_items_to_json() -> str:
    """eval_items テーブルをJSONファイルにエクスポートする。"""
    with eval_conn() as conn:
        rows = conn.execute(
            "SELECT section, num, name, description, max_score, choice_group, sort_order "
            "FROM eval_items ORDER BY section, sort_order, num"
        ).fetchall()
    items = [dict(r) for r in rows]
    EVAL_ITEMS_JSON.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return str(EVAL_ITEMS_JSON)


def push_to_github() -> tuple[bool, str]:
    """評価項目をJSONにエクスポートし、git commit & push する。"""
    export_items_to_json()
    try:
        # git add
        subprocess.run(
            ["git", "add", "evaluation/eval_items.json"],
            cwd=str(REPO_DIR), capture_output=True, text=True, check=True,
        )
        # 変更があるか確認
        diff = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(REPO_DIR), capture_output=True, text=True,
        )
        if not diff.stdout.strip():
            return True, "変更はありません（既に最新です）"

        # git commit
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        subprocess.run(
            ["git", "commit", "-m", f"update: 評価項目を更新（{now} ブラウザから反映）"],
            cwd=str(REPO_DIR), capture_output=True, text=True, check=True,
        )
        # git push
        result = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=str(REPO_DIR), capture_output=True, text=True,
        )
        if result.returncode != 0:
            return False, f"push に失敗しました: {result.stderr}"
        return True, "GitHubに反映しました"
    except subprocess.CalledProcessError as e:
        return False, f"エラー: {e.stderr or e.stdout or str(e)}"


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
# 評価項目の読み込み（DBから）
# ---------------------------------------------------------------------------
def load_items(section: str) -> list[dict]:
    with eval_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM eval_items WHERE section = ? ORDER BY sort_order, num",
            (section,),
        ).fetchall()
    return [dict(r) for r in rows]


def load_common_items() -> list[dict]:
    return load_items("共通")


def load_role_items(role: str) -> list[dict]:
    return load_items(role)


def get_all_roles() -> list[str]:
    """DBに登録されている役割一覧を返す（共通を除く）。"""
    with eval_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT section FROM eval_items WHERE section != '共通' ORDER BY section"
        ).fetchall()
    return [r["section"] for r in rows]


# ---------------------------------------------------------------------------
# 作業日報DB連携 — 勤怠データ取得
# ---------------------------------------------------------------------------
def get_attendance_stats(worker_name: str, date_from: str, date_to: str) -> dict | None:
    if not NIPPOU_DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(NIPPOU_DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("""
            SELECT
                COUNT(DISTINCT r.report_date) AS work_days,
                COALESCE(SUM(rw.work_hours), 0) AS total_hours,
                COALESCE(SUM(rw.overtime_h), 0) AS total_overtime,
                COUNT(DISTINCT r.site_id) AS site_count
            FROM report_workers rw
            JOIN reports r ON r.id = rw.report_id
            WHERE rw.worker_name = ? AND r.report_date BETWEEN ? AND ?
        """, (worker_name, date_from, date_to)).fetchone()
        monthly = conn.execute("""
            SELECT SUBSTR(r.report_date, 1, 7) AS month,
                   COUNT(DISTINCT r.report_date) AS days,
                   COALESCE(SUM(rw.work_hours), 0) AS hours,
                   COALESCE(SUM(rw.overtime_h), 0) AS overtime
            FROM report_workers rw
            JOIN reports r ON r.id = rw.report_id
            WHERE rw.worker_name = ? AND r.report_date BETWEEN ? AND ?
            GROUP BY SUBSTR(r.report_date, 1, 7) ORDER BY month
        """, (worker_name, date_from, date_to)).fetchall()
        conn.close()
        if not row or row["work_days"] == 0:
            return None
        return {
            "work_days": row["work_days"],
            "total_hours": round(row["total_hours"], 1),
            "total_overtime": round(row["total_overtime"], 1),
            "avg_hours_per_day": round(row["total_hours"] / row["work_days"], 1),
            "site_count": row["site_count"],
            "monthly": [dict(m) for m in monthly],
        }
    except Exception:
        return None


def get_nippou_workers() -> list[str]:
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

ALL_ROLES = get_all_roles() or ["事務方", "現場方", "役員"]

menu = st.sidebar.radio("メニュー", ["評価入力", "評価一覧", "評価基準の閲覧", "評価基準の編集"])

# =====================================================================
# 評価入力
# =====================================================================
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
        role = st.selectbox("役割", ALL_ROLES)
    with col3:
        today = date.today()
        fy_start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
        fy_end = date(fy_start.year + 1, 3, 31)
        period = st.text_input("評価期間", f"{fy_start} 〜 {fy_end}")
        evaluator = st.text_input("評価者")

    if not employee:
        st.info("対象者を選択または入力してください。")
        st.stop()

    # 勤怠データ
    st.subheader("📋 勤怠データ（作業日報から自動取得）")
    stats = get_attendance_stats(employee, str(fy_start), str(fy_end))
    if stats:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("出勤日数", f"{stats['work_days']} 日")
        c2.metric("総作業時間", f"{stats['total_hours']} h")
        c3.metric("総残業時間", f"{stats['total_overtime']} h")
        c4.metric("1日平均作業時間", f"{stats['avg_hours_per_day']} h")
        if stats["monthly"]:
            df_m = pd.DataFrame(stats["monthly"])
            fig = px.bar(df_m, x="month", y="days", text="days",
                         labels={"month": "月", "days": "出勤日数"}, title="月別出勤日数")
            fig.update_layout(height=250, margin=dict(t=30, b=20))
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("作業日報にこの対象者のデータがありません。手動で評価してください。")

    st.divider()

    common_items = load_common_items()
    role_items = load_role_items(role)

    # 択一選択
    choice_groups = set(i["choice_group"] for i in role_items if i.get("choice_group"))
    choice_selections = {}
    for cg in choice_groups:
        cg_items = [i for i in role_items if i.get("choice_group") == cg]
        options = {i["name"]: i["num"] for i in cg_items}
        choice_selections[cg] = st.radio(
            f"以下の項目はどちらか一方を選択",
            list(options.keys()),
            horizontal=True,
        )

    # 共通評価
    st.subheader("共通評価項目")
    scores = {}
    comments = {}
    for item in common_items:
        col_a, col_b, col_c = st.columns([2, 1, 3])
        with col_a:
            st.markdown(f"**{item['num']}. {item['name']}**")
            st.caption(item["description"])
        with col_b:
            key = f"common_{item['id']}"
            default = 0
            if item["name"] == "勤怠・規律" and stats:
                default = min(item["max_score"], round(stats["work_days"] / 20))
            scores[key] = st.number_input(
                f"配点（/{item['max_score']}）", 0, item["max_score"], default, key=key,
                help=f"参考: 出勤{stats['work_days']}日" if item["name"] == "勤怠・規律" and stats else None,
            )
        with col_c:
            comments[key] = st.text_input("コメント", key=f"cmt_{key}", label_visibility="collapsed",
                                          placeholder="コメント（任意）")

    # 役割固有
    st.subheader(f"{role} 固有の評価項目")
    for item in role_items:
        if item.get("choice_group"):
            selected_name = choice_selections.get(item["choice_group"])
            if selected_name != item["name"]:
                continue

        col_a, col_b, col_c = st.columns([2, 1, 3])
        with col_a:
            st.markdown(f"**{item['num']}. {item['name']}**")
            st.caption(item["description"])
        with col_b:
            key = f"role_{item['id']}"
            scores[key] = st.number_input(
                f"配点（/{item['max_score']}）", 0, item["max_score"], 0, key=key,
            )
        with col_c:
            comments[key] = st.text_input("コメント", key=f"cmt_{key}", label_visibility="collapsed",
                                          placeholder="コメント（任意）")

    total = sum(scores.values())
    rank = get_rank(total)
    st.divider()
    col_t1, col_t2 = st.columns(2)
    col_t1.metric("合計点", f"{total} / 100")
    col_t2.metric("評価ランク", rank)

    if st.button("評価を保存", type="primary", use_container_width=True):
        if not employee.strip():
            st.error("対象者名を入力してください。")
        else:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            choice_field = json.dumps(choice_selections, ensure_ascii=False) if choice_selections else None
            with eval_conn() as conn:
                cur = conn.execute(
                    "INSERT INTO evaluations (employee, role, period, evaluator, choice_field, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (employee.strip(), role, period, evaluator, choice_field, now, now),
                )
                eval_id = cur.lastrowid
                all_items = common_items + role_items
                for key, score in scores.items():
                    item_id = int(key.split("_")[1])
                    item_name = key
                    for item in all_items:
                        if item["id"] == item_id:
                            item_name = item["name"]
                            break
                    conn.execute(
                        "INSERT INTO eval_scores (evaluation_id, item_num, item_name, score, comment) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (eval_id, item_id, item_name, score, comments.get(key, "")),
                    )
            st.success(f"{employee} さんの評価を保存しました（ランク: {rank}）")
            st.balloons()


# =====================================================================
# 評価一覧
# =====================================================================
elif menu == "評価一覧":
    st.header("評価一覧")

    with eval_conn() as conn:
        evals = conn.execute("""
            SELECT e.*,
                   (SELECT COALESCE(SUM(es.score), 0) FROM eval_scores es WHERE es.evaluation_id = e.id) AS total_score
            FROM evaluations e ORDER BY e.created_at DESC
        """).fetchall()

    if not evals:
        st.info("まだ評価データがありません。「評価入力」から登録してください。")
        st.stop()

    rows = []
    for e in evals:
        d = dict(e)
        d["rank"] = get_rank(d["total_score"])
        rows.append(d)

    df = pd.DataFrame(rows)
    display_cols = {"employee": "対象者", "role": "役割", "period": "評価期間",
                    "evaluator": "評価者", "total_score": "合計点", "rank": "ランク", "created_at": "作成日"}
    st.dataframe(df[list(display_cols.keys())].rename(columns=display_cols),
                 use_container_width=True, hide_index=True)

    st.subheader("詳細を確認")
    options = [f"{dict(e)['employee']}（{dict(e)['role']}）— {dict(e)['created_at'][:10]}" for e in evals]
    selected_idx = st.selectbox("評価を選択", range(len(options)), format_func=lambda i: options[i])

    if selected_idx is not None:
        ev = dict(evals[selected_idx])
        with eval_conn() as conn:
            details = conn.execute(
                "SELECT * FROM eval_scores WHERE evaluation_id = ? ORDER BY item_num", (ev["id"],),
            ).fetchall()
        st.markdown(f"**{ev['employee']}** / {ev['role']} / 評価者: {ev['evaluator'] or '—'}")
        detail_rows = [{"#": dict(d)["item_num"], "項目": dict(d)["item_name"],
                        "得点": dict(d)["score"], "コメント": dict(d)["comment"] or ""} for d in details]
        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)
        st.metric("合計", f"{ev['total_score']} 点（ランク: {get_rank(ev['total_score'])}）")

        if st.button("この評価を削除", type="secondary"):
            with eval_conn() as conn:
                conn.execute("DELETE FROM evaluations WHERE id = ?", (ev["id"],))
            st.success("削除しました。")
            st.rerun()


# =====================================================================
# 評価基準の閲覧
# =====================================================================
elif menu == "評価基準の閲覧":
    st.header("評価基準一覧")

    st.subheader("評価ランク")
    rank_df = pd.DataFrame(RANK_TABLE, columns=["ランク", "下限", "上限", "意味"])
    rank_df["点数"] = rank_df["下限"].astype(str) + " 〜 " + rank_df["上限"].astype(str)
    st.dataframe(rank_df[["ランク", "点数", "意味"]], use_container_width=True, hide_index=True)

    common_items = load_common_items()
    common_total = sum(i["max_score"] for i in common_items)
    st.subheader(f"共通評価項目（全役割共通）— {common_total}点")
    st.dataframe(
        pd.DataFrame([{"#": i["num"], "項目": i["name"], "評価内容": i["description"], "配点": i["max_score"]}
                       for i in common_items]),
        use_container_width=True, hide_index=True,
    )

    for role_name in ALL_ROLES:
        items = load_role_items(role_name)
        # 択一は片方のみ加算
        role_total = 0
        seen_cg = set()
        for i in items:
            if i.get("choice_group"):
                if i["choice_group"] not in seen_cg:
                    role_total += i["max_score"]
                    seen_cg.add(i["choice_group"])
            else:
                role_total += i["max_score"]

        st.subheader(f"{role_name} 固有の評価項目 — {role_total}点（合計: {common_total + role_total}点）")
        rows = []
        for i in items:
            label = i["name"] + (" ※択一" if i.get("choice_group") else "")
            rows.append({"#": i["num"], "項目": label, "評価内容": i["description"], "配点": i["max_score"]})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# =====================================================================
# 評価基準の編集
# =====================================================================
elif menu == "評価基準の編集":
    st.header("評価基準の編集")
    st.caption("項目名・内容・配点を変更して「保存」を押してください。行の追加・削除もできます。")

    edit_section = st.selectbox("編集するセクション", ["共通"] + ALL_ROLES)

    items = load_items(edit_section)

    # --- 既存項目の編集 ---
    if items:
        st.subheader(f"「{edit_section}」の評価項目")

        edited_items = []
        delete_ids = []

        for i, item in enumerate(items):
            with st.container(border=True):
                cols = st.columns([0.5, 2, 4, 1, 1.5, 0.5])
                with cols[0]:
                    new_num = st.number_input("番号", value=item["num"], key=f"num_{item['id']}", label_visibility="collapsed")
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
                    "id": item["id"],
                    "num": new_num,
                    "name": new_name,
                    "description": new_desc,
                    "max_score": new_score,
                    "choice_group": new_cg.strip() or None,
                    "sort_order": i,
                })

        # 合計点の表示
        active_total = sum(it["max_score"] for it in edited_items if it["id"] not in delete_ids)
        if edit_section == "共通":
            st.info(f"共通 小計: **{active_total}点**")
        else:
            common_total = sum(i["max_score"] for i in load_common_items())
            st.info(f"固有 小計: **{active_total}点** ／ 合計（共通{common_total} + 固有{active_total}）: **{common_total + active_total}点**")

        # 削除実行
        if delete_ids:
            with eval_conn() as conn:
                for did in delete_ids:
                    conn.execute("DELETE FROM eval_items WHERE id = ?", (did,))
            st.success(f"{len(delete_ids)} 件削除しました。")
            st.rerun()

        # 保存ボタン
        if st.button("変更を保存", type="primary", use_container_width=True):
            with eval_conn() as conn:
                for it in edited_items:
                    conn.execute(
                        "UPDATE eval_items SET num=?, name=?, description=?, max_score=?, choice_group=?, sort_order=? "
                        "WHERE id=?",
                        (it["num"], it["name"], it["description"], it["max_score"], it["choice_group"],
                         it["sort_order"], it["id"]),
                    )
            st.success("保存しました。")
            st.rerun()
    else:
        st.info(f"「{edit_section}」にはまだ項目がありません。下のフォームから追加してください。")

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
                with eval_conn() as conn:
                    conn.execute(
                        "INSERT INTO eval_items (section, num, name, description, max_score, choice_group, sort_order) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (edit_section, add_num, add_name.strip(), add_desc.strip(), add_score,
                         add_cg.strip() or None, max_order),
                    )
                st.success(f"「{add_name}」を追加しました。")
                st.rerun()

    # --- 新しい役割の追加 ---
    if edit_section == "共通":
        st.divider()
        st.subheader("新しい役割を追加")
        st.caption("事務方・現場方・役員以外の役割が必要な場合はここから追加できます。")
        with st.form("add_role_form"):
            new_role = st.text_input("役割名", placeholder="例: パート・アルバイト")
            role_submitted = st.form_submit_button("役割を追加")
            if role_submitted:
                if not new_role.strip():
                    st.error("役割名を入力してください。")
                elif new_role.strip() in ALL_ROLES:
                    st.error("その役割は既に存在します。")
                else:
                    with eval_conn() as conn:
                        conn.execute(
                            "INSERT INTO eval_items (section, num, name, description, max_score, sort_order) "
                            "VALUES (?, 5, '（項目名を設定）', '（評価内容を設定）', 10, 0)",
                            (new_role.strip(),),
                        )
                    st.success(f"役割「{new_role}」を追加しました。「評価基準の編集」で項目を設定してください。")
                    st.rerun()

    # --- GitHubに反映 ---
    st.divider()
    st.subheader("GitHubに反映")
    st.caption("現在の評価項目をGitHubにプッシュして、他のPCにも反映させます。")
    if st.button("GitHubに反映する", type="primary", use_container_width=True, key="push_github"):
        with st.spinner("GitHubに反映中..."):
            ok, msg = push_to_github()
        if ok:
            st.success(msg)
        else:
            st.error(msg)
