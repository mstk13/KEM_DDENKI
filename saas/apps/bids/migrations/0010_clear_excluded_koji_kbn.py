"""取得対象外になった工事区分を検索条件から外す。

土木・舗装系（一般土木工事／土木工事／アスファルト舗装工事／
セメント・コンクリート舗装工事）を取り込み時に除外するようにしたため、
これらを検索条件に持つ ScrapeTarget は「検索はするが1件も保存されない」
状態になる。空にして「工事区分の指定なし」に倒す。
"""
from django.db import migrations

from apps.bids.models import is_excluded_category


def clear_excluded(apps, schema_editor):
    ScrapeTarget = apps.get_model("bids", "ScrapeTarget")
    for target in ScrapeTarget.objects.exclude(koji_kbn=""):
        if is_excluded_category(target.koji_kbn):
            target.koji_kbn = ""
            target.save(update_fields=["koji_kbn"])


def noop(apps, schema_editor):
    """元の値は復元できない（何を選んでいたかを残していない）。"""


class Migration(migrations.Migration):

    dependencies = [
        ("bids", "0009_bidproject_agency_dept_bidproject_announced_on_and_more"),
    ]

    operations = [
        migrations.RunPython(clear_excluded, noop),
    ]
