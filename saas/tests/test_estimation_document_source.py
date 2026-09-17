"""案件資料の提供元と登録者（ADR-0085）。

確かめること:

1. 誰からもらったか（提供元）と、社内の誰が登録したか（登録者）を残せる
2. 登録者を空で送ると、ログインしている人の名前が入る。作業員が紐づいていれば氏名
3. 候補は過去に入れた値そのもの。マスタは持たない
4. 詳細画面の一覧に両方出る
5. 他社の値は候補に出ない（テナント越境）
"""
import io

import openpyxl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import User
from apps.estimation.forms import EstimationDocumentForm, registrant_name
from apps.estimation.models import EstimationDocument, EstimationProject, Orderer
from apps.workers.models import Worker

ADD_URL = "/estimation/projects/{pk}/documents/add/"


def _pdf(name="公告.pdf"):
    body = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    return SimpleUploadedFile(name, body, content_type="application/pdf")


def _xlsx(name="内訳書.xlsx"):
    buffer = io.BytesIO()
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "数量"
    workbook.save(buffer)
    return SimpleUploadedFile(name, buffer.getvalue())


def _project(company, name="七沢センター改修"):
    orderer, _ = Orderer.unscoped.get_or_create(company=company, name="厚木市")
    return EstimationProject.unscoped.create(
        company=company, name=name, orderer=orderer,
        status=EstimationProject.Status.ESTIMATING,
    )


def _document(project, **kwargs):
    fields = {
        "name": "公告",
        "doc_type": EstimationDocument.DocType.ANNOUNCEMENT,
        "kind": EstimationDocument.Kind.PDF,
        "original_filename": "公告.pdf",
    }
    fields.update(kwargs)
    document = EstimationDocument(company=project.company, project=project, **fields)
    document.file = _pdf()
    document.save()
    return document


# ---------------------------------------------------------------------------
# 保存
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSaving:
    def test_提供元と登録者を残せる(self, client, company_a, user_a):
        project = _project(company_a)
        client.force_login(user_a)

        res = client.post(ADD_URL.format(pk=project.pk), {
            "name": "入札公告", "doc_type": "announcement", "file": _pdf(),
            "provided_by": "厚木市 契約課 高橋さん",
            "registered_by_name": "剣持 太郎",
        })

        assert res.status_code == 302
        document = EstimationDocument.unscoped.get(company=company_a, project=project)
        assert document.provided_by == "厚木市 契約課 高橋さん"
        assert document.registered_by_name == "剣持 太郎"

    def test_登録者が空ならログインしている人が入る(self, client, company_a, user_a):
        project = _project(company_a)
        client.force_login(user_a)

        client.post(ADD_URL.format(pk=project.pk), {
            "name": "仕様書", "doc_type": "spec", "file": _pdf(),
            "provided_by": "", "registered_by_name": "",
        })

        document = EstimationDocument.unscoped.get(company=company_a)
        assert document.registered_by_name == user_a.get_username()

    def test_作業員が紐づいていれば氏名が入る(self, client, company_a):
        """代理で登録することがあるので、名前は利用者IDではなく人の名前で残す。"""
        user = User.objects.create_user(
            username="office01", password="pass-12345", company=company_a,
        )
        Worker.unscoped.create(
            company=company_a, user=user, name="剣持 花子",
            employee_code="E001", hourly_cost=3000,
        )
        project = _project(company_a)
        client.force_login(user)

        client.post(ADD_URL.format(pk=project.pk), {
            "name": "図面", "doc_type": "drawing", "file": _pdf(),
        })

        document = EstimationDocument.unscoped.get(company=company_a)
        assert document.registered_by_name == "剣持 花子"

    def test_提供元は空のままでもよい(self, client, company_a, user_a):
        """出どころが分からない資料もある。空で止めると登録そのものが止まる。"""
        project = _project(company_a)
        client.force_login(user_a)

        res = client.post(ADD_URL.format(pk=project.pk), {
            "name": "内訳書", "doc_type": "boq", "file": _xlsx(),
        })

        assert res.status_code == 302
        assert EstimationDocument.unscoped.get(company=company_a).provided_by == ""

    def test_登録した人は履歴にも残る(self, client, company_a, user_a):
        project = _project(company_a)
        client.force_login(user_a)

        client.post(ADD_URL.format(pk=project.pk), {
            "name": "公告", "doc_type": "announcement", "file": _pdf(),
            "provided_by": "元請 山田建設",
        })

        document = EstimationDocument.unscoped.get(company=company_a)
        assert document.history.first().provided_by == "元請 山田建設"


