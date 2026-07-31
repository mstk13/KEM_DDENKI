"""人事評価アプリの共通ロジック（DB・スコア換算・作業日報連携・GitHub反映）

入力アプリ（app.py）と管理アプリ（admin_app.py）の両方から読み込まれる。
このモジュールは Streamlit に依存しない。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# パス設定
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent
EVAL_ITEMS_JSON = BASE_DIR / "eval_items.json"
SURVEY_JSON = BASE_DIR / "survey_questions.json"

sys.path.insert(0, str(REPO_DIR / "shared"))
from dbconn import get_conn, DATABASE_URL  # noqa: E402

# ---------------------------------------------------------------------------
# 5段階尺度
# ---------------------------------------------------------------------------
SCALE = [
    (5, "期待を大きく上回る"),
    (4, "期待を上回る"),
    (3, "期待通り（標準）"),
    (2, "やや不足。指導が必要"),
    (1, "大きく不足。早急な改善が必要"),
]
SCALE_TEXT = {value: label for value, label in SCALE}
SCALE_VALUES = [1, 2, 3, 4, 5]
DEFAULT_ANSWER_VALUE = 3
SCALE_LEGEND = "　｜　".join(f"**{v}** {SCALE_TEXT[v]}" for v in SCALE_VALUES)

SCALE_BUTTON_CSS = """
<style>
div[data-testid="stSegmentedControl"] button {
    min-width: 2.6rem;
    font-weight: 600;
    background-color: #ffffff !important;
    color: #333333 !important;
    border: 1px solid #cfd4d8 !important;
}
div[data-testid="stSegmentedControl"] button:hover {
    background-color: #f2f4f5 !important;
}
div[data-testid="stSegmentedControl"] button[aria-checked="true"],
div[data-testid="stSegmentedControl"] button[aria-selected="true"] {
    background-color: #8a9096 !important;
    color: #ffffff !important;
    border-color: #8a9096 !important;
}
</style>
"""


def questions_to_score(answers: list[int | None], max_score: int) -> tuple[int, float | None]:
    valid = [a for a in answers if a is not None]
    if not valid:
        return 0, None
    avg = sum(valid) / len(valid)
    return round(avg / 5 * max_score), avg


# ---------------------------------------------------------------------------
# デフォルト評価項目
# ---------------------------------------------------------------------------
DEFAULT_COMMON_ITEMS = [
    {"num": 1, "name": "勤怠・規律", "desc": "出勤率、遅刻・早退の頻度、就業規則の遵守", "max_score": 10},
    {"num": 2, "name": "コミュニケーション", "desc": "報連相の的確さ、社内外との連携・調整力", "max_score": 10},
    {"num": 3, "name": "責任感", "desc": "期限遵守、自発的な行動、最後までやり切る姿勢", "max_score": 10},
    {"num": 4, "name": "成長意欲", "desc": "自己研鑽、資格取得への取り組み", "max_score": 5},
    {"num": 5, "name": "スケジュール管理", "desc": "自分の作業の進捗を管理できているか、現場の日程の管理ができているか、取引先とのやり取りや業務が決まった時間内にできているか", "max_score": 5},
]

DEFAULT_ROLE_ITEMS = {
    "事務": [
        {"num": 5, "name": "業務処理の正確性", "desc": "書類・データ入力のミスの少なさ、チェック体制の構築", "max_score": 20},
        {"num": 6, "name": "業務効率", "desc": "処理スピード、業務改善の工夫、ムダの排除", "max_score": 15},
        {"num": 7, "name": "PCスキル / AIスキル", "desc": "Excel・システム操作・事務ツールの活用力・AIを活用した改善提案", "max_score": 10},
        {"num": 9, "name": "経費・原価管理の成長", "desc": "コスト意識、予算管理の精度、経費削減の取り組み", "max_score": 15},
    ],
    "電工": [
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
    "developer": [
        {"num": 5, "name": "業務処理の正確性", "desc": "書類・データ入力のミスの少なさ、チェック体制の構築", "max_score": 20},
        {"num": 6, "name": "業務効率", "desc": "処理スピード、業務改善の工夫、ムダの排除", "max_score": 15},
        {"num": 7, "name": "PCスキル / AIスキル", "desc": "Excel・システム操作・事務ツールの活用力・AIを活用した改善提案", "max_score": 10},
        {"num": 9, "name": "経費・原価管理の成長", "desc": "コスト意識、予算管理の精度、経費削減の取り組み", "max_score": 15},
    ],
    "社長": [
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


def get_rank(score: int, max_total: int | None = None) -> str:
    pct = score if not max_total else score / max_total * 100
    for rank, lo, hi, _ in RANK_TABLE:
        if lo <= pct <= hi:
            return rank
    return "-"


def achievement_rate(score: int, max_total: int | None) -> float:
    if not max_total:
        return float(score)
    return score / max_total * 100


# ---------------------------------------------------------------------------
# DB ヘルパー
# ---------------------------------------------------------------------------
def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


@contextmanager
def eval_conn():
    with get_conn() as conn:
        yield conn


def init_eval_db():
    """スキーマは shared/schema.sql で管理。初回のみ seed データを投入する。"""
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM eval.eval_items")
            if cur.fetchone()["cnt"] == 0:
                _seed_items(conn)
            cur.execute("SELECT COUNT(*) AS cnt FROM eval.survey_questions")
            if cur.fetchone()["cnt"] == 0:
                _seed_questions(conn)


def _seed_items(conn):
    if EVAL_ITEMS_JSON.exists():
        items = json.loads(EVAL_ITEMS_JSON.read_text(encoding="utf-8"))
        with conn.cursor() as cur:
            for it in items:
                cur.execute(
                    "INSERT INTO eval.eval_items (section, num, name, description, max_score, choice_group, sort_order) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (it["section"], it["num"], it["name"], it["description"],
                     it["max_score"], it.get("choice_group"), it.get("sort_order", 0)),
                )
        return

    order = 0
    with conn.cursor() as cur:
        for item in DEFAULT_COMMON_ITEMS:
            cur.execute(
                "INSERT INTO eval.eval_items (section, num, name, description, max_score, choice_group, sort_order) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                ("共通", item["num"], item["name"], item["desc"], item["max_score"], None, order),
            )
            order += 1
        for role, items in DEFAULT_ROLE_ITEMS.items():
            for item in items:
                cur.execute(
                    "INSERT INTO eval.eval_items (section, num, name, description, max_score, choice_group, sort_order) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (role, item["num"], item["name"], item["desc"], item["max_score"],
                     item.get("choice_group"), order),
                )
                order += 1


def _load_survey_json() -> dict:
    if not SURVEY_JSON.exists():
        return {}
    try:
        return json.loads(SURVEY_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _seed_questions(conn):
    data = _load_survey_json()
    with _cur(conn) as cur:
        for entry in data.get("items", []):
            cur.execute(
                "SELECT id FROM eval.eval_items WHERE section = %s AND num = %s",
                (entry["section"], entry["num"]),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "SELECT id FROM eval.eval_items WHERE section = %s AND name = %s",
                    (entry["section"], entry["name"]),
                )
                row = cur.fetchone()
            if row is None:
                continue
            item_id = row["id"]

            cur.execute(
                "UPDATE eval.eval_items SET anchor_5 = %s, anchor_3 = %s, anchor_1 = %s, free_text = %s WHERE id = %s",
                (entry.get("anchor_5", ""), entry.get("anchor_3", ""),
                 entry.get("anchor_1", ""), entry.get("free_text", ""), item_id),
            )
            for order, q in enumerate(entry.get("questions", [])):
                cur.execute(
                    "INSERT INTO eval.survey_questions (item_id, qnum, text, sort_order) VALUES (%s, %s, %s, %s)",
                    (item_id, q.get("qnum", ""), q["text"], order),
                )


def get_overall_questions() -> list[dict]:
    return _load_survey_json().get("overall", [])


def _ensure_evaluator_targets_table():
    """evaluator_targets テーブルがなければ作成する。"""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS eval.evaluator_targets (
                        id             SERIAL PRIMARY KEY,
                        evaluator_name TEXT NOT NULL,
                        target_name    TEXT NOT NULL,
                        created_at     TIMESTAMP NOT NULL DEFAULT NOW(),
                        UNIQUE (evaluator_name, target_name)
                    )
                """)
    except Exception:
        pass


