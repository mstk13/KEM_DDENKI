"""KEM_DDENKI 統合REST API

各アプリ (sagyo-nippou, bid_manager, material_manager) の
SQLiteデータベースを読み取り、外部アプリ (KEIHI等) へ公開するAPIサーバー。
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- DB パス ---
BASE_DIR = Path(__file__).resolve().parent.parent
NIPPOU_DB = Path(os.getenv("NIPPOU_DB_PATH", BASE_DIR / "sagyo-nippou" / "database.db"))
BID_DB = Path(os.getenv("BID_DB_PATH", BASE_DIR / "bid_manager" / "database.db"))

app = FastAPI(title="KEM_DDENKI API", description="電機屋 統合API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- DB接続ヘルパー ---
@contextmanager
def get_conn(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _dicts(rows) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


# ==========================================================================
# 現場 (Sites) API - sagyo-nippou DB
# ==========================================================================
@app.get("/api/v1/sites")
def list_sites(active_only: bool = False):
    """現場一覧を取得"""
    if not NIPPOU_DB.exists():
        return []
    sql = "SELECT * FROM sites"
    if active_only:
        sql += " WHERE status IN ('着工前', '施工中')"
    sql += " ORDER BY (status IN ('着工前','施工中')) DESC, name"
    with get_conn(NIPPOU_DB) as conn:
        return _dicts(conn.execute(sql).fetchall())


@app.get("/api/v1/sites/{site_id}")
def get_site(site_id: int):
    """現場詳細を取得"""
    if not NIPPOU_DB.exists():
        raise HTTPException(status_code=404, detail="現場が見つかりません")
    with get_conn(NIPPOU_DB) as conn:
        row = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="現場が見つかりません")
        return dict(row)


# ==========================================================================
# プロジェクト (Projects) API - bid_manager DB
# ==========================================================================
@app.get("/api/v1/projects")
def list_projects(status: str | None = None):
    """入札プロジェクト一覧を取得"""
    if not BID_DB.exists():
        return []
    sql = "SELECT * FROM projects"
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY updated_at DESC"
    with get_conn(BID_DB) as conn:
        return _dicts(conn.execute(sql, params).fetchall())


@app.get("/api/v1/projects/{project_id}")
def get_project(project_id: int):
    """プロジェクト詳細を取得"""
    if not BID_DB.exists():
        raise HTTPException(status_code=404, detail="プロジェクトが見つかりません")
    with get_conn(BID_DB) as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="プロジェクトが見つかりません")
        return dict(row)


@app.get("/api/v1/projects/{project_id}/costs")
def get_project_costs(project_id: int):
    """プロジェクトの原価情報を取得"""
    if not BID_DB.exists():
        raise HTTPException(status_code=404, detail="プロジェクトが見つかりません")
    with get_conn(BID_DB) as conn:
        row = conn.execute(
            "SELECT * FROM costs WHERE project_id = ?", (project_id,)
        ).fetchone()
        if not row:
            return None
        return dict(row)


# ==========================================================================
# 経費連携 API - KEIHIから経費データを受け取り、原価に反映
# ==========================================================================
class ExpenseSync(BaseModel):
    keihi_expense_id: int
    date: str | None = None
    amount: int | None = None
    tax: int | None = None
    store_name: str | None = None
    category: str | None = None
    memo: str | None = None
    site_id: int | None = None
    project_id: int | None = None


class ExpenseSyncBatch(BaseModel):
    expenses: list[ExpenseSync]


@app.post("/api/v1/expenses/sync")
def sync_expenses(batch: ExpenseSyncBatch):
    """KEIHIから経費データを受け取り、プロジェクトの実績原価を更新する"""
    results = []
    for expense in batch.expenses:
        result = {"keihi_expense_id": expense.keihi_expense_id, "status": "skipped"}

        # プロジェクトIDがある場合、bid_managerの原価を更新
        if expense.project_id and expense.amount and BID_DB.exists():
            with get_conn(BID_DB) as conn:
                # 既存の原価レコードを確認
                cost_row = conn.execute(
                    "SELECT * FROM costs WHERE project_id = ?", (expense.project_id,)
                ).fetchone()

                if cost_row:
                    # 実績原価に加算
                    current_actual = cost_row["actual_cost"] or 0
                    new_actual = current_actual + expense.amount
                    estimate = cost_row["estimate_amount"] or 0
                    profit = estimate - new_actual
                    profit_rate = (profit / estimate * 100) if estimate > 0 else 0

                    conn.execute(
                        "UPDATE costs SET actual_cost = ?, profit = ?, profit_rate = ?, "
                        "memo = COALESCE(memo, '') || ?, updated_at = ? WHERE project_id = ?",
                        (
                            new_actual, profit, round(profit_rate, 2),
                            f"\n[KEIHI #{expense.keihi_expense_id}] {expense.store_name or ''} ¥{expense.amount}",
                            datetime.now().isoformat(timespec="seconds"),
                            expense.project_id,
                        ),
                    )
                    conn.commit()
                    result["status"] = "updated"
                    result["new_actual_cost"] = new_actual
                else:
                    # 原価レコードが無ければ新規作成
                    conn.execute(
                        "INSERT INTO costs (project_id, estimate_amount, actual_cost, profit, profit_rate, memo, updated_at) "
                        "VALUES (?, 0, ?, ?, ?, ?, ?)",
                        (
                            expense.project_id, expense.amount, -expense.amount, 0,
                            f"[KEIHI #{expense.keihi_expense_id}] {expense.store_name or ''} ¥{expense.amount}",
                            datetime.now().isoformat(timespec="seconds"),
                        ),
                    )
                    conn.commit()
                    result["status"] = "created"
                    result["new_actual_cost"] = expense.amount

        results.append(result)

    return {"synced": len([r for r in results if r["status"] != "skipped"]), "results": results}


# ==========================================================================
# ヘルスチェック
# ==========================================================================
@app.get("/api/v1/health")
def health():
    return {
        "status": "ok",
        "databases": {
            "nippou": NIPPOU_DB.exists(),
            "bid_manager": BID_DB.exists(),
        },
    }
