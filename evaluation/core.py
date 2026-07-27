"""人事評価アプリの共通ロジック（DB・スコア換算・作業日報連携・GitHub反映）

入力アプリ（app.py）と管理アプリ（admin_app.py）の両方から読み込まれる。
このモジュールは Streamlit に依存しない。
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# パス設定
#   DB はリポジトリ直下の data/ に集約する。共有フォルダを使う場合は
#   環境変数 KEM_DATA_DIR で保存先を差し替えられる。
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent
_DATA_DIR = Path(os.getenv("KEM_DATA_DIR", str(REPO_DIR / "data")))
EVAL_DB_PATH = _DATA_DIR / "evaluation.db"
EVAL_ITEMS_JSON = BASE_DIR / "eval_items.json"
SURVEY_JSON = BASE_DIR / "survey_questions.json"
NIPPOU_DB_PATH = _DATA_DIR / "sagyo_nippou.db"

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
SCALE_VALUES = [1, 2, 3, 4, 5]           # ボタンは 1 → 5 の順に並べる
DEFAULT_ANSWER_VALUE = 3                 # 初期選択は「3 期待通り（標準）」
SCALE_LEGEND = "　｜　".join(f"**{v}** {SCALE_TEXT[v]}" for v in SCALE_VALUES)

# 1〜5 のボタン: 未選択は白、選択中はグレー。
# Streamlit の segmented control は選択中のボタンに aria-checked="true" が付く。
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
    """設問の回答リストから項目得点を換算する。戻り値: (得点, 平均点)"""
    valid = [a for a in answers if a is not None]
    if not valid:
        return 0, None
    avg = sum(valid) / len(valid)
    return round(avg / 5 * max_score), avg


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


def get_rank(score: int, max_total: int | None = None) -> str:
    """得点からランクを求める。

    max_total を渡すと「満点に対する%」で判定する（満点が100点でない役割に対応）。
    max_total が None / 0 の場合は従来どおり素点を100点満点とみなす。
    """
    pct = score if not max_total else score / max_total * 100
    for rank, lo, hi, _ in RANK_TABLE:
        if lo <= pct <= hi:
            return rank
    return "-"


def achievement_rate(score: int, max_total: int | None) -> float:
    """達成率（%）。満点が記録されていない古いデータは素点をそのまま%とみなす。"""
    if not max_total:
        return float(score)
    return score / max_total * 100


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

-- アンケート設問（評価項目にぶら下がる）
CREATE TABLE IF NOT EXISTS survey_questions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    INTEGER NOT NULL,
    qnum       TEXT NOT NULL DEFAULT '',
    text       TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (item_id) REFERENCES eval_items(id) ON DELETE CASCADE
);

-- 設問ごとの回答（1〜5、N/Aは NULL）
CREATE TABLE IF NOT EXISTS eval_answers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluation_id INTEGER NOT NULL,
    item_id       INTEGER,
    item_name     TEXT NOT NULL DEFAULT '',
    qnum          TEXT NOT NULL DEFAULT '',
    question_text TEXT NOT NULL DEFAULT '',
    answer        INTEGER,
    FOREIGN KEY (evaluation_id) REFERENCES evaluations(id) ON DELETE CASCADE
);

-- 総合設問（自由記述）
CREATE TABLE IF NOT EXISTS eval_overall (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluation_id INTEGER NOT NULL,
    qnum          TEXT NOT NULL DEFAULT '',
    question_text TEXT NOT NULL DEFAULT '',
    answer_text   TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (evaluation_id) REFERENCES evaluations(id) ON DELETE CASCADE
);
"""

# 既存DBに後から追加した列（テーブル名 → [(列名, 定義)]）
MIGRATIONS = {
    "eval_items": [
        ("anchor_5", "TEXT NOT NULL DEFAULT ''"),
        ("anchor_3", "TEXT NOT NULL DEFAULT ''"),
        ("anchor_1", "TEXT NOT NULL DEFAULT ''"),
        ("free_text", "TEXT NOT NULL DEFAULT ''"),
    ],
    "evaluations": [
        ("max_total", "INTEGER NOT NULL DEFAULT 0"),
    ],
}


def _migrate(conn):
    """不足している列を追加する（既存の evaluation.db をそのまま使えるようにする）。"""
    for table, columns in MIGRATIONS.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for col, ddl in columns:
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


