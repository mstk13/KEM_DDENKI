"""評価テンプレートを最新の設問（ケンモチ電機2.docx の指示を反映）へ更新する。

0010 / 0011 と同じ処理。マイグレーションは1回しか実行されないため、
JSON を更新するたびに追随用のマイグレーションを追加している。
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
        return

    for template in EvaluationTemplate.objects.all():
        template.sections = eval_items
        template.survey_items = survey["items"]
        template.scale = survey["scale"]
        template.overall = survey["overall"]
        template.save(update_fields=["sections", "survey_items", "scale", "overall"])


def noop(apps, schema_editor):
    """逆方向は何もしない。"""


class Migration(migrations.Migration):

    dependencies = [
        ("workers", "0011_refresh_eval_template_docx"),
    ]

    operations = [
        migrations.RunPython(refresh, noop),
    ]