init_eval_db()
_ensure_evaluator_targets_table()


# ---------------------------------------------------------------------------
# 評価項目・設問の読み込み
# ---------------------------------------------------------------------------
def load_items(section: str) -> list[dict]:
    with eval_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT * FROM eval.eval_items WHERE section = %s ORDER BY sort_order, num",
                (section,),
            )
            return [dict(r) for r in cur.fetchall()]


def load_common_items() -> list[dict]:
    return load_items("共通")


def load_role_items(role: str) -> list[dict]:
    return load_items(role)


def load_questions(item_id: int) -> list[dict]:
    with eval_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT * FROM eval.survey_questions WHERE item_id = %s ORDER BY sort_order, id",
                (item_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def count_questions(item_ids: list[int]) -> dict[int, int]:
    if not item_ids:
        return {}
    marks = ",".join("%s" for _ in item_ids)
    with eval_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                f"SELECT item_id, COUNT(*) AS n FROM eval.survey_questions WHERE item_id IN ({marks}) "
                "GROUP BY item_id",
                item_ids,
            )
            return {r["item_id"]: r["n"] for r in cur.fetchall()}


def get_all_roles() -> list[str]:
    with eval_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT DISTINCT section FROM eval.eval_items WHERE section != '共通' ORDER BY section"
            )
            return [r["section"] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# 評価データの読み込み
# ---------------------------------------------------------------------------
def load_evaluations() -> list[dict]:
    with eval_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("""
                SELECT e.*,
                       (SELECT COALESCE(SUM(es.score), 0) FROM eval.eval_scores es
                         WHERE es.evaluation_id = e.id) AS total_score
                FROM eval.evaluations e ORDER BY e.created_at DESC
            """)
            rows = cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["rate"] = achievement_rate(d["total_score"], d["max_total"])
        d["rank"] = get_rank(d["total_score"], d["max_total"])
        result.append(d)
    return result


def load_evaluation_detail(evaluation_id: int) -> dict:
    with eval_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT * FROM eval.eval_scores WHERE evaluation_id = %s ORDER BY id",
                (evaluation_id,),
            )
            scores = [dict(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT * FROM eval.eval_answers WHERE evaluation_id = %s ORDER BY id",
                (evaluation_id,),
            )
            answers = [dict(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT * FROM eval.eval_overall WHERE evaluation_id = %s ORDER BY id",
                (evaluation_id,),
            )
            overall = [dict(r) for r in cur.fetchall()]
    return {"scores": scores, "answers": answers, "overall": overall}


def _norm_name(text) -> str:
    return "".join(str(text or "").split())


def build_answer_matrix(employee: str, evals: list[dict]):
    self_cols, other_cols = [], []
    used_labels: dict[str, int] = {}
    for e in sorted(evals, key=lambda x: str(x["created_at"])):
        raw = (e["evaluator"] or "").strip()
        is_self = bool(_norm_name(raw)) and _norm_name(raw) == _norm_name(employee)
        label = f"{raw}（本人）" if is_self else (raw or "（評価者未記入）")
        used_labels[label] = used_labels.get(label, 0) + 1
        if used_labels[label] > 1:
            label = f"{label} {str(e['created_at'])[:10]}"
        (self_cols if is_self else other_cols).append((label, e))

    columns = self_cols + other_cols
    self_labels = [lb for lb, _ in self_cols]
    other_labels = [lb for lb, _ in other_cols]

    meta: dict[tuple, dict] = {}
    order: list[tuple] = []
    cell: dict[tuple, int | None] = {}
    for label, e in columns:
        for a in load_evaluation_detail(e["id"])["answers"]:
            key = (a["item_name"], a["qnum"])
            if key not in meta:
                meta[key] = {"項目": a["item_name"], "#": a["qnum"], "設問": a["question_text"]}
                order.append(key)
            cell[(key, label)] = a["answer"]

    records = []
    for key in order:
        row = dict(meta[key])
        for label, _ in columns:
            row[label] = cell.get((key, label))
        others = [row[lb] for lb in other_labels if row.get(lb) is not None]
        selfs = [row[lb] for lb in self_labels if row.get(lb) is not None]
        if other_labels:
            row["他者平均"] = round(sum(others) / len(others), 2) if others else None
        if self_labels and other_labels:
            row["差（本人−他者）"] = (round(sum(selfs) / len(selfs) - sum(others) / len(others), 2)
                                 if selfs and others else None)
        records.append(row)

    return pd.DataFrame(records), self_labels, other_labels


def delete_evaluation(evaluation_id: int):
    with eval_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM eval.evaluations WHERE id = %s", (evaluation_id,))


def save_evaluation(employee: str, role: str, period: str, evaluator: str,
                    choice_selections: dict, results: list[dict],
                    overall_answers: list[dict]) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    choice_field = json.dumps(choice_selections, ensure_ascii=False) if choice_selections else None
    max_total = sum(r["item"]["max_score"] for r in results)

    with eval_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "INSERT INTO eval.evaluations "
                "(employee, role, period, evaluator, choice_field, max_total, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (employee, role, period, evaluator, choice_field, max_total, now, now),
            )
            eval_id = cur.fetchone()["id"]
            for r in results:
                if r.get("score") is None:
                    score, _ = questions_to_score([a["answer"] for a in r["answers"]],
                                                  r["item"]["max_score"])
                else:
                    score = r["score"]
                cur.execute(
                    "INSERT INTO eval.eval_scores (evaluation_id, item_num, item_name, score, comment) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (eval_id, r["item"]["num"], r["item"]["name"], score, r["comment"]),
                )
                for a in r["answers"]:
                    cur.execute(
                        "INSERT INTO eval.eval_answers "
                        "(evaluation_id, item_id, item_name, qnum, question_text, answer) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (eval_id, a["item_id"], a["item_name"], a["qnum"], a["question_text"], a["answer"]),
                    )
            for o in overall_answers:
                if o["answer_text"].strip():
                    cur.execute(
                        "INSERT INTO eval.eval_overall (evaluation_id, qnum, question_text, answer_text) "
                        "VALUES (%s, %s, %s, %s)",
                        (eval_id, o["qnum"], o["question_text"], o["answer_text"].strip()),
                    )
    return eval_id


# ---------------------------------------------------------------------------
# 作業日報DB連携 — 勤怠データ取得（PostgreSQL統合DB）
# ---------------------------------------------------------------------------
def get_attendance_stats(worker_name: str, date_from: str, date_to: str) -> dict | None:
    try:
        with get_conn() as conn:
            with _cur(conn) as cur:
                cur.execute("""
                    SELECT
                        COUNT(DISTINCT r.report_date) AS work_days,
                        COALESCE(SUM(rw.work_hours), 0) AS total_hours,
                        COALESCE(SUM(rw.overtime_h), 0) AS total_overtime,
                        COUNT(DISTINCT r.site_id) AS site_count
                    FROM labor.report_workers rw
                    JOIN labor.reports r ON r.id = rw.report_id
                    WHERE rw.worker_name = %s AND r.report_date BETWEEN %s AND %s
                """, (worker_name, date_from, date_to))
                row = cur.fetchone()

                cur.execute("""
                    SELECT TO_CHAR(r.report_date, 'YYYY-MM') AS month,
                           COUNT(DISTINCT r.report_date) AS days,
                           COALESCE(SUM(rw.work_hours), 0) AS hours,
                           COALESCE(SUM(rw.overtime_h), 0) AS overtime
                    FROM labor.report_workers rw
                    JOIN labor.reports r ON r.id = rw.report_id
                    WHERE rw.worker_name = %s AND r.report_date BETWEEN %s AND %s
                    GROUP BY TO_CHAR(r.report_date, 'YYYY-MM')
                    ORDER BY month
                """, (worker_name, date_from, date_to))
                monthly = [dict(m) for m in cur.fetchall()]

        if not row or row["work_days"] == 0:
            return None
        return {
            "work_days": row["work_days"],
            "total_hours": round(float(row["total_hours"]), 1),
            "total_overtime": round(float(row["total_overtime"]), 1),
            "avg_hours_per_day": round(float(row["total_hours"]) / row["work_days"], 1),
            "site_count": row["site_count"],
            "monthly": monthly,
        }
    except Exception:
        return None


def get_nippou_workers() -> list[str]:
    try:
        with get_conn() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    "SELECT DISTINCT name FROM master.employees WHERE is_active = TRUE ORDER BY name"
                )
                return [r["name"] for r in cur.fetchall()]
    except Exception:
        return []


