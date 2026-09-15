"""入札参加資格の原本を書き写したもの（ADR-0063）。

原本: 「入札案件参加資格.pdf」（4 ページ）
- 1〜3 ページ: 官公庁 電子入札共同システム参加資格一覧
  （有効期限 令和7年4月1日～令和9年3月31日。3 ページ目の国立印刷局は手書きの追記）
- 4 ページ: 資格審査結果通知書（全省庁統一資格。発行番号 250128000135、
  業者コード 0000206312、有効期間 令和7年4月1日～令和10年3月31日）

原本そのものに書き誤りと思われる箇所や空欄があるので、どう登録するかを NOTES に残す。
`verify_qualifications` コマンドが、この値と登録内容を照らし合わせる。
"""

import datetime

SOURCE_NAME = "入札案件参加資格.pdf"

LIST_VALID_FROM = datetime.date(2025, 4, 1)
LIST_VALID_UNTIL = datetime.date(2027, 3, 31)  # 令和9年3月31日
UNIFIED_VALID_FROM = datetime.date(2025, 4, 1)
UNIFIED_VALID_UNTIL = datetime.date(2028, 3, 31)  # 令和10年3月31日

# 地方整備局などの 5 業種（電気設備だけ等級と、局ごとに違う総合点を持つ）
_FIVE = ("電気設備", "維持修繕", "通信設備", "受変電", "橋梁補修")


def _row(issuer, category, grade, keisin, total, vendor):
    return {
        "issuer": issuer,
        "category": category,
        "grade": grade,
        "keisin_score": keisin,
        "total_score": total,
        "vendor_number": vendor,
        "valid_from": LIST_VALID_FROM,
        "valid_until": LIST_VALID_UNTIL,
    }


def _bureau(issuer, facility_total, vendor, categories=_FIVE):
    scores = {
        "電気設備": ("B", 871, facility_total),
        "維持修繕": ("", 818, 818),
        "通信設備": ("", 696, 696),
        "受変電": ("", 845, 845),
        "橋梁補修": ("", 816, 816),
    }
    return [_row(issuer, c, *scores[c], vendor) for c in categories]


def _pair(issuer, vendor, construction="B", telecom="C", construction_name="電気工事"):
    """電気工事（経審 884）と電気通信（経審 696）の 2 行。"""
    return [
        _row(issuer, construction_name, construction, 884, 884, vendor),
        _row(issuer, "電気通信", telecom, 696, 696, vendor),
    ]


# 1〜3 ページ（原本の並び順）
LIST_ROWS = [
    _row("国土交通省", "電気工事", "A", 884, 884, "2514024304"),
    _row("国土交通省", "電気通信", "B", 696, 696, "2514024304"),
    *_bureau("国土交通省(東北地方整備局)", 1957, "17002225000"),
    *_bureau("国土交通省(関東地方整備局)", 2054, "10022158000"),
    *_bureau("国土交通省(中部地方整備局)", 1957, "26019259000"),
    *_bureau("国土交通省(近畿地方整備局)", 1957, "10040083000"),
    *_bureau("国土交通省(北陸地方整備局)", 1957, "12000043000"),
    *_bureau("国土交通省(中国地方整備局)", 1957, "17000316000"),
    *_bureau("国土交通省(四国地方整備局)", 1957, "50017244000"),
    *_bureau("国土交通省(九州地方整備局)", 1957, "00024690000"),
    *_bureau(
        "国土交通省(官房官庁営繕部)", 1957, "10022692000", ("電気設備", "通信設備", "受変電"),
    ),
    *_bureau("国土交通省(国土技術政策総合研究所)", 2054, "10022158000"),
    *_pair("法務省", "07081", telecom="○", construction_name="電気"),
    *_pair("財務省", "711684"),
    # 原本の電気工事の経審点は「8884」。884 の書き誤りとして 884 にする（NOTES）
    *_pair("財務省(北海道財務局)", "482489"),
    *_pair("財務省(関東財務局)", "204703"),
    *_pair("財務省(東北財務局)", "103336"),
    _row("財務省(中国財務局)", "電気工事", "B", 884, 884, "781441"),
    *_pair("財務省(東海財務局)", "711684", construction="", telecom=""),
    *_pair("財務省(北陸財務局)", "901536"),
    *_pair("財務省(四国財務局)", "871308"),
    _row("財務省(近畿財務局)", "電気工事", "B", 884, 884, "501761"),
    *_pair("財務省(九州財務局)", "711438"),
    *_pair("財務省(福岡財務支局)", "151406"),
    *_pair("厚生労働省", "5021001019709", telecom="D"),
    _row("環境省", "電気工事", "A", 884, 884, "14-005170"),
    *_pair("内閣府", "10701715394", construction="A"),
    *_bureau("内閣府(沖縄総合事務局)", 1947, "161869"),
    _row("経済産業省", "電気工事", "B", None, None, "0701103506"),
    _row("経済産業省", "電気通信", "C", None, None, "0701103506"),
    *_pair("最高裁判所", "0038034", telecom=""),
    *_pair("防衛省", "2-05-05074", construction="A"),
    _row("北海道開発局", "電気", "B", 880, 880, "11-05563"),
    _row("北海道開発局", "維持", "", 829, 829, "11-05563"),
    # 手書きの追記（NOTES）
    _row("国立印刷局", "電気工事", "B", 886, None, "010002213"),
    _row("国立印刷局", "電気通信工事", "C", 685, None, "010002213"),
]

