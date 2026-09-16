"""作業員の保有資格を、資格保有一覧.xls の資格だけにする（ADR-0068 改訂 その3）。

0019 では、この一覧から登録した資格だけを消していた。
プロダクトオーナーの指示（2026-09-16）で、一覧に載っている作業員の資格は
**いま登録してあるものをすべて消してから**、Excel の資格だけを登録し直す。

- 画面で手で登録した資格も消す
- 原本の写真が添付されている資格も消す（写真は見られなくなる）
- 一覧に載っていない作業員の資格には触らない
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
        ("workers", "0019_replace_listed_qualifications"),
    ]

    operations = [
        # 逆方向は何もしない（消した資格は戻せない）
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
