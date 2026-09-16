"""自社情報（会社の書類）（ADR-0071）。

ここで固定すること:
1. 会社ごとに書類の種類の一覧を持つ。無ければ既定の11種類を入れる。種類ごとに
   いちばん新しい書類と前の版を出す
2. 受け付けるのは PDF（.pdf）と Excel（.xlsx・.xls）だけ。中身の先頭の形も見る
3. 登録には「中身を確認した」のチェックが要る。誰がいつ確認したかを残す
4. 一覧に無い書類は名前を付けて足せ、会社の種類の一覧にも入る
5. AI の読み取りは押したときだけ動く。要約と項目を残し、空の日付には読み取った日を入れる
   （人が直せる。AI の値をそのまま確定させない）
6. 更新日の3か月前・1か月前・2週間前と当日・過ぎた日に、社長・管理者・事務員へ知らせる。
   同じ段階は1回だけ。更新日を直したら数え直す
7. 見られるのは社長・管理者（Y）・事務員・Developer だけ。会社をまたいでは見えない
8. 記録は会社ごとに分かれ、変更履歴と管理画面がある
"""

import datetime
import io

import openpyxl
import pytest
from django.contrib import admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from simple_history.admin import SimpleHistoryAdmin

from apps.core.tenant_context import set_current_company
from apps.notifications.models import Notification
from apps.tenants import company_document_llm
from apps.tenants.company_documents import (
    DEFAULT_TYPES,
    document_groups,
    ensure_default_types,
    save_company_document,
)
from apps.tenants.document_alerts import check_company_document_alerts
from apps.tenants.models import CompanyDocument, CompanyDocumentType
from apps.workers.models import Position, Worker

LIST_URL = "/company/"
CREATE_URL = "/company/new/"
OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")


def _pdf(name="経審.pdf"):
    body = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    return SimpleUploadedFile(name, body, content_type="application/pdf")


def _xlsx(name="決算書.xlsx", value="売上高"):
    buffer = io.BytesIO()
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = value
    workbook.active["B1"] = 1234
    workbook.save(buffer)
    return SimpleUploadedFile(name, buffer.getvalue())


def _manager(django_user_model, company, username="boss", code="Y001"):
    """自社情報を見られる人（社員番号 Y の管理者）。"""
    user = django_user_model.objects.create_user(
        username=username, password="testpass123", company=company,
    )
    position = Position.unscoped.get_or_create(company=company, name="正社員")[0]
    Worker.unscoped.create(
        company=company, name="管理 太郎", employee_code=code, position=position, user=user,
    )
    return user


def _document(company, user=None, **values):
    ensure_default_types(company)
    doc_type = CompanyDocumentType.unscoped.get(
        company=company, name="経営規模等評価結果通知書（経審）",
    )
    values.setdefault("issued_on", datetime.date(2026, 4, 1))
    return save_company_document(
        company,
        doc_type=doc_type,
        name=doc_type.name,
        uploaded=_pdf(),
        kind="pdf",
        user=user,
        **values,
    )


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def manager(django_user_model, company_a):
    return _manager(django_user_model, company_a)


@pytest.fixture
def logged_in(client, manager):
    client.force_login(manager)
    return client