GOODS_SALES_ITEMS = (
    "電気・通信用機器類", "精密機器類", "その他機器類", "土木・建設・建築材料", "その他",
)
SERVICES_ITEMS = ("賃貸借", "建物管理等各種保守管理", "その他")
PURCHASE_ITEMS = ("その他",)


def _unified(category, grade, items):
    return {
        "issuer": "全省庁統一資格",
        "category": category,
        "grade": grade,
        "keisin_score": None,
        "total_score": 62,
        "vendor_number": "0000206312",
        "valid_from": UNIFIED_VALID_FROM,
        "valid_until": UNIFIED_VALID_UNTIL,
        "application_type": "全省庁統一資格",
        "memo": "営業品目: " + "／".join(items),
    }


# 4 ページ（「物品の製造」は等級が無いので登録しない）
UNIFIED_ROWS = [
    _unified("物品の販売", "C", GOODS_SALES_ITEMS),
    _unified("役務の提供等", "C", SERVICES_ITEMS),
    _unified("物品の買受け", "B", PURCHASE_ITEMS),
]

ALL_ROWS = LIST_ROWS + UNIFIED_ROWS

# 全省庁統一資格（省庁別）は、どの機関でも通知書と同じ等級・点数・営業品目になる
UNIFIED_AGENCY_VALUES = [
    ("goods_sales_grade", "C"),
    ("goods_sales_score", 62),
    ("goods_sales_items", GOODS_SALES_ITEMS),
    ("services_grade", "C"),
    ("services_score", 62),
    ("services_items", SERVICES_ITEMS),
    ("purchase_grade", "B"),
    ("purchase_score", 62),
]

NOTES = [
    "財務省(北海道財務局) 電気工事の経審点は原本で「8884」。総合点 884 と、ほかの電気工事の"
    "経審点がすべて 884 なので、884 の書き誤りとして 884 で登録する",
    "財務省(東海財務局) は原本の等級が電気工事・電気通信とも空欄。業者番号 711684 は"
    "財務省（本省）と同じ。原本どおり等級は空欄で登録する",
    "国立印刷局 は手書きの追記。業者番号の最後の「3」が隣の欄にかかっていて「010002213」と読んだ。"
    "総合点は書かれていないので空欄",
    "経済産業省 は原本に経審点・総合点が無い（空欄）",
    "内閣府(沖縄総合事務局) 電気設備の総合点は原本どおり 1947"
    "（国土交通省の地方整備局は 1957・2054）",
    "法務省 電気通信の等級は原本どおり「○」、最高裁判所 電気通信の等級は原本どおり空欄",
    "有効期限は、一覧が 令和9年3月31日（2027-03-31）、"
    "全省庁統一資格が 令和10年3月31日（2028-03-31）",
]
