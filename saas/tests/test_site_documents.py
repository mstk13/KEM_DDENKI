"""現場の提出書類（ADR-0065）。

ここで固定すること:
1. 現場の書類の一覧を初めて開くと、会社の最初のリスト（無ければ既定の24種類）が
   時期ごとに写る。2回開いても増えない。
   あとで会社のリストを変えても、写し済みの現場は変わらない
2. リストに無い書類を名前を付けて足せる。
   その現場だけか、次の現場からも最初のリストに入れるかを選べる。同じ名前は足せない
3. 書類ごとに PDF（.pdf）と Excel（.xlsx・.xls）を何件でも置ける。新しいものが上。
   拡張子だけ変えたファイル・ほかの形式・大きすぎるファイル・多すぎる件数は受け付けない
4. ファイルは同じ会社のログインした人だけが開ける。PDF は画面で開き、Excel はダウンロードになる
5. 状況（未作成・作成済み・提出済み・不要）と提出日を付けられる。
   ファイルを置くと「作成済み」になる。「不要」は数に入れない
6. ファイルを消すと保存したファイルも消える。足した書類は消せるが、最初のリストの書類は消せない
7. 記録は会社ごとに分かれ、変更履歴と管理画面がある
"""

import io
import zipfile
from urllib.parse import quote

import openpyxl
import pytest
from django.contrib import admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from simple_history.admin import SimpleHistoryAdmin

from apps.core.tenant_context import set_current_company
from apps.sites import documents
from apps.sites.documents import (
    DEFAULT_DOCUMENTS,
    UnsupportedDocumentFile,
    add_site_document,
    detect_file_kind,
    ensure_site_documents,
    save_document_files,
)
from apps.sites.models import (
    DocumentPhase,
    DocumentTemplate,
    Site,
    SiteDocument,
    SiteDocumentFile,
)

DEFAULT_COUNT = sum(len(names) for _, names in DEFAULT_DOCUMENTS)
OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")


def _pdf(name="施工計画書.pdf"):
    body = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    return SimpleUploadedFile(name, body, content_type="application/pdf")


def _xlsx(name="作業員名簿.xlsx"):
    buffer = io.BytesIO()
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "作業員名簿"
    workbook.save(buffer)
    return SimpleUploadedFile(name, buffer.getvalue())


def _xls(name="工程表.xls"):
    return SimpleUploadedFile(name, OLE_MAGIC + b"\x00" * 1024)


