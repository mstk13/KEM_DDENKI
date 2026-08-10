"""材料管理のビジネスロジック。

見積比較、納品検収、在庫更新、消化率集計、見積PDF出力、納品書OCRを担う。
将来の DRF API 移行時にもそのまま使える。
"""

import base64
import json
import logging

from django.db.models import Sum
from django.utils import timezone

from apps.costs.services import create_material_cost_from_po_item
from apps.materials.models import (
    Inventory,
    PurchaseOrder,
    QuotationItem,
)

logger = logging.getLogger(__name__)


def compare_quotations(material_id, site_id=None):
    """同一材料の複数仕入先の見積を比較する。

    Returns:
        [{
            "supplier": Supplier,
            "unit_price": Decimal,
            "quantity": Decimal,
            "amount": Decimal,
            "quotation": Quotation,
        }, ...]
        ※ unit_price 昇順でソート
    """
    qs = QuotationItem.unscoped.filter(
        material_id=material_id,
        quotation__status__in=["received", "accepted"],
    ).select_related("quotation", "quotation__supplier")

    if site_id:
        qs = qs.filter(quotation__site_id=site_id)

    results = []
    for item in qs:
        results.append({
            "supplier": item.quotation.supplier,
            "unit_price": item.unit_price,
            "quantity": item.quantity,
            "amount": item.amount,
            "quotation": item.quotation,
        })

    return sorted(results, key=lambda x: x["unit_price"])


def inspect_delivery(delivery, inspected_by):
    """納品を検収する。在庫更新と原価計上を行う。"""
    delivery.inspected = True
    delivery.inspected_by = inspected_by
    delivery.inspected_at = timezone.now()
    delivery.save()

    # 在庫を更新
    for item in delivery.items.all():
        inv, _ = Inventory.unscoped.get_or_create(
            company=delivery.company,
            material=item.material,
            site=delivery.purchase_order.site,
            defaults={"quantity": 0},
        )
        inv.quantity += item.delivered_qty
        inv.save()

    # 発注書の原価計上（まだ計上されていない明細のみ）
    po = delivery.purchase_order
    for po_item in po.items.all():
        create_material_cost_from_po_item(po_item)

    # 発注ステータス更新
    _update_po_status(po)


def _update_po_status(po):
    """納品状況から発注ステータスを更新する。"""
    total_ordered = po.items.aggregate(t=Sum("quantity"))["t"] or 0
    total_delivered = sum(
        d.items.aggregate(t=Sum("delivered_qty"))["t"] or 0
        for d in po.deliveries.all()
    )

    if total_delivered >= total_ordered:
        po.status = PurchaseOrder.Status.RECEIVED
    elif total_delivered > 0:
        po.status = PurchaseOrder.Status.PARTIALLY_RECEIVED
    po.save(update_fields=["status"])


def get_site_material_consumption(site):
    """現場の材料消化率を取得する。

    Returns:
        [{
            "material": Material,
            "budget_qty": Decimal,
            "used_qty": Decimal,
            "pct": int,
        }, ...]
    """
    from apps.reports.models import DailyReportMaterial

    # 発注数量 = 予算として扱う
    ordered = (
        site.purchase_orders
        .filter(status__in=["ordered", "partially_received", "received"])
        .values("items__material__name", "items__material_id")
        .annotate(total=Sum("items__quantity"))
    )
    ordered_map = {r["items__material_id"]: r for r in ordered}

    # 使用数量 = 日報から集計
    used = (
        DailyReportMaterial.unscoped
        .filter(daily_report__site=site, material__isnull=False)
        .values("material__name", "material_id")
        .annotate(total=Sum("quantity_used"))
    )
    used_map = {r["material_id"]: r for r in used}

    all_ids = set(ordered_map.keys()) | set(used_map.keys())
    results = []
    for mid in all_ids:
        o = ordered_map.get(mid, {})
        u = used_map.get(mid, {})
        budget_qty = o.get("total", 0) or 0
        used_qty = u.get("total", 0) or 0
        pct = int(used_qty / budget_qty * 100) if budget_qty else 0
        name = o.get("items__material__name") or u.get("material__name", "")
        results.append({
            "material_name": name,
            "budget_qty": budget_qty,
            "used_qty": used_qty,
            "pct": pct,
        })

    return sorted(results, key=lambda x: -x["pct"])


# ── 見積書 PDF 出力 ──


