"""資格証のPDFを保有資格に添付する（ADR-0082）。

- フォルダ名の氏名で作業員を探す（空白・旧字の違いは同じとみなす）
- ファイル名から登録済みの資格名に読み替えて添付する
- 同じ資格に複数のファイルがあるときは1件だけ添付し、残りは報告に出す
- 有効期限は CSV から入れる。記載の無いものは空のままにする
"""

import datetime

import pytest
from django.urls import reverse

from apps.workers.certificate_import import (
    category_for,
    collect_files,
    import_certificates,
    read_dates,
)
from apps.workers.models import Worker, WorkerQualification

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


@pytest.fixture
def folder(tmp_path):
    for person, files in {
        "釼持　政宏": [
            "第一種電気工事士免状.pdf",
            "高圧ケーブル工事技能認定証.pdf",
            "引込線(アンペアブレーカ)工事者証(柱上・地上作業).pdf",
            "引込線(アンペアブレーカ)工事者証(地上作業のみ).pdf",
            "釼持　政宏_資格書チェックリスト.pdf",
            "見たことのない証.pdf",
        ],
        "髙橋　翔太": ["運転免許証.pdf"],
    }.items():
        person_dir = tmp_path / person
        person_dir.mkdir()
        for name in files:
            (person_dir / name).write_bytes(PDF)
    return tmp_path