# ---------------------------------------------------------------------------
# 種類の一覧
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTypes:
    def test_既定は11種類で更新の有無が付く(self, company_a):
        ensure_default_types(company_a)

        types = CompanyDocumentType.unscoped.filter(company=company_a)
        assert types.count() == len(DEFAULT_TYPES) == 11
        assert types.get(name="建設業許可証").has_renewal is True
        assert types.get(name="登記事項証明書").has_renewal is False

    def test_2回呼んでも増えない(self, company_a):
        ensure_default_types(company_a)
        ensure_default_types(company_a)

        assert CompanyDocumentType.unscoped.filter(company=company_a).count() == 11

    def test_使わなくした種類は一覧に出ない(self, company_a):
        ensure_default_types(company_a)
        CompanyDocumentType.unscoped.filter(company=company_a, name="印鑑証明書").update(
            is_active=False,
        )

        names = [g["type"].name for g in document_groups(company_a) if g["type"]]
        assert "印鑑証明書" not in names
        # 全部外した会社に既定を戻さない
        CompanyDocumentType.unscoped.filter(company=company_a).update(is_active=False)
        ensure_default_types(company_a)
        assert CompanyDocumentType.unscoped.filter(company=company_a).count() == 11

    def test_入れ直すと前の版が残る(self, company_a, manager):
        first = _document(company_a, manager, issued_on=datetime.date(2025, 4, 1))
        second = _document(company_a, manager, issued_on=datetime.date(2026, 4, 1))

        group = next(
            g for g in document_groups(company_a)
            if g["type"] and g["type"].name.startswith("経営規模")
        )
        assert group["latest"] == second
        assert group["older"] == [first]
        assert group["count"] == 2


# ---------------------------------------------------------------------------
# 登録
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreate:
    def _post(self, client, company, **extra):
        ensure_default_types(company)
        doc_type = CompanyDocumentType.unscoped.get(company=company, name="建設業許可証")
        data = {
            "doc_type": doc_type.pk,
            "file": _pdf("許可証.pdf"),
            "issued_on": "2026-04-01",
            "renewal_on": "2031-03-31",
            "memo": "",
            "confirmed": "on",
        }
        data.update(extra)
        return client.post(CREATE_URL, data)

    def test_登録すると確認した人と日時が残る(self, logged_in, company_a, manager):
        res = self._post(logged_in, company_a)

        document = CompanyDocument.unscoped.get()
        assert res.status_code == 302
        assert document.name == "建設業許可証"
        assert document.kind == "pdf"
        assert document.original_filename == "許可証.pdf"
        assert document.renewal_on == datetime.date(2031, 3, 31)
        assert document.confirmed is True
        assert document.confirmed_by == manager
        assert document.confirmed_at is not None
        assert document.file.name.startswith(f"company_documents/{company_a.pk}/")
        assert "許可証" not in document.file.name

    def test_確認のチェックが無ければ登録しない(self, logged_in, company_a):
        res = self._post(logged_in, company_a, confirmed="")

        assert res.status_code == 200
        assert "中身を確認してから" in res.content.decode()
        assert not CompanyDocument.unscoped.exists()

    @pytest.mark.parametrize(
        "uploaded",
        [
            SimpleUploadedFile("写真.png", b"\x89PNG\r\n\x1a\n"),
            SimpleUploadedFile("偽物.pdf", b"not a pdf"),
            SimpleUploadedFile("図面.docx", b"PK\x03\x04"),
        ],
    )
    def test_PDFとExcel以外は登録しない(self, logged_in, company_a, uploaded):
        res = self._post(logged_in, company_a, file=uploaded)

        assert res.status_code == 200
        assert not CompanyDocument.unscoped.exists()

    def test_Excelも登録できる(self, logged_in, company_a):
        self._post(logged_in, company_a, file=_xlsx())

        assert CompanyDocument.unscoped.get().kind == "excel"

    def test_一覧に無い書類は名前を付けて足せる(self, logged_in, company_a):
        ensure_default_types(company_a)

        res = logged_in.post(CREATE_URL, {
            "doc_type": "",
            "new_name": " 経営事項審査の申請書 ",
            "has_renewal": "on",
            "file": _pdf(),
            "confirmed": "on",
        })

        assert res.status_code == 302
        doc_type = CompanyDocumentType.unscoped.get(company=company_a, name="経営事項審査の申請書")
        assert doc_type.has_renewal is True
        assert CompanyDocument.unscoped.get().doc_type == doc_type

    def test_同じ名前の種類は足せない(self, logged_in, company_a):
        ensure_default_types(company_a)

        res = logged_in.post(CREATE_URL, {
            "doc_type": "", "new_name": "建設業許可証", "file": _pdf(), "confirmed": "on",
        })

        assert "もう一覧にあります" in res.content.decode()
        assert not CompanyDocument.unscoped.exists()


