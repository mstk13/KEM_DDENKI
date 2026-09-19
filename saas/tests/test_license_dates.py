"""運転免許証の取得日・有効期限を入れる（ADR-0101）。

- 資格証が付いていて日付が空のものだけに入れる
- 既に入っている日付は上書きしない
- クレーン・デリック運転士免許証のような別の免許には入れない
"""

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.workers.license_dates import fill_license_dates, is_car_license
from apps.workers.models import Worker, WorkerQualification

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _qualification(company, worker, name, *, attached=True, **kwargs):
    return WorkerQualification.unscoped.create(
        company=company, worker=worker, name=name,
        certificate_image=(
            SimpleUploadedFile(f"{name}.pdf", PDF, content_type="application/pdf")
            if attached else ""
        ),
        **kwargs,
    )


class TestIsCarLicense:
    @pytest.mark.parametrize(("name", "expected"), [
        ("運転免許証", True),
        ("普通自動車第一種運転免許証", True),
        ("クレーン・デリック運転士免許証(クレーン限定)", False),
        ("電気工事士　1種", False),
    ])
    def test_車の免許だけを見分ける(self, name, expected):
        assert is_car_license(name) is expected


@pytest.mark.django_db
class TestFill:
    def test_空いているところに券面の日付を入れる(self, company_a):
        worker = Worker.unscoped.create(company=company_a, name="杉本　和幸")
        qualification = _qualification(company_a, worker, "運転免許証")

        report = fill_license_dates(company_a, WorkerQualification)

        qualification.refresh_from_db()
        assert qualification.acquired_date == datetime.date(2025, 2, 10)
        assert qualification.expiry_date == datetime.date(2030, 4, 9)
        assert len(report["filled"]) == 1

    def test_資格名がファイル名でも入る(self, company_a):
        worker = Worker.unscoped.create(company=company_a, name="片桐　徳男")
        qualification = _qualification(company_a, worker, "普通自動車第一種運転免許証")

        fill_license_dates(company_a, WorkerQualification)

        qualification.refresh_from_db()
        assert qualification.expiry_date == datetime.date(2028, 4, 11)

    def test_旧字の氏名でも合わせる(self, company_a):
        worker = Worker.unscoped.create(company=company_a, name="高橋　昇汰")
        qualification = _qualification(company_a, worker, "運転免許証")

        fill_license_dates(company_a, WorkerQualification)

        qualification.refresh_from_db()
        assert qualification.expiry_date == datetime.date(2031, 6, 17)

    def test_既に入っている日付は変えない(self, company_a):
        worker = Worker.unscoped.create(company=company_a, name="杉本　和幸")
        qualification = _qualification(
            company_a, worker, "運転免許証",
            acquired_date=datetime.date(2020, 1, 1),
            expiry_date=datetime.date(2029, 1, 1),
        )

        report = fill_license_dates(company_a, WorkerQualification)

        qualification.refresh_from_db()
        assert qualification.acquired_date == datetime.date(2020, 1, 1)
        assert qualification.expiry_date == datetime.date(2029, 1, 1)
        assert report["filled"] == []

    def test_片方だけ空なら空いているほうに入れる(self, company_a):
        worker = Worker.unscoped.create(company=company_a, name="杉本　和幸")
        qualification = _qualification(
            company_a, worker, "運転免許証", acquired_date=datetime.date(2020, 1, 1),
        )

        fill_license_dates(company_a, WorkerQualification)

        qualification.refresh_from_db()
        assert qualification.acquired_date == datetime.date(2020, 1, 1)
        assert qualification.expiry_date == datetime.date(2030, 4, 9)

    def test_資格証が付いていなければ入れない(self, company_a):
        worker = Worker.unscoped.create(company=company_a, name="杉本　和幸")
        qualification = _qualification(
            company_a, worker, "運転免許証", attached=False,
        )

        report = fill_license_dates(company_a, WorkerQualification)

        qualification.refresh_from_db()
        assert qualification.expiry_date is None
        assert report["no_file"] == [("杉本　和幸", "運転免許証")]

    def test_券面の日付が無い人は報告に出す(self, company_a):
        worker = Worker.unscoped.create(company=company_a, name="知らない　人")
        _qualification(company_a, worker, "運転免許証")

        report = fill_license_dates(company_a, WorkerQualification)

        assert report["unknown"] == [("知らない　人", "運転免許証")]

    def test_別の免許には入れない(self, company_a):
        worker = Worker.unscoped.create(company=company_a, name="釼持　政宏")
        qualification = _qualification(
            company_a, worker, "クレーン・デリック運転士免許証(クレーン限定)",
        )

        fill_license_dates(company_a, WorkerQualification)

        qualification.refresh_from_db()
        assert qualification.expiry_date is None

    def test_確認だけなら保存しない(self, company_a):
        worker = Worker.unscoped.create(company=company_a, name="杉本　和幸")
        qualification = _qualification(company_a, worker, "運転免許証")

        report = fill_license_dates(company_a, WorkerQualification, apply=False)

        qualification.refresh_from_db()
        assert qualification.expiry_date is None
        assert len(report["filled"]) == 1

    def test_全員分の券面を持っている(self):
        from apps.workers.license_dates import LICENSE_DATES

        # 資格書一覧にある免許証は12件（2026-09-18 時点）
        assert len(LICENSE_DATES) == 12
        for acquired, expiry in LICENSE_DATES.values():
            assert acquired < expiry
