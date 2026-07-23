"""SQLite スキーマと CRUD。

営業に来た人の「会社名・担当者名・営業内容」を一覧管理するためのテーブル。
金額や日付は将来の集計・分析に備えて素直な型で保存する。
"""
import sqlite3
from datetime import datetime, date

from config import DB_PATH, DEFAULT_STATUS, DEFAULT_INDUSTRY


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """テーブルを作成（初回のみ）。既存DBには不足カラムを追加。"""
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS visits (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                industry      TEXT NOT NULL DEFAULT 'その他', -- 業界カテゴリ
                company_name  TEXT NOT NULL DEFAULT '',   -- 会社名
                rep_name      TEXT NOT NULL DEFAULT '',   -- 営業担当者名
                business_overview TEXT NOT NULL DEFAULT '', -- 事業概要（会社が何をしているか）
                sales_content TEXT NOT NULL DEFAULT '',   -- 営業内容（今回の売り込み）
                phone         TEXT NOT NULL DEFAULT '',   -- 電話番号
                email         TEXT NOT NULL DEFAULT '',   -- メールアドレス
                website       TEXT NOT NULL DEFAULT '',   -- 公式HPのURL
                address       TEXT NOT NULL DEFAULT '',   -- 住所
                visit_date    DATE,                       -- 訪問日（資料の日付）
                received_date DATE,                       -- 受領日（資料を受け取った日）
                source_file   TEXT NOT NULL DEFAULT '',   -- 元の資料ファイルのパス
                status        TEXT NOT NULL DEFAULT '下書き',
                memo          TEXT NOT NULL DEFAULT '',
                created_at    DATETIME NOT NULL,
                updated_at    DATETIME NOT NULL
            )
            """
        )
        # 既存DBへのマイグレーション（不足カラムを追加）
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(visits)").fetchall()}
        if "industry" not in cols:
            conn.execute("ALTER TABLE visits ADD COLUMN industry TEXT NOT NULL DEFAULT 'その他'")
        if "business_overview" not in cols:
            conn.execute("ALTER TABLE visits ADD COLUMN business_overview TEXT NOT NULL DEFAULT ''")
        if "website" not in cols:
            conn.execute("ALTER TABLE visits ADD COLUMN website TEXT NOT NULL DEFAULT ''")
    print(f"DB 初期化完了: {DB_PATH}")


def add_visit(**fields):
    """1件登録して id を返す。未指定のカラムは既定値。"""
    now = datetime.now().isoformat(timespec="seconds")
    row = {
        "industry": DEFAULT_INDUSTRY,
        "company_name": "",
        "rep_name": "",
        "business_overview": "",
        "sales_content": "",
        "phone": "",
        "email": "",
        "website": "",
        "address": "",
        "visit_date": None,
        "received_date": date.today().isoformat(),
        "source_file": "",
        "status": DEFAULT_STATUS,
        "memo": "",
    }
    row.update({k: v for k, v in fields.items() if k in row})
    cols = list(row.keys()) + ["created_at", "updated_at"]
    vals = list(row.values()) + [now, now]
    placeholders = ", ".join("?" for _ in cols)
    with _conn() as conn:
        cur = conn.execute(
            f"INSERT INTO visits ({', '.join(cols)}) VALUES ({placeholders})", vals
        )
        return cur.lastrowid


def update_visit(visit_id, **fields):
    """任意のカラムを更新。"""
    allowed = {
        "industry", "company_name", "rep_name", "business_overview", "sales_content",
        "phone", "email", "website", "address", "visit_date", "received_date",
        "source_file", "status", "memo",
    }
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    sets["updated_at"] = datetime.now().isoformat(timespec="seconds")
    assignments = ", ".join(f"{k} = ?" for k in sets)
    with _conn() as conn:
        conn.execute(
            f"UPDATE visits SET {assignments} WHERE id = ?",
            list(sets.values()) + [visit_id],
        )


def delete_visit(visit_id):
    with _conn() as conn:
        conn.execute("DELETE FROM visits WHERE id = ?", (visit_id,))


def get_visit(visit_id):
    with _conn() as conn:
        r = conn.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone()
        return dict(r) if r else None


def get_visits(status=None, keyword=None, industry=None, company=None, order_by="received_date"):
    """一覧取得。status / keyword / industry / company で絞り込み。"""
    sql = "SELECT * FROM visits WHERE 1=1"
    params = []
    if status and status != "すべて":
        sql += " AND status = ?"
        params.append(status)
    if industry:
        sql += " AND industry = ?"
        params.append(industry)
    if company is not None:
        sql += " AND company_name = ?"
        params.append(company)
    if keyword:
        sql += " AND (company_name LIKE ? OR rep_name LIKE ? OR sales_content LIKE ?)"
        like = f"%{keyword}%"
        params += [like, like, like]
    order_col = order_by if order_by in {"received_date", "visit_date", "created_at", "company_name"} else "received_date"
    sql += f" ORDER BY {order_col} DESC, id DESC"
    with _conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_industry_counts():
    """業界ごとの件数（会社数・記録数）。件数の多い順。"""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT industry,
                   COUNT(DISTINCT company_name) AS companies,
                   COUNT(*) AS records
            FROM visits
            GROUP BY industry
            ORDER BY records DESC, industry
            """
        ).fetchall()
        return [dict(r) for r in rows]


def get_companies_in_industry(industry):
    """指定業界の会社一覧（会社名・記録数・最終受領日・事業概要）。

    事業概要は、その会社の記録のうち最新の空でないものを採用する。
    """
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT company_name,
                   COUNT(*) AS records,
                   MAX(received_date) AS last_received
            FROM visits
            WHERE industry = ?
            GROUP BY company_name
            ORDER BY last_received DESC, company_name
            """,
            (industry,),
        ).fetchall()
        overview = {}
        for r in conn.execute(
            """
            SELECT company_name, business_overview
            FROM visits
            WHERE industry = ? AND business_overview <> ''
            ORDER BY received_date ASC, id ASC
            """,
            (industry,),
        ).fetchall():
            overview[r["company_name"]] = r["business_overview"]  # 昇順なので最後＝最新
        result = []
        for r in rows:
            d = dict(r)
            d["business_overview"] = overview.get(r["company_name"], "")
            result.append(d)
        return result


def source_file_exists(path):
    """同じ元ファイルが既に取込済みか（重複取込の防止）。"""
    with _conn() as conn:
        r = conn.execute(
            "SELECT 1 FROM visits WHERE source_file = ? LIMIT 1", (path,)
        ).fetchone()
        return r is not None


def stats():
    """ダッシュボード用の集計。"""
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
        by_status = {
            r["status"]: r["c"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS c FROM visits GROUP BY status"
            ).fetchall()
        }
        this_month = conn.execute(
            "SELECT COUNT(*) FROM visits WHERE strftime('%Y-%m', received_date) = strftime('%Y-%m', 'now', 'localtime')"
        ).fetchone()[0]
        return {"total": total, "by_status": by_status, "this_month": this_month}


if __name__ == "__main__":
    init_db()