def _zip(name, entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for entry in entries:
            archive.writestr(entry, "<xml/>")
    return SimpleUploadedFile(name, buffer.getvalue())


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def site(company_a):
    return Site.unscoped.create(
        company=company_a, code="S001", name="A社ビル新築", status=Site.Status.IN_PROGRESS
    )


@pytest.fixture
def logged_in(client, user_a):
    client.force_login(user_a)
    return client


def _document(site, name="施工計画書"):
    ensure_site_documents(site)
    return SiteDocument.unscoped.get(site=site, name=name)


def _names(site):
    return set(SiteDocument.unscoped.filter(site=site).values_list("name", flat=True))


# ---------------------------------------------------------------------------
# 最初のリスト
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDefaultList:
    def test_既定は24種類(self):
        assert DEFAULT_COUNT == 24

    def test_初めて開くと既定の書類が時期ごとに写る(self, logged_in, site):
        res = logged_in.get(reverse("sites:document_list", args=[site.pk]))

        assert res.status_code == 200
        assert SiteDocument.unscoped.filter(site=site).count() == DEFAULT_COUNT
        assert DocumentTemplate.unscoped.filter(company=site.company).count() == DEFAULT_COUNT
        html = res.content.decode()
        assert "提出済み 0 / 24" in html
        positions = [html.index(label) for label in ("着工時", "施工中", "完成時", "その他")]
        assert positions == sorted(positions)
        assert html.index("施工計画書") < html.index("完成図書")
        start = SiteDocument.unscoped.get(site=site, name="作業員名簿")
        assert start.phase == DocumentPhase.START
        assert start.template.name == "作業員名簿"
        assert not start.is_custom

    def test_2回開いても増えない(self, logged_in, site):
        logged_in.get(reverse("sites:document_list", args=[site.pk]))
        logged_in.get(reverse("sites:document_list", args=[site.pk]))
        logged_in.get(reverse("sites:detail", args=[site.pk]))

        assert SiteDocument.unscoped.filter(site=site).count() == DEFAULT_COUNT
        assert DocumentTemplate.unscoped.filter(company=site.company).count() == DEFAULT_COUNT

    def test_会社のリストを変えても写し済みの現場は変わらず_次の現場に出る(self, company_a, site):
        ensure_site_documents(site)
        DocumentTemplate.unscoped.filter(company=company_a, name="納入仕様書").update(
            is_active=False
        )
        DocumentTemplate.unscoped.create(
            company=company_a, name="道路使用許可書", phase=DocumentPhase.START, display_order=5
        )
        next_site = Site.unscoped.create(company=company_a, code="S002", name="B倉庫改修")

        ensure_site_documents(site)
        ensure_site_documents(next_site)

        assert "納入仕様書" in _names(site)
        assert "道路使用許可書" not in _names(site)
        assert "納入仕様書" not in _names(next_site)
        assert "道路使用許可書" in _names(next_site)

    def test_他社の最初のリストは使わない(self, company_a, company_b, site):
        other_site = Site.unscoped.create(company=company_b, code="S001", name="B社現場")
        ensure_site_documents(other_site)
        DocumentTemplate.unscoped.create(company=company_b, name="B社だけの書類")

        ensure_site_documents(site)

        assert "B社だけの書類" not in _names(site)
        assert SiteDocument.unscoped.filter(site=site).exclude(company=company_a).count() == 0


# ---------------------------------------------------------------------------
# 書類を足す
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAdd:
    def test_その現場だけに足す(self, logged_in, company_a, site):
        res = logged_in.post(
            reverse("sites:document_add", args=[site.pk]),
            {"name": "  道路使用   許可書 ", "phase": DocumentPhase.START},
        )

        document = SiteDocument.unscoped.get(site=site, name="道路使用 許可書")
        assert res.status_code == 302
        assert res["Location"] == reverse("sites:document_detail", args=[document.pk])
        assert document.is_custom
        assert document.template is None
        assert document.phase == DocumentPhase.START
        assert not DocumentTemplate.unscoped.filter(name="道路使用 許可書").exists()
        next_site = Site.unscoped.create(company=company_a, code="S002", name="B倉庫改修")
        ensure_site_documents(next_site)
        assert "道路使用 許可書" not in _names(next_site)

    def test_次の現場からも最初のリストに入れる(self, logged_in, company_a, site):
        logged_in.post(
            reverse("sites:document_add", args=[site.pk]),
            {"name": "近隣挨拶文", "phase": DocumentPhase.START, "add_to_company_list": "on"},
        )

        document = SiteDocument.unscoped.get(site=site, name="近隣挨拶文")
        template = DocumentTemplate.unscoped.get(company=company_a, name="近隣挨拶文")
        assert document.template == template
        assert document.is_custom
        assert template.is_active
        next_site = Site.unscoped.create(company=company_a, code="S002", name="B倉庫改修")
        ensure_site_documents(next_site)
        assert "近隣挨拶文" in _names(next_site)

    def test_同じ名前は足せない(self, logged_in, site):
        ensure_site_documents(site)

        res = logged_in.post(
            reverse("sites:document_add", args=[site.pk]),
            {"name": "施工計画書", "phase": DocumentPhase.OTHER},
        )

        assert res.status_code == 200
        assert "同じ名前の書類があります" in res.content.decode()
        assert SiteDocument.unscoped.filter(site=site).count() == DEFAULT_COUNT

    def test_外した書類と同じ名前で入れると最初のリストに戻る(self, company_a, site):
        ensure_site_documents(site)
        SiteDocument.unscoped.filter(site=site, name="納入仕様書").update(name="納入仕様書（旧）")
        DocumentTemplate.unscoped.filter(company=company_a, name="納入仕様書").update(
            is_active=False
        )

        add_site_document(
            site, name="納入仕様書", phase=DocumentPhase.COMPLETION, add_to_company_list=True
        )

        template = DocumentTemplate.unscoped.get(company=company_a, name="納入仕様書")
        assert template.is_active
        assert template.phase == DocumentPhase.COMPLETION


# ---------------------------------------------------------------------------
# ファイル
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFiles:
    def test_PDFとExcelを何件でも置け_新しいものが上(self, logged_in, site):
        document = _document(site)
        url = reverse("sites:document_detail", args=[document.pk])

        res = logged_in.post(
            url, {"upload": "1", "files": [_pdf(), _xlsx()], "note": "第1版"}
        )
        logged_in.post(url, {"upload": "1", "files": [_xls()], "note": "第2版"})

        assert res.status_code == 302
        document.refresh_from_db()
        files = list(document.files.all())
        assert [f.original_filename for f in files[:1]] == ["工程表.xls"]
        assert sorted(f.kind for f in files) == ["excel", "excel", "pdf"]
        assert {f.note for f in files} == {"第1版", "第2版"}
        assert document.status == SiteDocument.Status.PREPARED
        page = logged_in.get(url).content.decode()
        assert page.index("工程表.xls") < page.index("施工計画書.pdf")
        assert 'accept=".pdf,.xlsx,.xls' in page

    def test_保存するファイル名は推測できない(self, site):
        document = _document(site)

        [item] = save_document_files(document, [(_xlsx(), "excel")])

        assert item.file.name.startswith(f"site_documents/{site.company_id}/{site.pk}/")
        assert "作業員名簿" not in item.file.name
        assert item.file.name.endswith(".xlsx")
        assert item.size > 0

    @pytest.mark.parametrize(
        ("uploaded", "kind"),
        [
            (_pdf(), "pdf"),
            (SimpleUploadedFile("前に余計な行.pdf", b"\xef\xbb\xbf\n%PDF-1.4\n"), "pdf"),
            (_xlsx(), "excel"),
            (_xls(), "excel"),
            (SimpleUploadedFile("パスワード付き.xlsx", OLE_MAGIC + b"\x00" * 512), "excel"),
            (SimpleUploadedFile("大文字.PDF", b"%PDF-1.4\n"), "pdf"),
        ],
    )
    def test_PDFとExcelだと分かる(self, uploaded, kind):
        assert detect_file_kind(uploaded) == kind

    @pytest.mark.parametrize(
        "uploaded",
        [
            _zip("図面.docx", ["[Content_Types].xml", "word/document.xml"]),
            SimpleUploadedFile("写真.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 32),
            SimpleUploadedFile("メモ.csv", b"a,b\n1,2\n"),
            SimpleUploadedFile("偽物.pdf", b"This is not a PDF"),
            _zip("偽物.xlsx", ["[Content_Types].xml", "word/document.xml"]),
            SimpleUploadedFile("偽物.xls", b"%PDF-1.4\n"),
            SimpleUploadedFile("拡張子なし", b"%PDF-1.4\n"),
        ],
    )
    def test_ほかの形式と拡張子だけ変えたファイルは受け付けない(self, uploaded):
        with pytest.raises(UnsupportedDocumentFile):
            detect_file_kind(uploaded)

    def test_受け付けないファイルは1件も登録しない(self, logged_in, site):
        document = _document(site)
        png = SimpleUploadedFile("写真.png", b"\x89PNG\r\n\x1a\n")

        res = logged_in.post(
            reverse("sites:document_detail", args=[document.pk]),
            {"upload": "1", "files": [_pdf(), png]},
        )

        assert res.status_code == 200
        assert "写真.png: PDF（.pdf）か Excel（.xlsx・.xls）" in res.content.decode()
        assert not document.files.exists()

    def test_大きすぎるファイルと多すぎる件数は登録しない(self, logged_in, site, monkeypatch):
        document = _document(site)
        url = reverse("sites:document_detail", args=[document.pk])

        monkeypatch.setattr(documents, "MAX_DOCUMENT_FILE_MB", 0.00001)
        res = logged_in.post(url, {"upload": "1", "files": [_pdf()]})
        assert "MB を超えています" in res.content.decode()

        monkeypatch.setattr(documents, "MAX_DOCUMENT_FILE_MB", 50)
        monkeypatch.setattr(documents, "MAX_DOCUMENT_FILES_PER_UPLOAD", 2)
        three = [_pdf("1.pdf"), _pdf("2.pdf"), _pdf("3.pdf")]
        res = logged_in.post(url, {"upload": "1", "files": three})
        assert "一度に登録できるのは 2 件まで" in res.content.decode()

        assert not document.files.exists()

    def test_PDFは画面で開き_Excelはダウンロードになる(self, logged_in, site):
        document = _document(site)
        pdf, xlsx = save_document_files(document, [(_pdf(), "pdf"), (_xlsx(), "excel")])

        pdf_res = logged_in.get(reverse("sites:document_file", args=[pdf.pk]))
        xlsx_res = logged_in.get(reverse("sites:document_file", args=[xlsx.pk]))

        assert pdf_res.status_code == 200
        assert pdf_res["Content-Type"] == "application/pdf"
        assert pdf_res["Content-Disposition"].startswith("inline")
        assert b"".join(pdf_res.streaming_content).startswith(b"%PDF")
        assert xlsx_res["Content-Type"] == (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert xlsx_res["Content-Disposition"].startswith("attachment")
        assert quote("作業員名簿.xlsx") in xlsx_res["Content-Disposition"]
        assert "private" in xlsx_res["Cache-Control"]

    def test_他社の人とログインしていない人は開けない(self, client, user_b, site):
        document = _document(site)
        [item] = save_document_files(document, [(_pdf(), "pdf")])
        url = reverse("sites:document_file", args=[item.pk])

        client.force_login(user_b)
        assert client.get(url).status_code == 404
        assert client.get(reverse("sites:document_detail", args=[document.pk])).status_code == 404
        client.logout()
        assert client.get(url).status_code == 302


# ---------------------------------------------------------------------------
# 提出の状況
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStatus:
    def _post(self, client, document, **data):
        return client.post(reverse("sites:document_detail", args=[document.pk]), data)

    def test_提出済みで提出日が空なら今日にする(self, logged_in, site):
        document = _document(site)

        res = self._post(logged_in, document, status="submitted", submitted_on="", note="監督員へ")

        assert res.status_code == 302
        document.refresh_from_db()
        assert document.status == SiteDocument.Status.SUBMITTED
        assert document.submitted_on == timezone.localdate()
        assert document.note == "監督員へ"

    def test_提出済みでなければ提出日を持たない(self, logged_in, site):
        document = _document(site)

        self._post(logged_in, document, status="prepared", submitted_on="2026-09-01", note="")

        document.refresh_from_db()
        assert document.status == SiteDocument.Status.PREPARED
        assert document.submitted_on is None

    def test_不要は数に入れない(self, logged_in, site):
        self._post(logged_in, _document(site), status="submitted", submitted_on="2026-09-10")
        self._post(logged_in, _document(site, "納入仕様書"), status="not_required")

        page = logged_in.get(reverse("sites:document_list", args=[site.pk])).content.decode()
        detail = logged_in.get(reverse("sites:detail", args=[site.pk])).content.decode()

        assert "提出済み 1 / 23" in page
        assert "不要 1" in page
        assert "提出済み 1 / 23" in detail
        assert "まだ提出していない書類" in detail
        assert reverse("sites:document_list", args=[site.pk]) in detail

    def test_最初のリストの書類は名前を変えられず_足した書類は変えられる(self, logged_in, site):
        default = _document(site)
        custom = add_site_document(site, name="近隣挨拶文", phase=DocumentPhase.START)

        default_page = logged_in.get(reverse("sites:document_detail", args=[default.pk]))
        assert 'name="name"' not in default_page.content.decode()

        res = self._post(logged_in, custom, name="施工計画書", status="not_started")
        assert "同じ名前の書類があります" in res.content.decode()

        self._post(logged_in, custom, name="近隣への挨拶文", status="not_started")
        custom.refresh_from_db()
        assert custom.name == "近隣への挨拶文"


# ---------------------------------------------------------------------------
# 削除
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDelete:
    def test_ファイルを消すと保存したファイルも消える(
        self, logged_in, site, media_root, django_capture_on_commit_callbacks
    ):
        document = _document(site)
        [item] = save_document_files(document, [(_pdf(), "pdf")])
        path = media_root / item.file.name
        assert path.exists()

        with django_capture_on_commit_callbacks(execute=True):
            res = logged_in.post(reverse("sites:document_file_delete", args=[item.pk]))

        assert res["Location"] == reverse("sites:document_detail", args=[document.pk])
        assert not SiteDocumentFile.unscoped.filter(pk=item.pk).exists()
        assert not path.exists()

    def test_足した書類は消せ_ファイルも消える(
        self, logged_in, site, media_root, django_capture_on_commit_callbacks
    ):
        ensure_site_documents(site)
        custom = add_site_document(site, name="近隣挨拶文", phase=DocumentPhase.START)
        [item] = save_document_files(custom, [(_xlsx(), "excel")])
        path = media_root / item.file.name

        confirm = logged_in.get(reverse("sites:document_delete", args=[custom.pk]))
        assert "ファイル 1 件も消え" in confirm.content.decode()
        with django_capture_on_commit_callbacks(execute=True):
            logged_in.post(reverse("sites:document_delete", args=[custom.pk]))

        assert not SiteDocument.unscoped.filter(pk=custom.pk).exists()
        assert not SiteDocumentFile.unscoped.filter(pk=item.pk).exists()
        assert not path.exists()

    def test_最初のリストの書類は消せない(self, logged_in, site):
        document = _document(site)

        res = logged_in.post(reverse("sites:document_delete", args=[document.pk]))

        assert res["Location"] == reverse("sites:document_detail", args=[document.pk])
        assert SiteDocument.unscoped.filter(pk=document.pk).exists()


# ---------------------------------------------------------------------------
# モデル
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestModel:
    def test_他社の書類とファイルは見えない(self, company_a, company_b, site):
        other_site = Site.unscoped.create(company=company_b, code="S001", name="B社現場")
        save_document_files(_document(site), [(_pdf(), "pdf")])
        save_document_files(_document(other_site), [(_pdf(), "pdf")])

        set_current_company(company_a)
        try:
            assert SiteDocument.objects.count() == DEFAULT_COUNT
            assert set(SiteDocument.objects.values_list("site_id", flat=True)) == {site.pk}
            assert DocumentTemplate.objects.count() == DEFAULT_COUNT
            assert SiteDocumentFile.objects.get().document.site == site
        finally:
            set_current_company(None)

    def test_変更履歴が残り管理画面に出る(self, site):
        document = _document(site)
        [item] = save_document_files(document, [(_pdf(), "pdf")])
        document.refresh_from_db()
        document.status = SiteDocument.Status.SUBMITTED
        document.save()

        assert document.history.count() == 3  # 写したとき・ファイルで作成済み・提出済み
        assert item.history.count() == 1
        assert DocumentTemplate.history.filter(company=site.company).count() == DEFAULT_COUNT
        for model in (DocumentTemplate, SiteDocument, SiteDocumentFile):
            assert isinstance(admin.site._registry[model], SimpleHistoryAdmin)
