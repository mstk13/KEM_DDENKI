"""既存の評価テンプレートを、経営理念に基づく設問へ更新する。

評価画面は EvaluationTemplate（DB）があればそれを使い、無ければ
static/data/*.json をフォールバックとして使う。テナントには既に
テンプレートが保存されているため、JSON を書き換えても画面に反映されない。
このマイグレーションで DB 側を JSON の内容へ揃える。

注意: 管理画面からテナント独自に編集した内容があれば上書きされる。
マイグレーション内の save では simple-history の記録は残らないため、
更新前の内容は復元できない。今回は JSON 側を正とする前提で実行する。

このマイグレーションは1回だけ実行される。以降 JSON を書き換えたときは、
同様のマイグレーションを追加するか、seed_eval_template --force を実行する。
"""

import json
from pathlib import Path

from django.db import migrations

_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static" / "data"


def _load(name):
    with open(_DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def refresh(apps, schema_editor):
    EvaluationTemplate = apps.get_model("workers", "EvaluationTemplate")

    try:
        eval_items = _load("eval_items.json")
        survey = _load("survey_questions.json")
    except FileNotFoundError:
        # データファイルが無い環境（テスト等）では何もしない
        return

    for template in EvaluationTemplate.objects.all():
        template.sections = eval_items
        template.survey_items = survey["items"]
        template.scale = survey["scale"]
        template.overall = survey["overall"]
        template.save(update_fields=["sections", "survey_items", "scale", "overall"])


def noop(apps, schema_editor):
    """逆方向は何もしない。旧内容は simple-history に残っている。"""


class Migration(migrations.Migration):

    dependencies = [
        ("workers", "0009_worker_pin_fields"),
    ]

    operations = [
        migrations.RunPython(refresh, noop),
    ]