# ---------------------------------------------------------------------------
# AI の読み取り
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAnalyze:
    def test_読み取った要点と項目を残し空の更新日を埋める(
        self, logged_in, company_a, manager, monkeypatch,
    ):
        document = _document(company_a, manager)
        monkeypatch.setattr(
            company_document_llm,
            "analyze",
            lambda doc, data, user=None: {
                "document_type": "経営規模等評価結果通知書",
                "issuer": "神奈川県知事",
                "issued_on": "",
                "renewal_on": "2027-06-30",
                "fields": [{"label": "総合評定値（P）", "value": "812"}],
                "summary": "令和8年の経営規模等評価の結果。総合評定値は812。",
            },
        )

        res = logged_in.post(f"/company/{document.pk}/analyze/", follow=True)

        document.refresh_from_db()
        assert document.ai_summary.startswith("令和8年")
        assert document.ai_fields == [{"label": "総合評定値（P）", "value": "812"}]
        assert document.ai_checked_at is not None
        assert document.renewal_on == datetime.date(2027, 6, 30)
        assert "読み取った日付を入れました" in res.content.decode()

    def test_人が入れた日付は上書きしない(self, logged_in, company_a, manager, monkeypatch):
        document = _document(company_a, manager, renewal_on=datetime.date(2030, 1, 1))
        monkeypatch.setattr(
            company_document_llm,
            "analyze",
            lambda doc, data, user=None: {
                "document_type": "", "issuer": "", "issued_on": "2020-01-01",
                "renewal_on": "2027-06-30", "fields": [], "summary": "要約",
            },
        )

        logged_in.post(f"/company/{document.pk}/analyze/")

        document.refresh_from_db()
        assert document.renewal_on == datetime.date(2030, 1, 1)
        assert document.issued_on == datetime.date(2026, 4, 1)

    def test_読み取れなければ知らせるだけ(self, logged_in, company_a, manager, monkeypatch):
        document = _document(company_a, manager)
        monkeypatch.setattr(
            company_document_llm, "analyze", lambda doc, data, user=None: None,
        )

        res = logged_in.post(f"/company/{document.pk}/analyze/", follow=True)

        document.refresh_from_db()
        assert document.ai_checked_at is None
        assert "AI で読み取れませんでした" in res.content.decode()

    def test_Excelは中身を文字にして渡す(self):
        text = company_document_llm.excel_to_text(_xlsx(value="完成工事高").read())

        assert "完成工事高" in text
        assert "1234" in text


# ---------------------------------------------------------------------------
# 更新の知らせ
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRenewalAlerts:
    def _document(self, company, user, renewal_on):
        return _document(company, user, renewal_on=renewal_on)

    @pytest.mark.parametrize("days", [90, 30, 14])
    def test_3か月前1か月前2週間前に知らせる(self, company_a, manager, days):
        today = datetime.date(2026, 9, 16)
        document = self._document(company_a, manager, today + datetime.timedelta(days=days))

        created = check_company_document_alerts(company_a, today=today)

        assert created == 1
        notification = Notification.unscoped.filter(recipient=manager).first()
        assert f"残り{days}日" in notification.title
        document.refresh_from_db()
        assert document.reminder_step is not None

    def test_同じ段階は1回だけ(self, company_a, manager):
        today = datetime.date(2026, 9, 16)
        self._document(company_a, manager, today + datetime.timedelta(days=80))

        assert check_company_document_alerts(company_a, today=today) == 1
        assert check_company_document_alerts(company_a, today=today) == 0

    def test_まだ先の更新日では知らせない(self, company_a, manager):
        today = datetime.date(2026, 9, 16)
        self._document(company_a, manager, today + datetime.timedelta(days=120))

        assert check_company_document_alerts(company_a, today=today) == 0

    def test_当日と過ぎた日にも知らせる(self, company_a, manager):
        today = datetime.date(2026, 9, 16)
        self._document(company_a, manager, today)

        assert check_company_document_alerts(company_a, today=today) == 1
        assert check_company_document_alerts(
            company_a, today=today + datetime.timedelta(days=1),
        ) == 1
        assert "過ぎています" in Notification.unscoped.order_by("-pk").first().title

    def test_更新日を直したら数え直す(self, company_a, manager):
        today = datetime.date(2026, 9, 16)
        document = self._document(company_a, manager, today + datetime.timedelta(days=20))
        check_company_document_alerts(company_a, today=today)

        document.renewal_on = today + datetime.timedelta(days=200)
        document.save()

        document.refresh_from_db()
        assert document.reminder_step is None

    def test_更新日が無い書類は知らせない(self, company_a, manager):
        self._document(company_a, manager, None)

        assert check_company_document_alerts(company_a, today=datetime.date(2026, 9, 16)) == 0