def get_employees_by_role(role: str) -> list[str]:
    """指定職種区分のアクティブ社員名リストを返す。"""
    try:
        with get_conn() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    "SELECT name FROM master.employees "
                    "WHERE is_active = TRUE AND role = %s ORDER BY code",
                    (role,),
                )
                return [r["name"] for r in cur.fetchall()]
    except Exception:
        return []


def get_employee_role(name: str) -> str | None:
    """社員名から職種区分を返す。"""
    try:
        with get_conn() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    "SELECT role FROM master.employees "
                    "WHERE is_active = TRUE AND name = %s LIMIT 1",
                    (name,),
                )
                r = cur.fetchone()
                return r["role"] if r else None
    except Exception:
        return None


def _get_ceo_names() -> list[str]:
    """代表取締役の名前リストを返す。"""
    try:
        with get_conn() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    "SELECT name FROM master.employees "
                    "WHERE is_active = TRUE AND role = '役員' AND position = '代表取締役' "
                    "ORDER BY code"
                )
                return [r["name"] for r in cur.fetchall()]
    except Exception:
        return []


def _get_evaluator_position(name: str) -> str | None:
    """社員名からpositionを返す。"""
    try:
        with get_conn() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    "SELECT position FROM master.employees "
                    "WHERE is_active = TRUE AND name = %s LIMIT 1",
                    (name,),
                )
                r = cur.fetchone()
                return r["position"] if r else None
    except Exception:
        return None


