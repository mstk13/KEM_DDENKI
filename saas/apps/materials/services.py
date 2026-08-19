"""材料管理のビジネスロジック。

見積比較、納品検収、在庫更新、消化率集計、見積PDF出力、納品書OCRを担う。
将来の DRF API 移行時にもそのまま使える。
"""

import base64
import logging
import re
import unicodedata
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.costs.services import create_material_cost_from_po_item
from apps.materials.models import (
    Inventory,
    Material,
    PurchaseOrder,
    Quotation,
    QuotationItem,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 見積ファイルから読み取った明細の登録
# ---------------------------------------------------------------------------


def normalize_material_name(name: str) -> str:
    """材料名の照合キー。表記ゆれを吸収する。

    「VVF 1.6mm 2C」「ＶＶＦ1.6MM2C」「VVF-1.6mm-2c」を同じものとして扱う。
    全角/半角・大小文字・空白・区切り記号の違いだけを潰す。数字や単位は
    落とさない（「1.6」と「2.0」は別物なので）。
    """
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", str(name)).lower()
    return re.sub(r"[\s　\-_/・,，.．()（）\[\]]", "", text)


def find_material_by_name(company, raw_name):
    """材料名から材料マスタを引き当てる。見つからなければ None。

    自動作成はしない — 表記ゆれで重複マスタが増えるほうが後で困る。
    引き当てられなかったものは確認画面に「未登録」として並べ、人が
    マスタを作るか自由入力のままにするかを選ぶ。
    得意先の引き当て（sites.services.find_customer_by_name）と同じ方針。
    """
    key = normalize_material_name(raw_name)
    if not key:
        return None

    # unscoped: 取り込み経路はテナントコンテキスト未設定で通ることがあるため
    # company を明示して絞る。
    for material in Material.unscoped.filter(company=company, is_active=True):
        if normalize_material_name(material.name) == key:
            return material
    return None


def match_lines_to_materials(company, lines: list[dict]) -> list[dict]:
    """明細に材料マスタの引き当て結果を添える。行は増減させない。

    引き当てられた行には material が入り、それ以外は None のまま。
    確認画面で「どれがマスタに無いのか」を出すために使う。
    """
    return [
        {**line, "material": find_material_by_name(company, line.get("name"))}
        for line in lines
    ]


def create_quotation_from_lines(
    *, company, user, site, customer, lines, quotation_date,
    quotation_number="", source_filename="", valid_until=None, notes="",
):
    """読み取った明細から自社発行の見積とその明細を作る。

    materials.Material への自動登録はしない。引き当てられた行だけ FK を張り、
    残りは material_name（自由入力）に読み取った名称をそのまま残す。
    後から材料マスタを整備したときに再照合できるよう、名称は必ず保持する。

    Returns:
        (Quotation, 作成した QuotationItem のリスト)
    """
    quotation = Quotation.objects.create(
        company=company,
        created_by=user,
        kind=Quotation.Kind.ISSUED,
        site=site,
        customer=customer,
        quotation_number=quotation_number,
        source_filename=source_filename,
        quotation_date=quotation_date,
        valid_until=valid_until,
        status=Quotation.Status.RECEIVED,
        notes=notes,
    )

    items = []
    for order, line in enumerate(lines):
        material = line.get("material")
        amount = line.get("amount") or Decimal("0")
        items.append(QuotationItem(
            company=company,
            created_by=user,
            quotation=quotation,
            material=material,
            # マスタに引き当てられても、読み取った名称は残す。マスタ名と
            # 見積書上の表記が違うとき、どちらで書かれていたかが後で要る。
            material_name=line.get("name") or "",
            spec=line.get("spec") or "",
            unit=line.get("unit") or "",
            quantity=line.get("quantity"),
            unit_price=line.get("unit_price"),
            amount=amount,
            remarks=line.get("remarks") or "",
            sort_order=order,
        ))
    QuotationItem.objects.bulk_create(items)

    # 合計は明細の積み上げで持つ。見積書の合計欄は値引きや消費税を含んで
    # いることがあり、明細の和と一致しない。ここでは明細の和を正とする。
    quotation.total_amount = sum((i.amount or Decimal("0")) for i in items)
    quotation.save(update_fields=["total_amount", "updated_at"])
    return quotation, items


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
        # 単価が読めていない明細（金額だけの一式計上など）は比較できない。
        # 0 として並べると最安に見えてしまうので、比較表から外す。
        if item.unit_price is None:
            continue
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

    # 調達実績を記録
    _create_procurement_records(delivery)

    # 発注ステータス更新
    _update_po_status(po)


def _create_procurement_records(delivery):
    """検収完了時に調達実績を自動記録する。"""
    from apps.materials.models import MaterialSupplier, ProcurementRecord

    po = delivery.purchase_order
    for item in delivery.items.select_related("material"):
        if not item.material:
            continue

        # PO明細から単価を取得
        po_item = po.items.filter(material=item.material).first()
        unit_price = po_item.unit_price if po_item else 0

        record, created = ProcurementRecord.unscoped.get_or_create(
            company=po.company,
            site=po.site,
            material=item.material,
            supplier=po.supplier,
            purchase_order=po,
            defaults={
                "ordered_date": po.order_date,
                "delivered_date": delivery.delivery_date,
                "ordered_qty": item.ordered_qty,
                "delivered_qty": item.delivered_qty,
                "unit_price_paid": unit_price,
            },
        )
        if created:
            record.calc_lead_days()
            record.save(update_fields=["actual_lead_days"])

        # MaterialSupplier も自動登録（なければ作成）
        MaterialSupplier.unscoped.get_or_create(
            company=po.company,
            material=item.material,
            supplier=po.supplier,
            defaults={
                "standard_unit_price": unit_price,
                "is_active": True,
            },
        )


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

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
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
        # 取り込み見積では数量・単価が空の行がある。0 と書くと誤りになるので
        # 空欄のまま出す。金額は既定 0 なので常に出せる。
        qty = f"{item.quantity:,.2f}" if item.quantity is not None else ""
        price = f"¥{int(item.unit_price):,}" if item.unit_price is not None else ""
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


# ── 発注書・発注請書 PDF 出力 ──


# 工事請負契約約款テキスト
_YAKKAN_ARTICLES = [
    ("第1条（総則）",
     "発注者（以下「甲」という。）と、請負者（以下「乙」という。）は、互いに協力し、信義を守り、誠実に本契約を履行する。"),
    ("第2条（契約の成立）",
     "甲は、工事を発注するときは、乙に対し発注書を発行し、乙は甲に対し発注請書を提出することにより、契約が成立するものとする。"),
    ("第3条（権利譲渡等の禁止）",
     "乙は本契約によって生ずる権利、もしくは業務を第三者に譲渡し、又は承継させてはならない。"),
    ("第4条（請負代金の内容）",
     "請負代金には、甲の指定する場所において物件の引渡が完了するまでに要する荷造運賃、据付費等の諸掛一切を含むものとする。"),
    ("第5条（製作完成及び搬入、据付完了の通知）",
     "乙は本契約に基づく物件の製作完成及び搬入、据付完了のときは、其の旨を甲に通知するものとする。"),
    ("第6条（履行完了の確認）",
     "1. 甲は前条に定める通知を受けたときは、遅滞無く、乙の立会のもとに検査を行うものとする。但し、乙の都合により立会しない場合においても検査することができる。\n"
     "2. 甲が前項に定める検査を行った結果、契約に違反し、あるいは不良箇所を発見したときは、乙に速やかにその是正、又は改善をしなければならない。"),
    ("第7条（第三者障害）",
     "1. 施工のため第三者に損害を及ぼしたときには、乙がその損害を賠償する。但し、其の損害の内甲の責に帰すべき事由により生じたものについては、甲の責任とする。\n"
     "2. 前項の規定にかかわらず、施工については乙が善良な管理者としての注意を払っても避けることができない騒音・振動・地盤沈下・地下水の断絶等の事由により第三者に与えた損害を補償するときは、甲がこれを負担する。\n"
     "3. 第2項の場合、其の他施工について第三者との間に紛争が生じたときは、乙が其の処理解決に当たる。但し、乙だけで解決し難いときは、甲は乙に協力する。"),
    ("第8条（所有権の移転）",
     "物件の所有権は、甲が第6条に定める検査を完了し、請負代金を完済した後に乙から甲に移るものとする。"),
    ("第9条（不可抗力による損害）",
     "物件引き渡し前に生じた物件の亡失、毀損は全て乙の負担とする。但し、天災地変其の他乙の責に帰し難い事由による場合並びに甲の責に帰すべき場合はこの限りではない。"),
    ("第10条（物件の保証）",
     "契約の目的物に施工、製作上の瑕疵があるときは引渡検査のとき甲が補修又は取替を求めたものに限り乙が責を負い、かくれた瑕疵については引渡の日より1年間補修の責を負う。"),
    ("第11条（工事及び工期の変更）",
     "1. 甲は必要によって工事の追加又は変更を求めることができる。\n"
     "2. 甲は必要によって乙に工期の変更を求めることができる。\n"
     "3. 不可抗力、其の他正当な理由があるときは、乙は速やかにその理由を示して甲に工期の変更を求めることができる。"),
    ("第12条（請負代金の変更）",
     "1. 次の各号の一にあたるときは、当事者は相手方に請負代金の変更を求めることができる。\n"
     "  a. 工事の追加・変更があったとき。\n  b. 工期の変更があったとき。\n"
     "  c. 支給材料・貸与品について品目、数量、受渡時期又は受渡場所の変更があったとき。\n"
     "  d. 工期内に予期する事のできない経済事情の激変など異常な事態の発生によって請負代金が明らかに不適当であると認められたとき。\n"
     "  e. 中止した工事又は災害を受けた工事を続行する場合、請負代金が不適当であると認められたとき。\n"
     "2. 請負代金の変更をするときは、甲・乙が協議して其の金額を定める。"),
    ("第13条（紛争の解決）",
     "1. 本契約について甲乙間に紛争が生じたときは、建設業法による建設工事紛争審査会のあっせん又は調停によってその解決を図る。\n"
     "2. 甲又は乙が前項により紛争を解決する見込みがないと認めたときは、仲裁合意書に基づいて審査会の仲裁に付することができる。"),
    ("第14条（協議）",
     "この契約書に定めていない事項については、必要に応じて甲・乙が協議して定めるものとする。"),
    ("第15条（暴力団、妨害行為等の排除）",
     "発注者は請負者（下請負者を含む）が反社会的勢力に属すると認められるとき、本契約を解除することができ、本解除により損害が生じた場合、請負者はその賠償の責めを負うものとする。"),
]


def _build_po_pdf_elements(po, items, user, *, is_acceptance=False):
    """発注書/発注請書のPDF要素を組み立てる。"""

    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )

    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
    FONT = "HeiseiKakuGo-W5"
    FONT_MINCHO = "HeiseiMin-W3"

    HEADER_BG = colors.HexColor("#8C8279")

    style_title = ParagraphStyle(
        "title", fontName=FONT, fontSize=20, alignment=1, spaceAfter=5 * mm,
    )
    style_normal = ParagraphStyle(
        "normal", fontName=FONT, fontSize=10, leading=14,
    )
    style_right = ParagraphStyle(
        "right", fontName=FONT, fontSize=10, alignment=2,
    )
    style_company = ParagraphStyle(
        "company", fontName=FONT, fontSize=12, alignment=2,
    )
    style_yakkan_title = ParagraphStyle(
        "yakkan_title", fontName=FONT_MINCHO, fontSize=14, alignment=1,
        spaceBefore=8 * mm, spaceAfter=5 * mm,
    )
    style_article_title = ParagraphStyle(
        "article_title", fontName=FONT_MINCHO, fontSize=9, leading=12,
        spaceBefore=3 * mm,
    )
    style_article_body = ParagraphStyle(
        "article_body", fontName=FONT_MINCHO, fontSize=8, leading=11,
    )

    elements = []

    # === ページ1: 発注書 / 発注請書 ===
    title_text = "発 注 請 書" if is_acceptance else "発 注 書"
    elements.append(Paragraph(title_text, style_title))

    if is_acceptance:
        elements.append(Paragraph("収入印紙貼付欄", ParagraphStyle(
            "stamp", fontName=FONT, fontSize=8, alignment=0,
        )))
        elements.append(Spacer(1, 3 * mm))

    # ヘッダー: 宛先 + 会社情報
    supplier_name = po.supplier.name if po.supplier else ""
    company_name = str(user.company) if user.company else ""

    po_no = f"PO-{po.pk:05d}"
    date_label = "発行日" if is_acceptance else "発注日"

    header_left = [
        Paragraph(f"<b>{supplier_name}　御中</b>", ParagraphStyle(
            "dest", fontName=FONT, fontSize=14, leading=18,
        )),
        Spacer(1, 3 * mm),
        Paragraph(
            "下記のとおり御注文をお請け致しました。" if is_acceptance
            else "下記のとおり発注致します。",
            style_normal,
        ),
    ]

    header_right_data = [
        ["No", po_no],
        [date_label, str(po.order_date)],
    ]
    header_right_table = Table(header_right_data, colWidths=[18 * mm, 50 * mm])
    header_right_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (0, -1), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.white),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))

    company_info = [
        Paragraph(f"<b>{company_name}</b>", style_company),
    ]
    if not is_acceptance:
        company_info.append(Paragraph(
            "代表取締役　釼持　陽子", style_right,
        ))

    # 2カラムヘッダーテーブル
    from reportlab.platypus import TableStyle as TS
    outer = Table(
        [[header_left, [header_right_table, Spacer(1, 2 * mm)] + company_info]],
        colWidths=[90 * mm, 80 * mm],
    )
    outer.setStyle(TS([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements.append(outer)
    elements.append(Spacer(1, 5 * mm))

    # 件名・納期・支払条件
    subject = po.subject or (po.site.name if po.site else "")
    info_data = [
        ["件　名", subject],
        ["納　期", str(po.delivery_date) if po.delivery_date else ""],
        ["支払条件", po.payment_terms or "月末締翌月末払"],
    ]
    info_table = Table(info_data, colWidths=[25 * mm, 145 * mm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (0, -1), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.white),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (1, 0), (-1, -1), [colors.white]),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 5 * mm))

    # 合計金額
    subtotal = sum(int(item.quantity * item.unit_price) for item in items)
    tax_total = sum(
        int(item.quantity * item.unit_price * item.tax_rate)
        for item in items
    )
    grand_total = subtotal + tax_total

    total_data = [["合 計 金 額", f"¥{grand_total:,}"]]
    total_table = Table(total_data, colWidths=[40 * mm, 130 * mm])
    total_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 14),
        ("BACKGROUND", (0, 0), (0, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (0, 0), colors.white),
        ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(total_table)
    elements.append(Spacer(1, 5 * mm))

    # 明細テーブル
    detail_header = ["摘　要", "税率", "数量", "単位", "単価", "金額"]
    detail_data = [detail_header]
    for item in items:
        name = item.display_name
        tax_str = f"{float(item.tax_rate):.0%}" if item.tax_rate else ""
        qty = f"{item.quantity:,.2f}"
        unit = item.unit or (item.material.unit if item.material else "")
        price = f"¥{int(item.unit_price):,}"
        amount = f"¥{int(item.quantity * item.unit_price):,}"
        detail_data.append([name, tax_str, qty, unit, price, amount])

    # 小計・消費税・合計行
    detail_data.append(["", "", "", "", "小　計", f"¥{subtotal:,}"])
    detail_data.append(["", "", "", "", "消費税等", f"¥{tax_total:,}"])
    detail_data.append(["", "", "", "", "合計金額", f"¥{grand_total:,}"])

    col_widths = [55 * mm, 15 * mm, 18 * mm, 15 * mm, 25 * mm, 30 * mm]
    detail_table = Table(detail_data, colWidths=col_widths)
    detail_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -4), [colors.white, colors.HexColor("#f8f9fa")]),
        # 合計行
        ("BACKGROUND", (4, -3), (-1, -1), HEADER_BG),
        ("TEXTCOLOR", (4, -3), (-1, -1), colors.white),
        ("FONTSIZE", (4, -1), (-1, -1), 11),
    ]))
    elements.append(detail_table)
    elements.append(Spacer(1, 5 * mm))

    # 仕様・特記事項
    spec_data = [["仕　様　・　特　記　事　項"]]
    spec_table = Table(spec_data, colWidths=[170 * mm])
    spec_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("BACKGROUND", (0, 0), (-1, -1), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    elements.append(spec_table)

    specs = []
    if po.quotation:
        specs.append(f"見積番号：{po.quotation.pk}")
    if po.site:
        specs.append(f"工事場所：{po.site.name}")
        if hasattr(po.site, "address") and po.site.address:
            specs.append(f"工事場所住所：{po.site.address}")
    if po.delivery_date:
        specs.append(f"工事予定日：{po.delivery_date}")
    if po.notes:
        specs.append(po.notes)

    for spec in specs:
        elements.append(Paragraph(spec, style_normal))
    elements.append(Spacer(1, 5 * mm))

    # === ページ2: 工事請負契約約款 ===
    elements.append(PageBreak())
    elements.append(Paragraph("工 事 請 負 契 約 約 款", style_yakkan_title))

    for title, body in _YAKKAN_ARTICLES:
        elements.append(Paragraph(f"<b>{title}</b>", style_article_title))
        for line in body.split("\n"):
            elements.append(Paragraph(line, style_article_body))

    return elements


def generate_purchase_order_pdf(output, po, items, user):
    """発注書PDFを生成する。

    Args:
        output: HttpResponse or file-like object
        po: PurchaseOrder instance
        items: PurchaseOrderItem queryset
        user: 出力実行ユーザー
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    doc = SimpleDocTemplate(
        output, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )
    elements = _build_po_pdf_elements(po, items, user, is_acceptance=False)
    doc.build(elements)


def generate_purchase_order_acceptance_pdf(output, po, items, user):
    """発注請書PDFを生成する。

    Args:
        output: HttpResponse or file-like object
        po: PurchaseOrder instance
        items: PurchaseOrderItem queryset
        user: 出力実行ユーザー
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    doc = SimpleDocTemplate(
        output, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )
    elements = _build_po_pdf_elements(po, items, user, is_acceptance=True)
    doc.build(elements)


# ── 納品書 画像OCR ──


def extract_delivery_items_from_image(delivery, purchase_order, company):
    """納品書画像からClaude APIで明細を読み取り、DeliveryItemを生成する。

    Haiku使用。AILogに記録。

    Args:
        delivery: Delivery instance (image フィールドに画像がセットされている)
        purchase_order: PurchaseOrder instance
        company: Company instance

    Returns:
        list[DeliveryItem]: 生成された DeliveryItem のリスト
    """
    import os
    from decimal import Decimal

    from apps.ai.models import AILog
    from apps.ai.services.llm_advisor import call_claude_with_log
    from apps.materials.models import DeliveryItem, Material

    # 画像をbase64エンコード
    image_path = delivery.image.path
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    ext = os.path.splitext(image_path)[1].lower()
    media_type = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
    }.get(ext, "image/jpeg")

    # PO明細の材料リストをプロンプトに含める
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

    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": image_data,
            },
        },
        {"type": "text", "text": prompt},
    ]

    result = call_claude_with_log(
        prompt=prompt,
        model_key="haiku",
        max_tokens=2000,
        company=company,
        site=purchase_order.site,
        task_type=AILog.TaskType.DELIVERY_OCR,
        input_data={
            "delivery_id": delivery.pk,
            "po_id": purchase_order.pk,
            "image_path": str(image_path),
        },
        user=delivery.created_by,
        content=content,
    )

    raw_text = result["raw"]
    delivery.extraction_raw = raw_text
    delivery.save(update_fields=["extraction_raw"])

    extracted_items = (result["parsed"] or {}).get("items", [])

    created_items = []
    for ext_item in extracted_items:
        material_name = ext_item.get("material_name", "")
        delivered_qty = ext_item.get("delivered_qty", 0)

        if not material_name or not delivered_qty:
            continue

        matched_po_item = None
        for po_item in po_items:
            if po_item.material.name in material_name or material_name in po_item.material.name:
                matched_po_item = po_item
                break

        if matched_po_item:
            material = matched_po_item.material
            ordered_qty = matched_po_item.quantity
        else:
            material = Material.unscoped.filter(
                company=company, name__icontains=material_name,
            ).first()
            ordered_qty = 0

        if not material:
            logger.warning(f"材料マッチ失敗: {material_name}")
            continue

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
