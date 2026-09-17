"""資格証の提出チェックリスト（ADR-0081）。

- 作業員（縦）×資格名（横）の表にして、資格証が登録済みなら〇、未提出なら△
- 事務員・管理者だけが見られる
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.workers.models import Worker, WorkerQualification

# 1x1 の PNG。画像として扱えれば中身は何でもよい
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def admin_user(company_a, user_a):
    """社員番号が Y で始まる管理者。書類系の画面はこの人だけが見られる。"""
    Worker.unscoped.create(
        company=company_a, name="事務 花子", employee_code="Y01", user=user_a,
    )
    return user_a


@pytest.fixture
def workers(company_a):
    taro = Worker.unscoped.create(company=company_a, name="電工太郎", employee_code="E01")
    jiro = Worker.unscoped.create(company=company_a, name="電工次郎", employee_code="E02")
    WorkerQualification.unscoped.create(
        company=company_a, worker=taro, name="第二種電気工事士",
        certificate_image=SimpleUploadedFile("cert.png", PNG, content_type="image/png"),
    )
    WorkerQualification.unscoped.create(
        company=company_a, worker=taro, name="玉掛け技能講習",
    )
    WorkerQualification.unscoped.create(
        company=company_a, worker=jiro, name="玉掛け技能講習",
    )
    return taro, jiro


@pytest.mark.django_db
class TestChecklist:
    def test_登録されていれば丸が付く(self, client, admin_user, workers):
        client.force_login(admin_user)

        html = client.get(reverse("workers:cert_checklist")).content.decode()

        assert "第二種電気工事士" in html
        assert "玉掛け技能講習" in html
        assert "〇" in html
        assert "△" in html

    def test_提出の数を出す(self, client, admin_user, workers):
        client.force_login(admin_user)

        html = client.get(reverse("workers:cert_checklist")).content.decode()

        # 3件中1件だけ資格証あり
        assert "1 / 3" in html
        assert "未提出 2 件" in html

    def test_事務員でも管理者でもない人は見られない(self, client, company_a, user_a):
        Worker.unscoped.create(
            company=company_a, name="電工太郎", employee_code="E01", user=user_a,
        )
        client.force_login(user_a)

        assert client.get(reverse("workers:cert_checklist")).status_code == 403

    def test_他社の資格は出ない(self, client, admin_user, workers, company_b):
        other = Worker.unscoped.create(company=company_b, name="他社太郎")
        WorkerQualification.unscoped.create(
            company=company_b, worker=other, name="他社だけの資格",
        )
        client.force_login(admin_user)

        html = client.get(reverse("workers:cert_checklist")).content.decode()

        assert "他社だけの資格" not in html
        assert "他社太郎" not in html
