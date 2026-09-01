"""自由入力の category を工事区分／業種へ振り分け、地域を i-ppi の表記へ揃える。

i-ppi の「電気」を含む選択肢は工事区分（電気設備工事など）と
業種（電気工事など）の2つのセレクトに分かれている。
旧コードは DOM 順で先にヒットする工事区分を部分一致で選んでいたため、
その挙動をそのまま移送する（工事区分を優先し、無ければ業種）。

選択肢の一覧はこの時点の実物を写したもの。
以後 models.py 側が変わってもこの移送結果が動かないよう、意図して複製している。
"""
from django.db import migrations

KOJI_KBN = [
    "一般土木工事",
    "アスファルト舗装工事",
    "鋼橋上部工事",
    "造園工事",
    "建築工事",
    "木造建築工事",
    "電気設備工事",
    "暖冷房衛生設備工事",
    "セメント・コンクリート舗装工事",
    "プレストレスト・コンクリート工事",
    "法面処理工事",
    "塗装工事",
    "維持修繕工事",
    "浚渫工事",
    "グラウト工事",
    "杭打工事",
    "さく井工事",
    "プレハブ建築工事",
    "機械設備工事",
    "通信設備工事",
    "受変電設備工事",
    "港湾土木工事",
    "農林土木工事",
    "農林建築工事",
    "橋梁補修工事",
    "その他",
]

KOJI_GYOSYU = [
    "土木一式工事",
    "建築一式工事",
    "大工工事",
    "左官工事",
    "とび・土工・コンクリート工事",
    "石工事",
    "屋根工事",
    "電気工事",
    "管工事",
    "タイル・れんが・ブロック工事",
    "鋼構造物工事",
    "鉄筋工事",
    "舗装工事",
    "浚渫工事",
    "板金工事",
    "ガラス工事",
    "塗装工事",
    "防水工事",
    "内装仕上工事",
    "機械器具設置工事",
    "熱絶縁工事",
    "電気通信工事",
    "造園工事",
    "さく井工事",
    "建具工事",
    "水道施設工事",
    "消防施設工事",
    "清掃施設工事",
    "解体工事",
    "その他",
]

# i-ppi の地域は九州と沖縄が1項目にまとまっている
REGION_RENAMES = {"九州": "九州・沖縄", "沖縄": "九州・沖縄"}


def _split_category(category):
    """旧 category を (工事区分, 業種) に振り分ける。判別できなければ両方空。"""
    value = (category or "").strip()
    if not value:
        return "", ""
    if value in KOJI_KBN:
        return value, ""
    if value in KOJI_GYOSYU:
        return "", value
    for label in KOJI_KBN:
        if value in label:
            return label, ""
    for label in KOJI_GYOSYU:
        if value in label:
            return "", label
    # 判別できないものは移送しない。category 列は残るので情報は失われない。
    return "", ""


def forwards(apps, schema_editor):
    # unscoped: データ移送は全テナントが対象
    ScrapeTarget = apps.get_model("bids", "ScrapeTarget")

    for target in ScrapeTarget.objects.all():
        updates = []

        if target.category and not target.koji_kbn and not target.koji_gyosyu:
            kbn, gyosyu = _split_category(target.category)
            if kbn or gyosyu:
                target.koji_kbn = kbn
                target.koji_gyosyu = gyosyu
                updates += ["koji_kbn", "koji_gyosyu"]

        new_region = REGION_RENAMES.get(target.region)
        if new_region:
            target.region = new_region
            updates.append("region")

        if updates:
            target.save(update_fields=updates)


class Migration(migrations.Migration):
    dependencies = [
        ("bids", "0004_historicalscrapetarget_koji_gyosyu_and_more"),
    ]

    operations = [
        # 逆方向は何もしない。category 列を残しているので巻き戻しても情報は失われない。
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
