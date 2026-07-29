"""人材管理 — master.employees の CRUD。"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from dbconn import get_conn  # noqa: E402

import config


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _dicts(rows) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# 初期化 / JSON 復元
# ------------------------------------------------------------------
def init_db() -> None:
    """employees が空なら JSON から復元する。"""
    _restore_if_empty()


def _restore_if_empty() -> None:
    if not config.EMPLOYEES_JSON.exists():
        return
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM master.employees")
            if cur.fetchone()["cnt"] > 0:
                return
    try:
        records = json.loads(config.EMPLOYEES_JSON.read_text(encoding="utf-8"))
        for rec in records:
            add_employee(**rec)
        print(f"社員マスターを {config.EMPLOYEES_JSON} から {len(records)} 件復元しました。")
    except Exception as exc:
        print(f"社員マスターの復元に失敗: {exc}")


def save_to_json() -> None:
    """現在の DB 内容を JSON にエクスポート。"""
    emps = list_employees()
    records = []
    for e in emps:
        records.append({
            "code": e["code"],
            "name": e["name"],
            "kana": e.get("kana") or "",
            "department": e.get("department") or "",
            "position": e.get("position") or "",
            "role": e.get("role") or "",
            "phone": e.get("phone") or "",
            "is_active": bool(e["is_active"]),
            "note": e.get("note") or "",
        })
    config.EMPLOYEES_JSON.parent.mkdir(parents=True, exist_ok=True)
    config.EMPLOYEES_JSON.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"社員マスターを {config.EMPLOYEES_JSON} に {len(records)} 件保存しました。")


# ------------------------------------------------------------------
# CRUD
# ------------------------------------------------------------------
def add_employee(*, code: str = "", name: str, kana: str = "",
                 department: str = "", position: str = "", role: str = "",
                 phone: str = "", is_active: bool = True, note: str = "") -> int:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                """INSERT INTO master.employees
                   (code, name, kana, department, position, role, phone, is_active, note, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (name) DO UPDATE SET
                       code = COALESCE(NULLIF(EXCLUDED.code, ''), master.employees.code),
                       kana = COALESCE(NULLIF(EXCLUDED.kana, ''), master.employees.kana),
                       department = COALESCE(NULLIF(EXCLUDED.department, ''), master.employees.department),
                       position = COALESCE(NULLIF(EXCLUDED.position, ''), master.employees.position),
                       role = COALESCE(NULLIF(EXCLUDED.role, ''), master.employees.role),
                       phone = COALESCE(NULLIF(EXCLUDED.phone, ''), master.employees.phone),
                       note = COALESCE(NULLIF(EXCLUDED.note, ''), master.employees.note)
                   RETURNING id""",
                (code, name, kana, department, position, role, phone,
                 is_active, note, _now()),
            )
            return cur.fetchone()["id"]


def update_employee(emp_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = %s" for k in fields)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE master.employees SET {cols} WHERE id = %s",
                        (*fields.values(), emp_id))


def delete_employee(emp_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM master.employees WHERE id = %s", (emp_id,))


def get_employee(emp_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("SELECT * FROM master.employees WHERE id = %s", (emp_id,))
            r = cur.fetchone()
            return dict(r) if r else None


def list_employees(active_only: bool = False, role: str | None = None) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if active_only:
        where.append("is_active = TRUE")
    if role:
        where.append("role = %s")
        params.append(role)
    sql = "SELECT * FROM master.employees"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY COALESCE(NULLIF(kana, ''), name), name"
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(sql, params)
            return _dicts(cur.fetchall())


if __name__ == "__main__":
    init_db()
    print("人材管理 DB 初期化完了 (PostgreSQL)")