@pytest.mark.django_db
class TestRegistrantName:
    def test_作業員が無ければ利用者名(self, company_a):
        user = User.objects.create_user(
            username="plain", password="pass-12345", company=company_a,
        )
        assert registrant_name(user) == "plain"

    def test_ログインしていなければ空(self):
        assert registrant_name(None) == ""


# ---------------------------------------------------------------------------
# 候補
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestChoices:
    def test_過去に入れた提供元が候補に出る(self, company_a):
        project = _project(company_a)
        _document(project, provided_by="厚木市 契約課")
        _document(project, provided_by="元請 山田建設")

        form = EstimationDocumentForm(company=company_a)

        assert form.provided_by_choices == ["元請 山田建設", "厚木市 契約課"]

    def test_同じ提供元は1回だけ出る(self, company_a):
        project = _project(company_a)
        _document(project, provided_by="厚木市 契約課")
        _document(project, provided_by="厚木市 契約課")

        form = EstimationDocumentForm(company=company_a)

        assert form.provided_by_choices == ["厚木市 契約課"]

    def test_空の値は候補に出ない(self, company_a):
        project = _project(company_a)
        _document(project, provided_by="")

        assert EstimationDocumentForm(company=company_a).provided_by_choices == []

    def test_過去に入れた登録者が候補に出る(self, company_a):
        project = _project(company_a)
        _document(project, registered_by_name="剣持 太郎")

        form = EstimationDocumentForm(company=company_a)

        assert form.registered_by_choices == ["剣持 太郎"]

    def test_登録者の初期値はログインしている人(self, company_a):
        user = User.objects.create_user(
            username="office02", password="pass-12345", company=company_a,
        )
        Worker.unscoped.create(
            company=company_a, user=user, name="剣持 次郎",
            employee_code="E002", hourly_cost=3000,
        )

        form = EstimationDocumentForm(company=company_a, user=user)

        assert form.fields["registered_by_name"].initial == "剣持 次郎"


# ---------------------------------------------------------------------------
# 画面
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDetailScreen:
    def test_一覧に提供元と登録者が出る(self, client, company_a, user_a):
        project = _project(company_a)
        _document(project, provided_by="厚木市 契約課", registered_by_name="剣持 太郎")
        client.force_login(user_a)

        html = client.get(f"/estimation/projects/{project.pk}/").content.decode()

        assert "提供元" in html
        assert "厚木市 契約課" in html
        assert "剣持 太郎" in html

    def test_入力欄と候補の一覧が出る(self, client, company_a, user_a):
        project = _project(company_a)
        _document(project, provided_by="元請 山田建設")
        client.force_login(user_a)

        html = client.get(f"/estimation/projects/{project.pk}/").content.decode()

        assert 'name="provided_by"' in html
        assert 'name="registered_by_name"' in html
        assert 'id="doc-provided-by-options"' in html
        assert "元請 山田建設" in html


# ---------------------------------------------------------------------------
# テナント越境
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTenantIsolation:
    def test_他社の提供元は候補に出ない(self, company_a, company_b):
        _document(_project(company_b, "他社案件"), provided_by="他社の窓口")

        form = EstimationDocumentForm(company=company_a)

        assert form.provided_by_choices == []

    def test_他社の登録者は候補に出ない(self, company_a, company_b):
        _document(_project(company_b, "他社案件"), registered_by_name="他社の人")

        form = EstimationDocumentForm(company=company_a)

        assert form.registered_by_choices == []
