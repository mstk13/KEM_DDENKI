"""評価テンプレートの項目の並びを「共通 → 職種別」に揃える。

データ側の並びが職種別より後に共通が来ていたため、事務の評価では
共通の設問が下に埋もれて見落とされていた。JSON を並べ替えたので、
DB のテンプレートにも同じ内容を反映する。
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
        ("workers", "0012_refresh_eval_template_docx2"),
    ]

    operations = [
        migrations.RunPython(refresh, noop),
    ]