def generate_quotation_pdf(output, quotation, items, user):
    """見積書をPDF出力する。reportlab使用。

    Args:
        output: HttpResponse or file-like object
        quotation: Quotation instance
        items: QuotationItem queryset
        user: 出力実行ユーザー
    """
    from decimal import Decimal

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    from reportlab.lib.styles import ParagraphStyle

    # 日本語フォント登録
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    FONT = "HeiseiKakuGo-W5"

    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    style_title = ParagraphStyle(
        "title", fontName=FONT, fontSize=18, alignment=1, spaceAfter=10 * mm,
    )
    style_normal = ParagraphStyle(
        "normal", fontName=FONT, fontSize=10, leading=14,
    )
    style_right = ParagraphStyle(
        "right", fontName=FONT, fontSize=10, alignment=2,
    )
    style_small = ParagraphStyle(
        "small", fontName=FONT, fontSize=8, textColor=colors.grey,
    )

    elements = []

    # タイトル
    elements.append(Paragraph("見 積 書", style_title))
    elements.append(Spacer(1, 5 * mm))

    # ヘッダー情報
    supplier_name = str(quotation.supplier) if quotation.supplier else ""
    header_data = [
        [
            Paragraph(f"<b>{supplier_name} 御中</b>", style_normal),
            Paragraph(f"見積日: {quotation.quotation_date}", style_right),
        ],
        [
            Paragraph(f"現場: {quotation.site or '—'}", style_normal),
            Paragraph(
                f"有効期限: {quotation.valid_until or '—'}",
                style_right,
            ),
        ],
    ]
    header_table = Table(header_data, colWidths=[90 * mm, 80 * mm])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 5 * mm))

    # 合計金額
    total_str = f"¥{int(quotation.total_amount):,}"
    elements.append(Paragraph(
        f'<b>合計金額: {total_str}</b>',
        ParagraphStyle("total", fontName=FONT, fontSize=14, alignment=0),
    ))
    elements.append(Spacer(1, 5 * mm))

    # 明細テーブル
    table_data = [["No.", "品名", "数量", "単価", "金額"]]
    for i, item in enumerate(items, 1):
        name = str(item.material) if item.material else item.material_name
        qty = f"{item.quantity:,.2f}"
        price = f"¥{int(item.unit_price):,}"
        amount = f"¥{int(item.amount):,}"
        table_data.append([str(i), name, qty, price, amount])

    # 合計行
    table_data.append(["", "", "", "合計", total_str])

    col_widths = [10 * mm, 70 * mm, 25 * mm, 30 * mm, 35 * mm]
    detail_table = Table(table_data, colWidths=col_widths)
    detail_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a2744")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8f9fa")]),
        ("FONTNAME", (0, -1), (-1, -1), FONT),
        ("FONTSIZE", (0, -1), (-1, -1), 10),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e9ecef")),
    ]))
    elements.append(detail_table)
    elements.append(Spacer(1, 10 * mm))

    # 備考
    if quotation.notes:
        elements.append(Paragraph("備考:", style_normal))
        elements.append(Paragraph(quotation.notes, style_normal))
        elements.append(Spacer(1, 5 * mm))

    # フッター
    company_name = str(user.company) if user.company else ""
    elements.append(Spacer(1, 10 * mm))
    elements.append(Paragraph(company_name, style_right))
    elements.append(Paragraph(f"出力者: {user.get_full_name() or user.username}", style_small))

    doc.build(elements)


# ── 納品書 画像OCR ──


def extract_delivery_items_from_image(delivery, purchase_order, company):
    """納品書画像からClaude APIで明細を読み取り、DeliveryItemを生成する。

    Args:
        delivery: Delivery instance (image フィールドに画像がセットされている)
        purchase_order: PurchaseOrder instance
        company: Company instance

    Returns:
        list[DeliveryItem]: 生成された DeliveryItem のリスト
    """
    import os

    from django.conf import settings

    try:
        import anthropic
    except ImportError:
        raise ImportError("anthropic がインストールされていません。")

    api_key = getattr(settings, "ANTHROPIC_API_KEY", None) or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY が設定されていません。")

    # 画像をbase64エンコード
    image_path = delivery.image.path
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    # 拡張子からメディアタイプを判定
    ext = os.path.splitext(image_path)[1].lower()
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_type_map.get(ext, "image/jpeg")

    # PO明細の材料リストをプロンプトに含める（マッチング精度向上）
    po_items = purchase_order.items.select_related("material").all()
    material_list = "\n".join(
        f"- ID:{item.material.pk} 材料名:{item.material.name} 発注数量:{item.quantity}"
        for item in po_items
    )

    prompt = f"""この画像は納品書です。以下の情報を読み取ってJSON形式で返してください。

読み取る項目:
- items: 納品された品目のリスト。各品目について:
  - material_name: 品名
  - delivered_qty: 納品数量（数値）

以下は発注時の材料リストです。可能な限りこのリストの材料名とマッチさせてください:
{material_list}

JSONのみを返してください。説明文は不要です。
形式:
{{
  "items": [
    {{"material_name": "...", "delivered_qty": 数値}},
    ...
  ]
}}"""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_data,
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }],
    )

    raw_text = message.content[0].text
    delivery.extraction_raw = raw_text
    delivery.save(update_fields=["extraction_raw"])

    # JSONをパース
    parsed = _parse_json_response(raw_text)
    extracted_items = parsed.get("items", [])

    # DeliveryItemを生成
    from apps.materials.models import DeliveryItem, Material

    created_items = []
    for ext_item in extracted_items:
        material_name = ext_item.get("material_name", "")
        delivered_qty = ext_item.get("delivered_qty", 0)

        if not material_name or not delivered_qty:
            continue

        # PO明細から材料をマッチング
        matched_po_item = None
        for po_item in po_items:
            if po_item.material.name in material_name or material_name in po_item.material.name:
                matched_po_item = po_item
                break

        if matched_po_item:
            material = matched_po_item.material
            ordered_qty = matched_po_item.quantity
        else:
            # マッチしない場合、材料名で部分一致検索
            material = Material.unscoped.filter(
                company=company, name__icontains=material_name,
            ).first()
            ordered_qty = 0

        if not material:
            logger.warning(f"材料マッチ失敗: {material_name}")
            continue

        from decimal import Decimal
        delivery_item = DeliveryItem.unscoped.create(
            company=company,
            created_by=delivery.created_by,
            delivery=delivery,
            material=material,
            ordered_qty=Decimal(str(ordered_qty)),
            delivered_qty=Decimal(str(delivered_qty)),
            is_ok=(Decimal(str(delivered_qty)) == Decimal(str(ordered_qty))),
        )
        created_items.append(delivery_item)

    return created_items


def _parse_json_response(text):
    """LLMレスポンスからJSON部分を抽出してパースする。"""
    if "```json" in text:
        start = text.index("```json") + len("```json")
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + len("```")
        end = text.index("```", start)
        text = text[start:end].strip()

    return json.loads(text)