# ---------------------------------------------------------------------------
# 見られる人・テナント
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAccess:
    def test_一般の社員は見られない(self, client, company_a, user_a, manager):
        _document(company_a, manager)
        client.force_login(user_a)

        assert client.get(LIST_URL).status_code == 403
        assert client.get(CREATE_URL).status_code == 403

    def test_ログインしていなければログイン画面へ(self, client):
        res = client.get(LIST_URL)

        assert res.status_code == 302
        assert "/login/" in res["Location"]

    def test_他社の書類は見えない(self, client, django_user_model, company_a, company_b, manager):
        mine = _document(company_a, manager)
        other_manager = _manager(django_user_model, company_b, username="boss_b", code="Y900")
        other = _document(company_b, other_manager)
        client.force_login(other_manager)

        assert client.get(f"/company/{mine.pk}/").status_code == 404
        assert client.get(f"/company/{mine.pk}/file/").status_code == 404

        set_current_company(company_a)
        try:
            assert list(CompanyDocument.objects.all()) == [mine]
            assert CompanyDocument.objects.filter(pk=other.pk).count() == 0
        finally:
            set_current_company(None)

    def test_PDFは画面で開きExcelはダウンロードになる(self, logged_in, company_a, manager):
        pdf = _document(company_a, manager)
        excel = save_company_document(
            company_a,
            doc_type=None,
            name="決算書（財務諸表）",
            uploaded=_xlsx(),
            kind="excel",
            user=manager,
        )

        pdf_res = logged_in.get(f"/company/{pdf.pk}/file/")
        excel_res = logged_in.get(f"/company/{excel.pk}/file/")

        assert pdf_res["Content-Type"] == "application/pdf"
        assert pdf_res["Content-Disposition"].startswith("inline")
        assert excel_res["Content-Disposition"].startswith("attachment")


# ---------------------------------------------------------------------------
# 画面・モデル
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestScreens:
    def test_自社情報に書類と建設業許可が出る(self, logged_in, company_a, manager):
        _document(company_a, manager, renewal_on=timezone.localdate())

        html = logged_in.get(LIST_URL).content.decode()

        assert "自社情報" in html
        assert "経営規模等評価結果通知書（経審）" in html
        assert "建設業許可" in html
        assert "更新の近い書類" in html

    def test_サイドバーの名前が開発_自社情報になる(self, logged_in):
        html = logged_in.get(LIST_URL).content.decode()

        assert "開発・自社情報" in html
        assert reverse("tenants:company_document_list") == LIST_URL

    def test_消すとファイルも消える(
        self, logged_in, company_a, manager, media_root, django_capture_on_commit_callbacks,
    ):
        document = _document(company_a, manager)
        path = media_root / document.file.name
        assert path.exists()

        with django_capture_on_commit_callbacks(execute=True):
            logged_in.post(f"/company/{document.pk}/delete/")

        assert not CompanyDocument.unscoped.filter(pk=document.pk).exists()
        assert not path.exists()

    def test_変更履歴が残り管理画面に出る(self, company_a, manager):
        document = _document(company_a, manager)
        document.memo = "県へ提出済み"
        document.save()

        assert document.history.count() == 2
        for model in (CompanyDocumentType, CompanyDocument):
            assert isinstance(admin.site._registry[model], SimpleHistoryAdmin)
