"""コスト分析エンジン — 過去実績から最適調達を提案"""
import sqlite3
from datetime import date, timedelta

DATABASE = "construction.db"


def get_conn():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def analyze_item_costs(item_id=None):
    """品目ごとのコスト分析（全品目 or 指定品目）

    Returns: list of dict
        item_id, item_name, spec, unit,
        avg_price, min_price, max_price, latest_price,
        best_supplier, best_supplier_avg,
        avg_transport, total_orders
    """
    conn = get_conn()

    where = "WHERE o.item_id = ?" if item_id else ""
    params = (item_id,) if item_id else ()

    rows = conn.execute(f"""
        SELECT
            im.id AS item_id,
            im.name AS item_name,
            im.spec,
            im.unit,
            COUNT(o.id) AS total_orders,
            AVG(o.unit_price) AS avg_price,
            MIN(o.unit_price) AS min_price,
            MAX(o.unit_price) AS max_price,
            -- 直近の単価
            (SELECT o2.unit_price FROM "order" o2
             WHERE o2.item_id = im.id ORDER BY o2.order_date DESC LIMIT 1) AS latest_price,
            -- 最安仕入先
            (SELECT s.name FROM "order" o3
             JOIN supplier s ON s.id = o3.supplier_id
             WHERE o3.item_id = im.id AND o3.supplier_id IS NOT NULL
             GROUP BY o3.supplier_id
             ORDER BY AVG(o3.unit_price) ASC LIMIT 1) AS best_supplier,
            -- 最安仕入先の平均単価
            (SELECT AVG(o4.unit_price) FROM "order" o4
             WHERE o4.item_id = im.id AND o4.supplier_id = (
                 SELECT o5.supplier_id FROM "order" o5
                 WHERE o5.item_id = im.id AND o5.supplier_id IS NOT NULL
                 GROUP BY o5.supplier_id
                 ORDER BY AVG(o5.unit_price) ASC LIMIT 1
             )) AS best_supplier_avg,
            -- 平均輸送費（付帯コスト）
            COALESCE((SELECT AVG(oc.amount) FROM order_cost oc
             JOIN "order" o6 ON o6.id = oc.order_id
             WHERE o6.item_id = im.id AND oc.cost_type = '輸送費'), 0) AS avg_transport
        FROM item_master im
        JOIN "order" o ON o.item_id = im.id
        {where}
        GROUP BY im.id
        HAVING total_orders >= 1
        ORDER BY im.name
    """, params).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def get_supplier_comparison(item_id):
    """特定品目の業者別単価比較"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            s.id AS supplier_id,
            s.name AS supplier_name,
            COUNT(o.id) AS order_count,
            AVG(o.unit_price) AS avg_price,
            MIN(o.unit_price) AS min_price,
            MAX(o.unit_price) AS max_price,
            MAX(o.order_date) AS last_order_date,
            COALESCE(AVG(oc.amount), 0) AS avg_transport
        FROM "order" o
        JOIN supplier s ON s.id = o.supplier_id
        LEFT JOIN order_cost oc ON oc.order_id = o.id AND oc.cost_type = '輸送費'
        WHERE o.item_id = ? AND o.supplier_id IS NOT NULL
        GROUP BY s.id
        ORDER BY (AVG(o.unit_price) + COALESCE(AVG(oc.amount), 0)) ASC
    """, (item_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def generate_estimate_suggestion(project_id):
    """見積もり作成時の最適提案を生成

    現場の見積もり明細に対して、過去実績から最安の調達方法を提案。
    Returns: list of dict
        item_name, spec, unit, est_qty, est_unit_price, est_amount,
        suggested_price, suggested_supplier, savings, savings_pct,
        avg_transport_per_unit
    """
    conn = get_conn()

    # この現場の最新見積もり明細を取得
    header = conn.execute(
        "SELECT id FROM estimate_header WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,)
    ).fetchone()

    if not header:
        conn.close()
        return []

    lines = conn.execute("""
        SELECT el.*, im.name AS item_name, im.spec, im.unit
        FROM estimate_line el
        JOIN item_master im ON im.id = el.item_id
        WHERE el.header_id = ?
        ORDER BY el.sort_order
    """, (header["id"],)).fetchall()

    suggestions = []
    for line in lines:
        item_id = line["item_id"]

        # 過去の発注実績を分析
        stats = conn.execute("""
            SELECT
                COUNT(*) AS cnt,
                AVG(o.unit_price) AS avg_price,
                MIN(o.unit_price) AS min_price
            FROM "order" o
            WHERE o.item_id = ?
        """, (item_id,)).fetchone()

        # 最安仕入先
        best = conn.execute("""
            SELECT s.name, AVG(o.unit_price) AS avg_price
            FROM "order" o
            JOIN supplier s ON s.id = o.supplier_id
            WHERE o.item_id = ? AND o.supplier_id IS NOT NULL
            GROUP BY o.supplier_id
            ORDER BY AVG(o.unit_price) ASC
            LIMIT 1
        """, (item_id,)).fetchone()

        # 輸送費の平均（1注文あたり→1単位あたりに変換）
        transport = conn.execute("""
            SELECT AVG(oc.amount) AS avg_transport, AVG(o.quantity) AS avg_qty
            FROM order_cost oc
            JOIN "order" o ON o.id = oc.order_id
            WHERE o.item_id = ? AND oc.cost_type = '輸送費'
        """, (item_id,)).fetchone()

        avg_transport_per_unit = 0
        if transport and transport["avg_transport"] and transport["avg_qty"] and transport["avg_qty"] > 0:
            avg_transport_per_unit = transport["avg_transport"] / transport["avg_qty"]

        suggested_price = line["unit_price"]
        suggested_supplier = ""
        savings = 0

        if stats["cnt"] and stats["cnt"] > 0 and best:
            suggested_price = int(best["avg_price"])
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

    conn.close()
    return suggestions
