"""自社の建設業許可（神奈川県知事の通知 2 通）を登録する（ADR-0064）。

通知書: 建業第53546号（令和7年4月3日）
- 特定建設業の許可について（通知）: 電気工事業 神奈川県知事 許可（特-7）第5170号
- 一般建設業の許可について（通知）: 電気通信工事業 神奈川県知事 許可（般-7）第5170号
どちらも有効期間は令和7年4月21日から令和12年4月20日まで、更新書類の提出期限は令和12年3月21日。

登録先は会社名が「ケンモチ電機」の会社。無ければ、会社が 1 社だけのときはその会社。
その会社に建設業許可が 1 件でもあれば何もしない（画面で登録・修正した内容を上書きしない）。
"""

import datetime

from django.db import migrations

COMPANY_NAME = "ケンモチ電機"

_COMMON = {
    "grantor_type": "governor",
    "authority": "神奈川県知事",
    "valid_from": datetime.date(2025, 4, 21),
    "valid_until": datetime.date(2030, 4, 20),
    "renewal_deadline": datetime.date(2030, 3, 21),
}

LICENSES = [
    {
        **_COMMON,
        "trade": "電気工事業",
        "license_class": "special",
        "license_number": "許可（特-7）第5170号",
        "memo": "特定建設業の許可について（通知） 建業第53546号（令和7年4月3日）",
    },
    {
        **_COMMON,
        "trade": "電気通信工事業",
        "license_class": "general",
        "license_number": "許可（般-7）第5170号",
        "memo": "一般建設業の許可について（通知） 建業第53546号（令和7年4月3日）",
    },
]


def register_licenses(Company, ConstructionLicense):
    """建設業許可を登録し、登録した件数を返す。

    マイグレーションからは履歴モデルを、テストからは実モデルを渡す。
    データ移送はテナントの文脈が無いので、テナントで絞らない _base_manager を使う。
    """
    company = Company._base_manager.filter(name=COMPANY_NAME).order_by("pk").first()
    if company is None:
        companies = list(Company._base_manager.order_by("pk")[:2])
        if len(companies) != 1:
            return 0
        company = companies[0]
    if ConstructionLicense._base_manager.filter(company=company).exists():
        return 0
    for row in LICENSES:
        ConstructionLicense._base_manager.create(company=company, **row)
    return len(LICENSES)


def forwards(apps, schema_editor):
    register_licenses(
        apps.get_model("tenants", "Company"), apps.get_model("bids", "ConstructionLicense"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("bids", "0023_constructionlicense"),
    ]

    operations = [
        # 逆方向は何もしない。表そのものは 0023 を戻せば消える。
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
