"""開発管理 — DBアクセス層。

スキーマ: dev.*
  dev.projects   — プロジェクト
  dev.tasks      — タスク（チケット）
  dev.comments   — タスクへのコメント
"""
from __future__ import annotations

import sys
from datetime import datetime, date
from pathlib import Path
from typing import Any

import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from dbconn import get_conn  # noqa: E402


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _dicts(rows) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def init_db() -> None:
    """スキーマとテーブルを作成。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS dev")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dev.projects (
                    id          SERIAL PRIMARY KEY,
                    name        TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    status      TEXT NOT NULL DEFAULT '進行中',
                    assignee    TEXT DEFAULT '',
                    repo_url    TEXT DEFAULT '',
                    start_date  DATE,
                    due_date    DATE,
                    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dev.tasks (
                    id           SERIAL PRIMARY KEY,
                    project_id   INTEGER NOT NULL REFERENCES dev.projects(id) ON DELETE CASCADE,
                    title        TEXT NOT NULL,
                    description  TEXT DEFAULT '',
                    status       TEXT NOT NULL DEFAULT 'open',
                    priority     TEXT NOT NULL DEFAULT 'medium',
                    category     TEXT NOT NULL DEFAULT 'feature',
                    assignee     TEXT DEFAULT '',
                    reporter     TEXT DEFAULT '',
                    due_date     DATE,
                    estimate_h   REAL,
                    actual_h     REAL,
                    sort_order   INTEGER NOT NULL DEFAULT 0,
                    created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at   TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dev.comments (
                    id         SERIAL PRIMARY KEY,
                    task_id    INTEGER NOT NULL REFERENCES dev.tasks(id) ON DELETE CASCADE,
                    author     TEXT NOT NULL DEFAULT '',
                    body       TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_dev_tasks_project ON dev.tasks(project_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_dev_tasks_status ON dev.tasks(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_dev_comments_task ON dev.comments(task_id)")
            # マイグレーション: projects.assignee カラム追加
            cur.execute("""
                DO $$ BEGIN
                    ALTER TABLE dev.projects ADD COLUMN assignee TEXT DEFAULT '';
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$
            """)


# ---------------------------------------------------------------------------
# プロジェクト
# ---------------------------------------------------------------------------
def list_projects(active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM dev.projects"
    if active_only:
        sql += " WHERE status IN ('進行中', '計画中')"
    sql += " ORDER BY created_at DESC"
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(sql)
            return _dicts(cur.fetchall())


def get_project(project_id: int) -> dict | None:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM dev.projects WHERE id = %s", (project_id,))
            r = cur.fetchone()
            return dict(r) if r else None


def add_project(name: str, description: str = "", assignee: str = "",
                repo_url: str = "", start_date=None, due_date=None) -> int:
    now = _now()
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("""
                INSERT INTO dev.projects (name, description, assignee, repo_url, start_date, due_date, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (name, description, assignee, repo_url, start_date, due_date, now, now))
            return cur.fetchone()["id"]


def update_project(project_id: int, **fields) -> None:
    allowed = {"name", "description", "status", "assignee", "repo_url", "start_date", "due_date"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    sets["updated_at"] = _now()
    clause = ", ".join(f"{k} = %s" for k in sets)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE dev.projects SET {clause} WHERE id = %s",
                        (*sets.values(), project_id))


def delete_project(project_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM dev.projects WHERE id = %s", (project_id,))


# ---------------------------------------------------------------------------
# タスク
# ---------------------------------------------------------------------------
TASK_STATUSES = ["open", "in_progress", "review", "done", "closed"]
TASK_PRIORITIES = ["low", "medium", "high", "critical"]
TASK_CATEGORIES = ["feature", "bug", "refactor", "docs", "test", "infra", "other"]

STATUS_LABELS = {
    "open": "未着手", "in_progress": "作業中", "review": "レビュー中",
    "done": "完了", "closed": "クローズ",
}
PRIORITY_LABELS = {
    "low": "低", "medium": "中", "high": "高", "critical": "緊急",
}
CATEGORY_LABELS = {
    "feature": "機能追加", "bug": "バグ修正", "refactor": "リファクタ",
    "docs": "ドキュメント", "test": "テスト", "infra": "インフラ", "other": "その他",
}


def list_tasks(project_id: int, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM dev.tasks WHERE project_id = %s"
    params: list[Any] = [project_id]
    if status:
        sql += " AND status = %s"
        params.append(status)
    sql += " ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, sort_order, id"
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(sql, params)
            return _dicts(cur.fetchall())


def get_task(task_id: int) -> dict | None:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM dev.tasks WHERE id = %s", (task_id,))
            r = cur.fetchone()
            return dict(r) if r else None


def add_task(project_id: int, title: str, description: str = "",
             priority: str = "medium", category: str = "feature",
             assignee: str = "", reporter: str = "",
             due_date=None, estimate_h=None) -> int:
    now = _now()
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 AS nxt FROM dev.tasks WHERE project_id = %s",
                        (project_id,))
            nxt = cur.fetchone()["nxt"]
            cur.execute("""
                INSERT INTO dev.tasks
                (project_id, title, description, priority, category, assignee, reporter,
                 due_date, estimate_h, sort_order, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """, (project_id, title, description, priority, category, assignee, reporter,
                  due_date, estimate_h, nxt, now, now))
            return cur.fetchone()["id"]


def update_task(task_id: int, **fields) -> None:
    allowed = {"title", "description", "status", "priority", "category",
               "assignee", "reporter", "due_date", "estimate_h", "actual_h", "sort_order"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    sets["updated_at"] = _now()
    clause = ", ".join(f"{k} = %s" for k in sets)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE dev.tasks SET {clause} WHERE id = %s",
                        (*sets.values(), task_id))


def delete_task(task_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM dev.tasks WHERE id = %s", (task_id,))


def get_project_stats(project_id: int) -> dict:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'done' OR status = 'closed') AS completed,
                    COUNT(*) FILTER (WHERE status = 'open') AS open_count,
                    COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress,
                    COUNT(*) FILTER (WHERE status = 'review') AS review,
                    COUNT(*) FILTER (WHERE priority = 'critical' AND status NOT IN ('done','closed')) AS critical,
                    COUNT(*) FILTER (WHERE category = 'bug' AND status NOT IN ('done','closed')) AS open_bugs,
                    COALESCE(SUM(estimate_h), 0) AS total_estimate,
                    COALESCE(SUM(actual_h), 0) AS total_actual
                FROM dev.tasks WHERE project_id = %s
            """, (project_id,))
            return dict(cur.fetchone())


# ---------------------------------------------------------------------------
# コメント
# ---------------------------------------------------------------------------
def list_comments(task_id: int) -> list[dict]:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM dev.comments WHERE task_id = %s ORDER BY created_at", (task_id,))
            return _dicts(cur.fetchall())


def add_comment(task_id: int, author: str, body: str) -> int:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("""
                INSERT INTO dev.comments (task_id, author, body, created_at)
                VALUES (%s, %s, %s, %s) RETURNING id
            """, (task_id, author, body, _now()))
            return cur.fetchone()["id"]


# ---------------------------------------------------------------------------
# 従業員一覧（担当者選択用）
# ---------------------------------------------------------------------------
def list_members() -> list[str]:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT name FROM master.employees WHERE is_active = TRUE ORDER BY code")
            return [r["name"] for r in cur.fetchall()]


if __name__ == "__main__":
    init_db()
    print("開発管理 DB 初期化完了")