def get_evaluation_targets(evaluator_name: str) -> list[str]:
    """評価者の評価対象者リストを返す。

    ルール:
    - 代表取締役  → 自分含め全員
    - 役員        → 自分 + 代表取締役 + 全電工
    - 事務        → 自分 + 全役員
    - 電工        → 自分 + 全役員
    - developer   → 自分 + 他developer + 代表取締役

    eval.evaluator_targets テーブルに明示的な割り当てがあればそちらを優先。
    """
    # --- テーブルに明示的な割り当てがあればそれを優先 ---
    assigned = get_assigned_targets(evaluator_name)
    if assigned:
        return assigned

    # --- 職種区分ベース ---
    evaluator_role = get_employee_role(evaluator_name)
    evaluator_position = _get_evaluator_position(evaluator_name)

    # 代表取締役 → 全員
    if evaluator_role == "役員" and evaluator_position == "代表取締役":
        return get_nippou_workers()

    # 役員（代表取締役以外）→ 自分 + 代表取締役 + 全電工
    if evaluator_role == "役員":
        targets = [evaluator_name] + _get_ceo_names() + get_employees_by_role("電工")
        return sorted(set(targets))

    # 事務 → 自分 + 全役員
    if evaluator_role == "事務":
        targets = [evaluator_name] + get_employees_by_role("役員")
        return sorted(set(targets))

    # 電工 → 自分 + 全役員
    if evaluator_role == "電工":
        targets = [evaluator_name] + get_employees_by_role("役員")
        return sorted(set(targets))

    # developer → 自分 + 他developer + 代表取締役
    if evaluator_role == "developer":
        targets = get_employees_by_role("developer") + _get_ceo_names()
        return sorted(set(targets))

    return []


