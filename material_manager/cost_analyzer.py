"""コスト分析エンジン — 過去実績から最適調達を提案（PostgreSQL版）"""
import sys
from pathlib import Path

import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from db import get_conn  # noqa: E402


def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def analyze_item_costs(item_id=None):
    """品目ごとのコスト分析（全品目 or 指定品目）"""
    where = "WHERE o.item_id = %s" if item_id else ""
    params = (item_id,) if item_id else ()

    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(f"""
                SELECT
                    im.id AS item_id,
                    im.name AS item_name,
                    im.spec,
                    im.unit,
                    COUNT(o.id) AS total_orders,
                    AVG(o.unit_price) AS avg_price,
                    MIN(o.unit_price) AS min_price,
                    MAX(o.unit_price) AS max_price,
                    (SELECT o2.unit_price FROM material.orders o2
                     WHERE o2.item_id = im.id ORDER BY o2.order_date DESC LIMIT 1) AS latest_price,
                    (SELECT s.name FROM material.orders o3
                     JOIN master.suppliers s ON s.id = o3.supplier_id
                     WHERE o3.item_id = im.id AND o3.supplier_id IS NOT NULL
                     GROUP BY o3.supplier_id, s.name
                     ORDER BY AVG(o3.unit_price) ASC LIMIT 1) AS best_supplier,
                    (SELECT AVG(o4.unit_price) FROM material.orders o4
                     WHERE o4.item_id = im.id AND o4.supplier_id = (
                         SELECT o5.supplier_id FROM material.orders o5
                         WHERE o5.item_id = im.id AND o5.supplier_id IS NOT NULL
                         GROUP BY o5.supplier_id
                         ORDER BY AVG(o5.unit_price) ASC LIMIT 1
                     )) AS best_supplier_avg,
                    COALESCE((SELECT AVG(oc.amount) FROM material.order_cost oc
                     JOIN material.orders o6 ON o6.id = oc.order_id
                     WHERE o6.item_id = im.id AND oc.cost_type = '輸送費'), 0) AS avg_transport
                FROM material.item_master im
                JOIN material.orders o ON o.item_id = im.id
                {where}
                GROUP BY im.id, im.name, im.spec, im.unit
                HAVING COUNT(o.id) >= 1
                ORDER BY im.name
            """, params)
            return [dict(r) for r in cur.fetchall()]


def get_supplier_comparison(item_id):
    """特定品目の業者別単価比較"""
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute("""
                SELECT
                    s.id AS supplier_id,
                    s.name AS supplier_name,
                    COUNT(o.id) AS order_count,
                    AVG(o.unit_price) AS avg_price,
                    MIN(o.unit_price) AS min_price,
                    MAX(o.unit_price) AS max_price,
                    MAX(o.order_date)::TEXT AS last_order_date,
                    COALESCE(AVG(oc.amount), 0) AS avg_transport
                FROM material.orders o
                JOIN master.suppliers s ON s.id = o.supplier_id
                LEFT JOIN material.order_cost oc ON oc.order_id = o.id AND oc.cost_type = '輸送費'
                WHERE o.item_id = %s AND o.supplier_id IS NOT NULL
                GROUP BY s.id, s.name
                ORDER BY (AVG(o.unit_price) + COALESCE(AVG(oc.amount), 0)) ASC
            """, (item_id,))
            return [dict(r) for r in cur.fetchall()]


def generate_estimate_suggestion(project_id):
    """見積もり作成時の最適提案を生成"""
    with get_conn() as conn:
        with _cur(conn) as cur:
            cur.execute(
                "SELECT id FROM material.estimate_header WHERE project_id = %s ORDER BY version DESC LIMIT 1",
                (project_id,)
            )
            header = cur.fetchone()
            if not header:
                return []

            cur.execute("""
                SELECT el.*, im.name AS item_name, im.spec, im.unit
                FROM material.estimate_line el
                JOIN material.item_master im ON im.id = el.item_id
                WHERE el.header_id = %s
                ORDER BY el.sort_order
            """, (header["id"],))
            lines = cur.fetchall()

            suggestions = []
            for line in lines:
                item_id = line["item_id"]

                cur.execute("""
                    SELECT COUNT(*) AS cnt, AVG(o.unit_price) AS avg_price, MIN(o.unit_price) AS min_price
                    FROM material.orders o WHERE o.item_id = %s
                """, (item_id,))
                stats = cur.fetchone()

                cur.execute("""
                    SELECT s.name, AVG(o.unit_price) AS avg_price
                    FROM material.orders o
                    JOIN master.suppliers s ON s.id = o.supplier_id
                    WHERE o.item_id = %s AND o.supplier_id IS NOT NULL
                    GROUP BY o.supplier_id, s.name
                    ORDER BY AVG(o.unit_price) ASC LIMIT 1
                """, (item_id,))
                best = cur.fetchone()

                cur.execute("""
                    SELECT AVG(oc.amount) AS avg_transport, AVG(o.quantity) AS avg_qty
                    FROM material.order_cost oc
                    JOIN material.orders o ON o.id = oc.order_id
                    WHERE o.item_id = %s AND oc.cost_type = '輸送費'
                """, (item_id,))
                transport = cur.fetchone()

                avg_transport_per_unit = 0
                if transport and transport["avg_transport"] and transport["avg_qty"] and float(transport["avg_qty"]) > 0:
                    avg_transport_per_unit = float(transport["avg_transport"]) / float(transport["avg_qty"])

                suggested_price = line["unit_price"]
                suggested_supplier = ""
                savings = 0

                if stats["cnt"] and stats["cnt"] > 0 and best:
                    suggested_price = int(float(best["avg_price"]))
                    suggested_supplier = best["name"]
                    savings = (line["unit_price"] - suggested_price) * line["quantity"]

                suggestions.append({
                    "item_id": item_id,
                    "item_name": line["item_name"],
                    "spec": line["spec"],
                    "unit": line["unit"],
                    "est_qty": line["quantity"],
                    "est_unit_price": line["unit_price"],
                    "est_amount": line["amount"],
                    "suggested_price": suggested_price,
                    "suggested_supplier": suggested_supplier,
                    "avg_transport_per_unit": int(avg_transport_per_unit),
                    "total_suggested": int(suggested_price * line["quantity"] + avg_transport_per_unit * line["quantity"]),
                    "savings": int(savings),
                    "savings_pct": round(savings / line["amount"] * 100, 1) if line["amount"] > 0 else 0,
                    "order_count": stats["cnt"] or 0,
                })

            return suggestions
