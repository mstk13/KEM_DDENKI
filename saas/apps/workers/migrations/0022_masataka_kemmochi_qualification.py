"""釼持雅崇（Masataka Kemmochi）の保有資格を登録する（ADR-0082）。

資格保有一覧.xls（ADR-0068）にはこの人の行が無く、資格が1件も登録されていない。
資格書一覧のフォルダに修了証の PDF があるので、まず資格名だけを登録しておく。
証明書の PDF は、サーバーで import_certificates を流したときに添付される。

作業員はローマ字「Masataka Kemmochi」で登録されている（プロダクトオーナー、2026-09-17）。
漢字とローマ字のどちらでも当たるよう、取り込みと同じ名寄せを使う。
"""

from django.db import migrations

QUALIFICATION_NAME = "産業廃棄物処理業許可申請講習会（更新・収集運搬課程）"
PERSON = "釼持雅崇"


def forwards(apps, schema_editor):
    from apps.workers.certificate_import import category_for, name_keys
    from apps.workers.listed_qualifications import find_company

    company = find_company(apps.get_model("tenants", "Company"))
    if company is None:
        return

    Worker = apps.get_model("workers", "Worker")
    WorkerQualification = apps.get_model("workers", "WorkerQualification")

    keys = name_keys(PERSON)
    worker = next(
        (w for w in Worker.objects.filter(company=company) if name_keys(w.name) & keys),
        None,
    )
    if worker is None:
        # 作業員が未登録の環境（テスト用のDBなど）では何もしない
        return

    WorkerQualification.objects.get_or_create(
        company=company,
        worker=worker,
        name=QUALIFICATION_NAME,
        defaults={"category": category_for(QUALIFICATION_NAME)},
    )


def backwards(apps, schema_editor):
    WorkerQualification = apps.get_model("workers", "WorkerQualification")
    WorkerQualification.objects.filter(
        name=QUALIFICATION_NAME, certificate_image="",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("workers", "0021_certificate_file"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