# ---------------------------------------------------------------------------
# 評価対象の割り当て管理 (eval.evaluator_targets)
# ---------------------------------------------------------------------------
def get_assigned_targets(evaluator_name: str) -> list[str]:
    """evaluator_targets テーブルから割り当て済みの対象者を返す。"""
    try:
        with get_conn() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    "SELECT target_name FROM eval.evaluator_targets "
                    "WHERE evaluator_name = %s ORDER BY target_name",
                    (evaluator_name,),
                )
                return [r["target_name"] for r in cur.fetchall()]
    except Exception:
        return []


def get_all_evaluator_assignments() -> dict[str, list[str]]:
    """全評価者の割り当てを {評価者: [対象者, ...]} で返す。"""
    try:
        with get_conn() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    "SELECT evaluator_name, target_name FROM eval.evaluator_targets "
                    "ORDER BY evaluator_name, target_name"
                )
                result: dict[str, list[str]] = {}
                for r in cur.fetchall():
                    result.setdefault(r["evaluator_name"], []).append(r["target_name"])
                return result
    except Exception:
        return {}


def save_evaluator_targets(evaluator_name: str, target_names: list[str]):
    """評価者の対象者リストを上書き保存する。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM eval.evaluator_targets WHERE evaluator_name = %s",
                (evaluator_name,),
            )
            for name in target_names:
                cur.execute(
                    "INSERT INTO eval.evaluator_targets (evaluator_name, target_name) "
                    "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (evaluator_name, name),
                )


def get_evaluator_options() -> list[str]:
    names = set(get_nippou_workers())
    try:
        with eval_conn() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    "SELECT DISTINCT evaluator FROM eval.evaluations "
                    "WHERE evaluator IS NOT NULL AND TRIM(evaluator) <> ''"
                )
                names.update((r["evaluator"] or "").strip() for r in cur.fetchall())
    except Exception:
        pass
    return sorted(n for n in names if n)


# ---------------------------------------------------------------------------
# GitHub反映
# ---------------------------------------------------------------------------
def export_items_to_json() -> str:
    with eval_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT section, num, name, description, max_score, choice_group, sort_order "
                "FROM eval.eval_items ORDER BY section, sort_order, num"
            )
            rows = cur.fetchall()
    items = [dict(r) for r in rows]
    EVAL_ITEMS_JSON.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return str(EVAL_ITEMS_JSON)


def export_survey_to_json() -> str:
    with eval_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT id, section, num, name, anchor_5, anchor_3, anchor_1, free_text "
                "FROM eval.eval_items ORDER BY section, sort_order, num"
            )
            items = cur.fetchall()
            entries = []
            for it in items:
                cur.execute(
                    "SELECT qnum, text FROM eval.survey_questions WHERE item_id = %s ORDER BY sort_order, id",
                    (it["id"],),
                )
                qs = cur.fetchall()
                if not qs and not it["anchor_3"]:
                    continue
                entries.append({
                    "section": it["section"],
                    "num": it["num"],
                    "name": it["name"],
                    "anchor_5": it["anchor_5"],
                    "anchor_3": it["anchor_3"],
                    "anchor_1": it["anchor_1"],
                    "free_text": it["free_text"],
                    "questions": [{"qnum": q["qnum"], "text": q["text"]} for q in qs],
                })

    data = _load_survey_json()
    payload = {
        "version": data.get("version", 1),
        "scale": data.get("scale", [{"value": v, "label": lb} for v, lb in SCALE]),
        "items": entries,
        "overall": data.get("overall", []),
    }
    SURVEY_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return str(SURVEY_JSON)


def _current_branch() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(REPO_DIR), capture_output=True, text=True,
    )
    branch = result.stdout.strip()
    return branch if result.returncode == 0 and branch and branch != "HEAD" else "main"


def push_to_github() -> tuple[bool, str]:
    export_items_to_json()
    export_survey_to_json()
    try:
        subprocess.run(
            ["git", "add", "evaluation/eval_items.json", "evaluation/survey_questions.json"],
            cwd=str(REPO_DIR), capture_output=True, text=True, check=True,
        )
        diff = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(REPO_DIR), capture_output=True, text=True,
        )
        if not diff.stdout.strip():
            return True, "変更はありません（既に最新です）"

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        subprocess.run(
            ["git", "commit", "-m", f"update: 評価項目・設問を更新（{now} ブラウザから反映）"],
            cwd=str(REPO_DIR), capture_output=True, text=True, check=True,
        )
        branch = _current_branch()
        result = subprocess.run(
            ["git", "push", "origin", branch],
            cwd=str(REPO_DIR), capture_output=True, text=True,
        )
        if result.returncode != 0:
            return False, f"push に失敗しました: {result.stderr}"
        return True, f"GitHubに反映しました（ブランチ: {branch}）"
    except subprocess.CalledProcessError as e:
        return False, f"エラー: {e.stderr or e.stdout or str(e)}"