@contextmanager
def eval_conn():
    # 入力アプリと管理アプリが同じDBを触るため、ロック待ちの余裕を持たせる
    conn = sqlite3.connect(EVAL_DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_eval_db():
    # data/ フォルダは初回起動時にはまだ無いことがある
    EVAL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(EVAL_DB_PATH, timeout=15)
    conn.executescript(EVAL_SCHEMA)
    _migrate(conn)
    count = conn.execute("SELECT COUNT(*) FROM eval_items").fetchone()[0]
    if count == 0:
        _seed_items(conn)
    if conn.execute("SELECT COUNT(*) FROM survey_questions").fetchone()[0] == 0:
        _seed_questions(conn)
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


def _load_survey_json() -> dict:
    if not SURVEY_JSON.exists():
        return {}
    try:
        return json.loads(SURVEY_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _seed_questions(conn):
    """survey_questions.json の設問・判断基準を eval_items に紐づけて投入する。

    JSONの項目と既存の eval_items 行は (section, num) で照合し、
    見つからなければ (section, name) で照合する。どちらも無ければスキップ。
    """
    data = _load_survey_json()
    for entry in data.get("items", []):
        row = conn.execute(
            "SELECT id FROM eval_items WHERE section = ? AND num = ?",
            (entry["section"], entry["num"]),
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id FROM eval_items WHERE section = ? AND name = ?",
                (entry["section"], entry["name"]),
            ).fetchone()
        if row is None:
            continue
        item_id = row[0]

        conn.execute(
            "UPDATE eval_items SET anchor_5 = ?, anchor_3 = ?, anchor_1 = ?, free_text = ? WHERE id = ?",
            (entry.get("anchor_5", ""), entry.get("anchor_3", ""),
             entry.get("anchor_1", ""), entry.get("free_text", ""), item_id),
        )
        for order, q in enumerate(entry.get("questions", [])):
            conn.execute(
                "INSERT INTO survey_questions (item_id, qnum, text, sort_order) VALUES (?, ?, ?, ?)",
                (item_id, q.get("qnum", ""), q["text"], order),
            )


def get_overall_questions() -> list[dict]:
    return _load_survey_json().get("overall", [])


init_eval_db()


# ---------------------------------------------------------------------------
# 評価項目・設問の読み込み
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


def load_questions(item_id: int) -> list[dict]:
    with eval_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM survey_questions WHERE item_id = ? ORDER BY sort_order, id",
            (item_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def count_questions(item_ids: list[int]) -> dict[int, int]:
    """項目IDごとの設問数をまとめて取得する。"""
    if not item_ids:
        return {}
    marks = ",".join("?" * len(item_ids))
    with eval_conn() as conn:
        rows = conn.execute(
            f"SELECT item_id, COUNT(*) AS n FROM survey_questions WHERE item_id IN ({marks}) "
            "GROUP BY item_id",
            item_ids,
        ).fetchall()
    return {r["item_id"]: r["n"] for r in rows}


def get_all_roles() -> list[str]:
    """DBに登録されている役割一覧を返す（共通を除く）。"""
    with eval_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT section FROM eval_items WHERE section != '共通' ORDER BY section"
        ).fetchall()
    return [r["section"] for r in rows]


# ---------------------------------------------------------------------------
# 評価データの読み込み
# ---------------------------------------------------------------------------
def load_evaluations() -> list[dict]:
    """全評価を合計点つきで新しい順に返す。"""
    with eval_conn() as conn:
        rows = conn.execute("""
            SELECT e.*,
                   (SELECT COALESCE(SUM(es.score), 0) FROM eval_scores es
                     WHERE es.evaluation_id = e.id) AS total_score
            FROM evaluations e ORDER BY e.created_at DESC
        """).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["rate"] = achievement_rate(d["total_score"], d["max_total"])
        d["rank"] = get_rank(d["total_score"], d["max_total"])
        result.append(d)
    return result


def load_evaluation_detail(evaluation_id: int) -> dict:
    """1件の評価の項目別得点・設問別回答・総合設問をまとめて返す。"""
    with eval_conn() as conn:
        scores = conn.execute(
            "SELECT * FROM eval_scores WHERE evaluation_id = ? ORDER BY id", (evaluation_id,),
        ).fetchall()
        answers = conn.execute(
            "SELECT * FROM eval_answers WHERE evaluation_id = ? ORDER BY id", (evaluation_id,),
        ).fetchall()
        overall = conn.execute(
            "SELECT * FROM eval_overall WHERE evaluation_id = ? ORDER BY id", (evaluation_id,),
        ).fetchall()
    return {
        "scores": [dict(r) for r in scores],
        "answers": [dict(r) for r in answers],
        "overall": [dict(r) for r in overall],
    }


def _norm_name(text) -> str:
    """氏名比較用に空白（全角・半角）を除去する。"""
    return "".join(str(text or "").split())


def build_answer_matrix(employee: str, evals: list[dict]):
    """設問を行、評価者を列にした比較表を作る。

    回答者（評価者）と対象者が一致する評価＝自己評価は、列の一番左に置く。
    戻り値: (DataFrame, 自己評価の列名リスト, 他者評価の列名リスト)
    """
    self_cols, other_cols = [], []
    used_labels: dict[str, int] = {}
    for e in sorted(evals, key=lambda x: x["created_at"]):
        raw = (e["evaluator"] or "").strip()
        is_self = bool(_norm_name(raw)) and _norm_name(raw) == _norm_name(employee)
        label = f"{raw}（本人）" if is_self else (raw or "（評価者未記入）")
        # 同じ評価者が複数回評価している場合は日付を添えて区別する
        used_labels[label] = used_labels.get(label, 0) + 1
        if used_labels[label] > 1:
            label = f"{label} {e['created_at'][:10]}"
        (self_cols if is_self else other_cols).append((label, e))

    columns = self_cols + other_cols          # ← 自己評価が左端
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
        conn.execute("DELETE FROM evaluations WHERE id = ?", (evaluation_id,))


def save_evaluation(employee: str, role: str, period: str, evaluator: str,
                    choice_selections: dict, results: list[dict],
                    overall_answers: list[dict]) -> int:
    """評価1件を保存し、evaluation_id を返す。

    得点はここで算出する（入力アプリ側では採点結果を扱わない）。
    results の各要素は {"item", "answers", "comment"} を持ち、設問を持たない項目のみ
    "score"（直接入力された得点）を持つ。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    choice_field = json.dumps(choice_selections, ensure_ascii=False) if choice_selections else None
    max_total = sum(r["item"]["max_score"] for r in results)

    with eval_conn() as conn:
        cur = conn.execute(
            "INSERT INTO evaluations "
            "(employee, role, period, evaluator, choice_field, max_total, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (employee, role, period, evaluator, choice_field, max_total, now, now),
        )
        eval_id = cur.lastrowid
        for r in results:
            if r.get("score") is None:
                score, _ = questions_to_score([a["answer"] for a in r["answers"]],
                                              r["item"]["max_score"])
            else:
                score = r["score"]
            conn.execute(
                "INSERT INTO eval_scores (evaluation_id, item_num, item_name, score, comment) "
                "VALUES (?, ?, ?, ?, ?)",
                (eval_id, r["item"]["num"], r["item"]["name"], score, r["comment"]),
            )
            for a in r["answers"]:
                conn.execute(
                    "INSERT INTO eval_answers "
                    "(evaluation_id, item_id, item_name, qnum, question_text, answer) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (eval_id, a["item_id"], a["item_name"], a["qnum"], a["question_text"], a["answer"]),
                )
        for o in overall_answers:
            if o["answer_text"].strip():
                conn.execute(
                    "INSERT INTO eval_overall (evaluation_id, qnum, question_text, answer_text) "
                    "VALUES (?, ?, ?, ?)",
                    (eval_id, o["qnum"], o["question_text"], o["answer_text"].strip()),
                )
    return eval_id


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


def export_survey_to_json() -> str:
    """設問・判断基準をJSONファイルにエクスポートする（総合設問は既存内容を保持）。"""
    with eval_conn() as conn:
        items = conn.execute(
            "SELECT id, section, num, name, anchor_5, anchor_3, anchor_1, free_text "
            "FROM eval_items ORDER BY section, sort_order, num"
        ).fetchall()
        entries = []
        for it in items:
            qs = conn.execute(
                "SELECT qnum, text FROM survey_questions WHERE item_id = ? ORDER BY sort_order, id",
                (it["id"],),
            ).fetchall()
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
    """評価項目・設問をJSONにエクスポートし、git commit & push する。"""
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
