"""資格保有一覧.xls の資格を、作業員ごとに登録する（ADR-0068）。

- 資格名は Excel の見出しのまま。「△」は「（補）」を付ける
- この一覧から登録した資格のうち、一覧に無いものは消す（手で登録した資格は残す）
"""

import importlib
from io import StringIO

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command

from apps.tenants.models import Company
from apps.workers.listed_qualifications import (
    CATEGORIES,
    HOLDERS,
    NOTE,
    PREVIOUS_NOTES,
    find_company,
    normalize_person_name,
    register_listed_qualifications,
)
from apps.workers.models import Worker, WorkerQualification

register_migration = importlib.import_module(
    "apps.workers.migrations.0018_register_listed_qualifications"
)
replace_migration = importlib.import_module(
    "apps.workers.migrations.0019_replace_listed_qualifications"
)

# アプリ側の氏名は空白や字の違いがあってもよい
APP_NAMES = {
    "釼持　陽子": "剣持　陽子",
    "釼持　政宏": "釼持政宏",
    "高橋　章": "高橋 章",
    "江頭　敏幸": "江頭 敏幸",
    "片桐　徳男": "片桐 徳男",
    "茨木　浩次": "茨木 浩次",
    "出永　修": "出永 修",
    "佐藤　榮一": "佐藤 栄一",
    "古矢　隆": "古矢 隆",
    "村井　君好": "村井 君好",
    "髙橋　翔太": "高橋 翔太",
    "杉本　和幸": "杉本 和幸",
    "梅田　義彦": "梅田 義彦",
    "松倉　利昭": "松倉 利昭",
}
HOSHO = "電気工事施工監理技士　１級（補）"
ICHIKYU = "電気工事施工監理技士　１級"


@pytest.fixture
def kem(db):
    return Company.objects.create(name="ケンモチ電機", industry_type="設備工事")


def _workers(company, names=None):
    workers = {}
    for i, (listed, app_name) in enumerate((names or APP_NAMES).items(), start=1):
        workers[listed] = Worker.unscoped.create(
            company=company, employee_code=f"E{i:03d}", name=app_name, hourly_cost=3000,
        )
    return workers


def _names(worker):
    return set(worker.qualifications.values_list("name", flat=True))


class TestSource:
    def test_一覧は14人150件で_すべての資格に区分がある(self):
        assert len(HOLDERS) == 14
        assert sum(len(v) for v in HOLDERS.values()) == 150
        for names in HOLDERS.values():
            assert len(names) == len(set(names))
            assert all(name in CATEGORIES for name in names)

    def test_資格名はExcelの見出しのまま(self):
        assert CATEGORIES[ICHIKYU] == "license"
        assert CATEGORIES[HOSHO] == "license"
        assert CATEGORIES["高所作業車・作業床高⒑ｍ以上"] == "skill_course"
        assert CATEGORIES["車両系建設機械・機重３ｔ未満"] == "education"
        assert CATEGORIES["3M工法取得認定（高圧端末 常温収縮）"] == "other"
        # 「(補△)」は凡例なので資格名には入れない
        assert not any("(補△)" in name for name in CATEGORIES)

    def test_補は政宏だけ(self):
        holders = [who for who, names in HOLDERS.items() if HOSHO in names]
        assert holders == ["釼持　政宏"]
        assert ICHIKYU not in HOLDERS["釼持　政宏"]

    def test_氏名の空白と字の違いを揃える(self):
        assert normalize_person_name("髙橋　翔太") == normalize_person_name("高橋 翔太")
        assert normalize_person_name("佐藤 榮一") == normalize_person_name("佐藤栄一")
        assert normalize_person_name("釼持 陽子") == normalize_person_name("剣持陽子")
        assert normalize_person_name("高橋 章") != normalize_person_name("高橋 翔太")