@pytest.fixture
def dates_csv(tmp_path):
    path = tmp_path / "有効期限.csv"
    path.write_text(
        "氏名,ファイル名,取得日,有効期限\n"
        "釼持　政宏,高圧ケーブル工事技能認定証.pdf,2018-11-09,2029-03-31\n"
        "高橋翔太,運転免許証.pdf,2026-05-13,2031-06-17\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def workers(company_a):
    masahiro = Worker.unscoped.create(company=company_a, name="釼持　政宏")
    shota = Worker.unscoped.create(company=company_a, name="高橋　翔太")
    WorkerQualification.unscoped.create(
        company=company_a, worker=masahiro, name="電気工事士　1種",
    )
    WorkerQualification.unscoped.create(
        company=company_a, worker=masahiro, name="高圧ケーブル工事",
    )
    WorkerQualification.unscoped.create(
        company=company_a, worker=masahiro, name="引込線",
    )
    WorkerQualification.unscoped.create(
        company=company_a, worker=shota, name="運転免許証",
    )
    return masahiro, shota


class TestReadFolder:
    def test_台紙は対象にしない(self, folder):
        names = [path.name for _p, path, _n, _pr in collect_files(folder)]

        assert "釼持　政宏_資格書チェックリスト.pdf" not in names
        assert "第一種電気工事士免状.pdf" in names

    def test_読み替え表にないファイルは資格名が空(self, folder):
        unknown = [
            path.name for _p, path, name, _pr in collect_files(folder) if name is None
        ]

        assert unknown == ["見たことのない証.pdf"]

    def test_区分は資格名から決める(self):
        assert category_for("電気工事士　1種") == "license"
        assert category_for("低圧電気取扱業務特別教育") == "education"
        assert category_for("玉掛け・吊上げ荷重1ｔ以上") == "skill_course"


class TestDates:
    def test_CSVを読む(self, dates_csv):
        dates = read_dates(dates_csv)

        assert dates[("高橋翔太", "運転免許証.pdf")] == (
            datetime.date(2026, 5, 13), datetime.date(2031, 6, 17),
        )

    def test_旧字の氏名も同じとみなす(self, dates_csv):
        dates = read_dates(dates_csv)

        assert ("剣持政宏", "高圧ケーブル工事技能認定証.pdf") in dates


@pytest.mark.django_db
class TestImport:
    def test_確認だけでは登録しない(self, company_a, folder, workers):
        report = import_certificates(
            folder, company_a, Worker, WorkerQualification, apply=False,
        )

        assert len(report["attached"]) == 4
        assert not WorkerQualification.unscoped.exclude(certificate_image="").exists()

    def test_添付して期限を入れる(self, company_a, folder, workers, dates_csv):
        import_certificates(
            folder, company_a, Worker, WorkerQualification,
            dates=read_dates(dates_csv), apply=True,
        )

        cable = WorkerQualification.unscoped.get(name="高圧ケーブル工事")
        assert cable.certificate_image.name.endswith(".pdf")
        assert cable.expiry_date == datetime.date(2029, 3, 31)
        assert cable.acquired_date == datetime.date(2018, 11, 9)

        license_ = WorkerQualification.unscoped.get(name="運転免許証")
        assert license_.expiry_date == datetime.date(2031, 6, 17)

    def test_期限の無いものは日付を入れない(self, company_a, folder, workers, dates_csv):
        import_certificates(
            folder, company_a, Worker, WorkerQualification,
            dates=read_dates(dates_csv), apply=True,
        )

        first = WorkerQualification.unscoped.get(name="電気工事士　1種")
        assert first.certificate_image
        assert first.expiry_date is None
        assert first.acquired_date is None

    def test_同じ資格の2枚目は添付しない(self, company_a, folder, workers):
        report = import_certificates(
            folder, company_a, Worker, WorkerQualification, apply=True,
        )

        hikikomi = WorkerQualification.unscoped.get(name="引込線")
        # 保存名からは記号が落ちる（Django がファイル名を整える）
        assert "柱上地上作業" in hikikomi.certificate_image.name
        assert report["skipped_duplicate"] == [
            ("釼持　政宏", "引込線", "引込線(アンペアブレーカ)工事者証(地上作業のみ).pdf"),
        ]

    def test_保有資格が無ければ作る(self, company_a, folder, workers):
        WorkerQualification.unscoped.filter(name="電気工事士　1種").delete()

        report = import_certificates(
            folder, company_a, Worker, WorkerQualification, apply=True,
        )

        assert ("釼持　政宏", "電気工事士　1種") in report["created"]
        created = WorkerQualification.unscoped.get(name="電気工事士　1種")
        assert created.category == "license"
        assert created.certificate_image

    def test_作業員が見つからないときは報告する(self, company_a, folder, workers):
        Worker.unscoped.filter(name="高橋　翔太").delete()

        report = import_certificates(
            folder, company_a, Worker, WorkerQualification, apply=True,
        )

        assert report["unknown_worker"] == ["髙橋　翔太"]

    def test_他社の資格には触れない(self, company_a, company_b, folder, workers):
        other = Worker.unscoped.create(company=company_b, name="釼持　政宏")
        other_qual = WorkerQualification.unscoped.create(
            company=company_b, worker=other, name="電気工事士　1種",
        )

        import_certificates(folder, company_a, Worker, WorkerQualification, apply=True)

        other_qual.refresh_from_db()
        assert not other_qual.certificate_image


@pytest.mark.django_db
class TestPdfAttachment:
    """保有資格の証明書に PDF を登録できる（ADR-0082）。"""

    def test_フォームからPDFを登録できる(self, company_a):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.workers.forms import WorkerQualificationForm

        worker = Worker.unscoped.create(company=company_a, name="電工太郎")
        form = WorkerQualificationForm(
            {"name": "電気工事士　1種", "category": "license"},
            {"certificate_image": SimpleUploadedFile(
                "menjou.pdf", PDF, content_type="application/pdf",
            )},
        )

        assert form.is_valid(), form.errors
        qualification = form.save(commit=False)
        qualification.company = company_a
        qualification.worker = worker
        qualification.save()

        assert qualification.certificate_is_pdf is True

    def test_決めた拡張子以外は断る(self, company_a):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.workers.forms import WorkerQualificationForm

        form = WorkerQualificationForm(
            {"name": "電気工事士　1種", "category": "license"},
            {"certificate_image": SimpleUploadedFile(
                "cert.exe", b"MZ", content_type="application/octet-stream",
            )},
        )

        assert not form.is_valid()
        assert "certificate_image" in form.errors


@pytest.mark.django_db
class TestPersonAliases:
    """漢字の名前とローマ字の登録を同じ人として扱う（ADR-0082）。

    「釼持雅崇」は Masataka Kemmochi として登録されている。
    """

    def test_ローマ字で登録された作業員にも添付する(self, company_a, tmp_path):
        from apps.workers.certificate_import import import_certificates

        person_dir = tmp_path / "釼持雅崇"
        person_dir.mkdir()
        (person_dir / "産業廃棄物処理業許可申請講習会(更新・収集運搬課程)修了証.pdf").write_bytes(
            PDF,
        )
        worker = Worker.unscoped.create(company=company_a, name="Masataka Kemmochi")

        report = import_certificates(
            tmp_path, company_a, Worker, WorkerQualification, apply=True,
        )

        assert report["unknown_worker"] == []
        qualification = WorkerQualification.unscoped.get(worker=worker)
        assert qualification.name == "産業廃棄物処理業許可申請講習会（更新・収集運搬課程）"
        assert qualification.certificate_image
        # 技能講習でも特別教育でもない講習会なので「その他」に入れる
        assert qualification.category == "other"

    def test_姓名の順が逆でも同じ人とみなす(self):
        from apps.workers.certificate_import import name_keys

        assert name_keys("釼持雅崇") & name_keys("Kemmochi Masataka")

    def test_別の人とは混ざらない(self):
        from apps.workers.certificate_import import name_keys

        assert not (name_keys("釼持雅崇") & name_keys("釼持　政宏"))


@pytest.mark.django_db
class TestMasatakaMigration:
    """データ移送 0022 と同じ手順で、資格名だけ先に登録できる（ADR-0082）。"""

    def test_資格名だけを先に登録する(self, company_a):
        from apps.workers.certificate_import import category_for, name_keys

        worker = Worker.unscoped.create(company=company_a, name="Masataka Kemmochi")
        name = "産業廃棄物処理業許可申請講習会（更新・収集運搬課程）"

        found = next(
            w for w in Worker.unscoped.filter(company=company_a)
            if name_keys(w.name) & name_keys("釼持雅崇")
        )
        WorkerQualification.unscoped.get_or_create(
            company=company_a, worker=found, name=name,
            defaults={"category": category_for(name)},
        )

        assert found == worker
        assert WorkerQualification.unscoped.filter(worker=worker, name=name).count() == 1


@pytest.mark.django_db
class TestZipUpload:
    """ZIP をアップロードして取り込む（ADR-0091）。"""

    @pytest.fixture
    def admin_user(self, company_a, user_a):
        Worker.unscoped.create(
            company=company_a, name="事務花子", employee_code="Y01", user=user_a,
        )
        return user_a

    def _zip(self, tmp_path, *, root_folder=True, extra=()):
        import io
        import zipfile

        buffer = io.BytesIO()
        prefix = "資格書一覧/" if root_folder else ""
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr(f"{prefix}髙橋　翔太/運転免許証.pdf", PDF)
            zf.writestr(
                f"{prefix}有効期限.csv",
                "氏名,ファイル名,取得日,有効期限\n"
                "髙橋　翔太,運転免許証.pdf,2026-05-13,2031-06-17\n",
            )
            for name, content in extra:
                zf.writestr(name, content)
        buffer.seek(0)
        return buffer

    def test_確認だけなら登録しない(self, client, company_a, admin_user, tmp_path):
        from django.core.files.uploadedfile import SimpleUploadedFile

        Worker.unscoped.create(company=company_a, name="高橋　翔太")
        client.force_login(admin_user)

        res = client.post(reverse("workers:certificate_import"), {
            "archive": SimpleUploadedFile(
                "certs.zip", self._zip(tmp_path).read(), content_type="application/zip",
            ),
        })

        assert res.status_code == 200
        assert "運転免許証" in res.content.decode()
        assert not WorkerQualification.unscoped.exclude(certificate_image="").exists()

    def test_登録するとPDFと期限が入る(self, client, company_a, admin_user, tmp_path):
        import datetime

        from django.core.files.uploadedfile import SimpleUploadedFile

        worker = Worker.unscoped.create(company=company_a, name="高橋　翔太")
        client.force_login(admin_user)

        client.post(reverse("workers:certificate_import"), {
            "archive": SimpleUploadedFile(
                "certs.zip", self._zip(tmp_path).read(), content_type="application/zip",
            ),
            "apply": "on",
        })

        qualification = WorkerQualification.unscoped.get(worker=worker)
        assert qualification.name == "運転免許証"
        assert qualification.certificate_image.name.endswith(".pdf")
        assert qualification.expiry_date == datetime.date(2031, 6, 17)

    def test_親フォルダが無いZIPでも読める(self, client, company_a, admin_user, tmp_path):
        from django.core.files.uploadedfile import SimpleUploadedFile

        Worker.unscoped.create(company=company_a, name="高橋　翔太")
        client.force_login(admin_user)

        client.post(reverse("workers:certificate_import"), {
            "archive": SimpleUploadedFile(
                "certs.zip",
                self._zip(tmp_path, root_folder=False).read(),
                content_type="application/zip",
            ),
            "apply": "on",
        })

        assert WorkerQualification.unscoped.exclude(certificate_image="").count() == 1

    def test_上の階層へ抜ける名前は展開しない(self, tmp_path):
        from apps.workers.certificate_import import extract_archive

        archive = self._zip(tmp_path, extra=(("../逃げ出す.pdf", PDF),))

        root = extract_archive(archive, tmp_path / "out")

        assert not (tmp_path / "逃げ出す.pdf").exists()
        assert (root / "髙橋　翔太" / "運転免許証.pdf").exists()

    def test_PDFとCSV以外は展開しない(self, tmp_path):
        from apps.workers.certificate_import import extract_archive

        archive = self._zip(tmp_path, extra=(("資格書一覧/悪い.exe", b"MZ"),))

        root = extract_archive(archive, tmp_path / "out")

        assert not (root / "悪い.exe").exists()

    def test_事務員でも管理者でもない人は使えない(self, client, company_a, user_a):
        Worker.unscoped.create(
            company=company_a, name="電工太郎", employee_code="E01", user=user_a,
        )
        client.force_login(user_a)

        assert client.get(reverse("workers:certificate_import")).status_code == 403


class TestYokoFiles:
    """陽子さんの4件の読み替え（ADR-0082）。

    あとから足された資格証で、名前が資格保有一覧の見出しと違うもの。
    """

    @pytest.mark.parametrize(("file_stem", "expected"), [
        ("運転免許証", "運転免許証"),
        ("1級電気工事施工管理技士 技術検定合格証明書", "電気工事施工監理技士　１級"),
        ("安全衛生責任者教育修了証", "職長・安全衛生責任者教育"),
        ("3M工法修得認定証", "3M工法取得認定（高圧端末 常温収縮）"),
    ])
    def test_資格名に読み替える(self, file_stem, expected):
        from apps.workers.certificate_import import FILE_TO_QUALIFICATION

        assert FILE_TO_QUALIFICATION[file_stem][0] == expected

    def test_職長の修了証は内容の広いものを優先する(self):
        from apps.workers.certificate_import import FILE_TO_QUALIFICATION

        full = FILE_TO_QUALIFICATION["職長・安全衛生責任者教育修了証"][1]
        partial = FILE_TO_QUALIFICATION["安全衛生責任者教育修了証"][1]

        assert full > partial
