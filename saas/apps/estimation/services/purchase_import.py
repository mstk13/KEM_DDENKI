"""仕入実績の CSV インポートサービス。

CSVフォーマット（ヘッダー行あり）:
    仕入日,品名,品番,数量,単位,単価,金額,仕入先名,備考

raw_name と raw_code は必ず保持する。
名寄せは後から何度でもやり直せる必要がある。
"""

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from apps.estimation.models import PurchaseRecord
from apps.estimation.services.matching import match_item


def parse_purchase_csv(file_content: str) -> list[dict]:
    """CSV をパースしてレコードリストを返す。"""
    reader = csv.DictReader(io.StringIO(file_content))
    records = []

    for row in reader:
        try:
            purchase_date = datetime.strptime(
                row.get("仕入日", "").strip(), "%Y-%m-%d",
            ).date()
        except ValueError:
            try:
                purchase_date = datetime.strptime(
                    row.get("仕入日", "").strip(), "%Y/%m/%d",
                ).date()
            except ValueError:
                continue

        try:
            quantity = Decimal(row.get("数量", "0").strip())
            unit_price = Decimal(row.get("単価", "0").strip())
        except (InvalidOperation, ValueError):
            continue

        raw_name = row.get("品名", "").strip()
        if not raw_name:
            continue

        amount_str = row.get("金額", "").strip()
        try:
            amount = Decimal(amount_str) if amount_str else quantity * unit_price
        except (InvalidOperation, ValueError):
            amount = quantity * unit_price

        records.append({
            "purchase_date": purchase_date,
            "raw_name": raw_name,
            "raw_code": row.get("品番", "").strip(),
            "quantity": quantity,
            "unit": row.get("単位", "").strip(),
            "unit_price": unit_price,
            "amount": amount,
            "supplier_name": row.get("仕入先名", "").strip(),
            "notes": row.get("備考", "").strip(),
        })

    return records


def import_purchase_records(
    file_content: str,
    company,
    *,
    project=None,
    auto_match: bool = True,
) -> dict:
    """CSV から仕入実績をインポートする。

    auto_match=True の場合、名寄せマッチングも同時に実行する。

    Returns:
        {"created": int, "matched": int, "total": int, "batch_id": str}
    """
    batch_id = f"purchase_{date.today().isoformat()}"
    records = parse_purchase_csv(file_content)

    created = 0
    matched = 0

    for rec in records:
        pr = PurchaseRecord.unscoped.create(  # unscoped: company を明示指定
            company=company,
            raw_name=rec["raw_name"],
            raw_code=rec["raw_code"],
            purchase_date=rec["purchase_date"],
            quantity=rec["quantity"],
            unit=rec["unit"],
            unit_price=rec["unit_price"],
            amount=rec["amount"],
            project=project,
            import_source=PurchaseRecord.ImportSource.CSV,
            import_batch=batch_id,
            data_scope="tenant",
            notes=rec["notes"],
        )
        created += 1

        if auto_match and rec["raw_name"]:
            alias = match_item(
                raw_name=rec["raw_name"],
                source_type="supplier_quote",
                source_key=rec["raw_code"],
                company=company,
            )
            if alias.estimation_item:
                pr.estimation_item = alias.estimation_item
                pr.save(update_fields=["estimation_item", "updated_at"])
                matched += 1

    return {
        "created": created,
        "matched": matched,
        "total": len(records),
        "batch_id": batch_id,
    }
