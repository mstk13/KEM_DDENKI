"""運転免許証の取得日・有効期限を入れる（ADR-0101）。

資格証が付いているのに日付が入っていない免許証へ、券面の日付を入れる。
既に入っている日付は上書きしない。
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.workers.license_dates import fill_license_dates
    from apps.workers.listed_qualifications import find_company

    company = find_company(apps.get_model("tenants", "Company"))
    if company is None:
        return

    fill_license_dates(company, apps.get_model("workers", "WorkerQualification"))


def backwards(apps, schema_editor):
    # 入れた日付を消すと、人が手で入れた分と見分けが付かないため戻さない
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("workers", "0022_masataka_kemmochi_qualification"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
