"""アップロードしたファイルを、本番でもログインした人に返す（ADR-0093）。

これまで /media/ は DEBUG=True のときだけ配信していたため、
本番では資格証の「表示」が Not Found になっていた。
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.workers.models import Worker, WorkerQualification

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


@pytest.fixture
def qualification(company_a, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    worker = Worker.unscoped.create(company=company_a, name="電工太郎")
    return WorkerQualification.unscoped.create(
        company=company_a, worker=worker, name="電気工事士　1種",
        certificate_image=SimpleUploadedFile(
            "menjou.pdf", PDF, content_type="application/pdf",
        ),
    )


@pytest.mark.django_db
class TestServeMedia:
    def test_本番の設定でも表示できる(self, client, user_a, qualification, settings):
        settings.DEBUG = False
        client.force_login(user_a)

        res = client.get(qualification.certificate_image.url)

        assert res.status_code == 200
        assert res["Content-Type"] == "application/pdf"
        assert b"".join(res.streaming_content) == PDF

    def test_画面の中で開く(self, client, user_a, qualification):
        client.force_login(user_a)

        res = client.get(qualification.certificate_image.url)

        assert res["Content-Disposition"] == "inline"
        assert "private" in res["Cache-Control"]

    def test_ログインしていない人は見られない(self, client, qualification):
        res = client.get(qualification.certificate_image.url)

        assert res.status_code == 302
        assert reverse("login") in res["Location"]

    def test_無いファイルは404(self, client, user_a, qualification):
        client.force_login(user_a)

        assert client.get("/media/qualifications/ない.pdf").status_code == 404

    @pytest.mark.parametrize("path", [
        "/media/../config/settings.py",
        "/media/..%2F..%2Fconfig/settings.py",
        "/media/qualifications/../../manage.py",
    ])
    def test_上の階層は返さない(self, client, user_a, qualification, path):
        client.force_login(user_a)

        assert client.get(path).status_code in (404, 301, 302)
