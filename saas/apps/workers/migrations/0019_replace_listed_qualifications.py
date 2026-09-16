"""作業員の保有資格を、資格保有一覧.xls の資格名に入れ替える（ADR-0068 改訂）。

0018 では PDF の「資格保有状況一覧」から読み取った資格名で登録していた。
プロダクトオーナーの指示（2026-09-16）で、Excel「資格保有一覧.xls」に書かれている資格名だけにする。

- 0018 で登録した資格（備考が PREVIOUS_NOTES）のうち、Excel の一覧に無い資格名は消す
- Excel の一覧の資格を、書かれている表記のまま登録する
- 手で登録した資格（備考が違う）や、写真を添えた資格はそのまま残す
"""

from django.db import migrations


def forwards(apps, schema_editor):
    # 一覧のデータと入れ替えの手順は、管理コマンドと同じものを使う
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
        ("workers", "0018_register_listed_qualifications"),
    ]

    operations = [
        # 逆方向は何もしない（画面で写真を添付したあとの資格を消さないため）
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