@pytest.mark.django_db
class TestRegister:
    def test_作業員ごとに資格名と区分を登録する(self, kem):
        workers = _workers(kem)

        report = register_listed_qualifications(kem, Worker, WorkerQualification)

        assert len(report["created"]) == 150
        assert report["missing"] == [] and report["ambiguous"] == []
        assert report["removed"] == []
        assert HOSHO in _names(workers["釼持　政宏"])
        assert _names(workers["松倉　利昭"]) == {ICHIKYU, "電気工事士　1種"}
        assert _names(workers["髙橋　翔太"]) == {"運転免許証", "職長・安全衛生責任者教育"}
        q = WorkerQualification.unscoped.get(worker=workers["釼持　陽子"], name="フルハーネス")
        assert q.category == WorkerQualification.Category.EDUCATION
        assert q.note == NOTE
        assert not q.certificate_image
        assert q.acquired_date is None and q.expiry_date is None

    def test_前の表記で登録した資格は消して入れ替える(self, kem):
        workers = _workers(kem)
        matsukura = workers["松倉　利昭"]
        WorkerQualification.unscoped.create(
            company=kem, worker=matsukura, name="電気工事施工管理技士 1級",
            category=WorkerQualification.Category.LICENSE, note=PREVIOUS_NOTES[0],
        )
        WorkerQualification.unscoped.create(
            company=kem, worker=matsukura, name="手で入れた資格",
            category=WorkerQualification.Category.OTHER, note="手で登録",
        )

        report = register_listed_qualifications(kem, Worker, WorkerQualification)

        assert ("松倉 利昭", "電気工事施工管理技士 1級") in report["removed"]
        assert _names(matsukura) == {ICHIKYU, "電気工事士　1種", "手で入れた資格"}

    def test_確認だけなら消さず登録もしない(self, kem):
        workers = _workers(kem)
        old = WorkerQualification.unscoped.create(
            company=kem, worker=workers["松倉　利昭"], name="電気工事施工管理技士 1級",
            category=WorkerQualification.Category.LICENSE, note=PREVIOUS_NOTES[0],
        )

        report = register_listed_qualifications(kem, Worker, WorkerQualification, apply=False)

        assert len(report["created"]) == 150
        assert len(report["removed"]) == 1
        assert WorkerQualification.unscoped.filter(pk=old.pk).exists()
        assert WorkerQualification.unscoped.filter(company=kem).count() == 1

    def test_何度流しても増えない(self, kem):
        _workers(kem)

        register_listed_qualifications(kem, Worker, WorkerQualification)
        second = register_listed_qualifications(kem, Worker, WorkerQualification)

        assert second["created"] == [] and second["removed"] == []
        assert len(second["existing"]) == 150
        assert WorkerQualification.unscoped.filter(company=kem).count() == 150

    def test_見つからない作業員と同姓同名は登録しない(self, kem):
        names = dict(APP_NAMES)
        del names["杉本　和幸"]
        _workers(kem, names)
        Worker.unscoped.create(company=kem, employee_code="E900", name="梅田 義彦", hourly_cost=0)

        report = register_listed_qualifications(kem, Worker, WorkerQualification)

        assert report["missing"] == ["杉本　和幸"]
        assert report["ambiguous"] == ["梅田　義彦"]
        assert not WorkerQualification.unscoped.filter(worker__name="梅田 義彦").exists()

    def test_退職者と同姓同名なら在籍中の人に登録する(self, kem):
        workers = _workers(kem, {"松倉　利昭": "松倉 利昭"})
        Worker.unscoped.create(
            company=kem, employee_code="E900", name="松倉 利昭", hourly_cost=0, is_active=False,
        )

        register_listed_qualifications(kem, Worker, WorkerQualification)

        assert len(_names(workers["松倉　利昭"])) == 2

    def test_他社の作業員には登録しない(self, kem, company_a):
        _workers(kem)
        others = _workers(company_a)

        register_listed_qualifications(kem, Worker, WorkerQualification)

        assert not WorkerQualification.unscoped.filter(worker__in=others.values()).exists()

    def test_登録先の会社(self, kem, company_a):
        assert find_company(Company) == kem
        kem.delete()
        # 会社が1社だけならその会社、複数なら決めない
        assert find_company(Company) == company_a
        Company.objects.create(name="別の会社", industry_type="設備工事")
        assert find_company(Company) is None


@pytest.mark.django_db
class TestMigrationAndCommand:
    def test_データ移送で登録し_入れ替えでも増えない(self, kem):
        workers = _workers(kem)
        WorkerQualification.unscoped.create(
            company=kem, worker=workers["松倉　利昭"], name="電気工事施工管理技士 1級",
            category=WorkerQualification.Category.LICENSE, note=PREVIOUS_NOTES[0],
        )

        register_migration.forwards(django_apps, None)
        replace_migration.forwards(django_apps, None)

        assert WorkerQualification.unscoped.filter(company=kem).count() == 150
        assert not WorkerQualification.unscoped.filter(name="電気工事施工管理技士 1級").exists()

    def test_コマンドは確認だけでは変えず_見つからない氏名と消す資格を出す(self, kem):
        names = dict(APP_NAMES)
        del names["杉本　和幸"]
        workers = _workers(kem, names)
        WorkerQualification.unscoped.create(
            company=kem, worker=workers["松倉　利昭"], name="電気工事施工管理技士 1級",
            category=WorkerQualification.Category.LICENSE, note=PREVIOUS_NOTES[0],
        )
        out = StringIO()

        call_command("register_listed_qualifications", stdout=out)

        text = out.getvalue()
        assert "確認だけです" in text
        assert "登録予定 143 件" in text
        assert "一覧に無い資格 1 件（消す予定）" in text
        assert "- 杉本　和幸" in text
        assert WorkerQualification.unscoped.filter(company=kem).count() == 1

        call_command("register_listed_qualifications", "--apply", stdout=StringIO())

        assert WorkerQualification.unscoped.filter(company=kem).count() == 143
        assert not WorkerQualification.unscoped.filter(name="電気工事施工管理技士 1級").exists()
