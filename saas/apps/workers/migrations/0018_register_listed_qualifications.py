"""資格保有状況一覧（2026/9/15）の資格を、作業員ごとに登録する（ADR-0068）。

「○」の資格を資格名と区分だけ登録する（原本の写真・取得日・有効期限はあとから画面で入れる）。
登録先は会社名「ケンモチ電機」、無ければ会社が1社だけのときのその会社。
作業員は氏名で探し、同じ資格名が既にあれば登録しない。見つからなかった作業員は
管理コマンド register_listed_qualifications で確かめて、登録し直せる。
"""

from django.db import migrations


def forwards(apps, schema_editor):
    # 一覧のデータと登録の手順は、管理コマンドと同じものを使う
    from apps.workers.listed_qualifications import (
        find_company,
        register_listed_qualifications,
    )

    company = find_company(apps.get_model("tenants", "Company"))
    register_listed_qualifications(
        company,
        apps.get_model("workers", "Worker"),
        apps.get_model("workers", "WorkerQualification"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("workers", "0017_worker_social_insurance"),
    ]

    operations = [
        # 逆方向は何もしない（画面で写真を添付したあとの資格を消さないため）
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
