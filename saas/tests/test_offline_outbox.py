"""圏外で端末に保存した入力を、あとで送り直す仕組み（ADR-0048）。

固定したいのは次の点:

1. /sw.js は Service Worker として直下から配られ、圏外で開ける入力画面の URL の形と
   「未送信の入力」画面を含む。ログインしていなくても取れる
2. 圏外で開ける画面の一覧（pages.py）と、送り直しを受け付けるビュー
   （offline_resendable）がそろっている
3. 同じ識別番号の送信は1回しか登録しない（ふつうの送信でも、送り直しでも）
4. 送り直しは JSON で結果を返す。入力に誤りがあれば 422 を返し、記録を残さない（直して送り直せる）
5. 写真・書類を含む入力を送り直して登録できる（資格証・健康診断・納品）
6. 記録は会社ごとに分かれ、変更履歴と管理画面がある
"""

import io
import json
import re
import uuid
from datetime import date

import pytest
from django.contrib import admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.urls import resolve, reverse
from PIL import Image

from apps.accounts.models import User
from apps.core.tenant_context import set_current_company
from apps.masters.models import Supplier
from apps.materials.models import Delivery, PurchaseOrder
from apps.offline.models import OfflineSubmission
from apps.offline.pages import OFFLINE_FORM_PATTERNS
from apps.sites.models import Site
from apps.workers.models import HealthCheckup, Worker, WorkerQualification

RESEND = {"HTTP_X_OFFLINE_RESEND": "1"}

# 圏外で開ける画面（URL 名と、URL を組み立てる引数）
OFFLINE_PAGES = (
    ("workers:qual_create", {"worker_pk": 1}),
    ("workers:qual_edit", {"pk": 1}),
    ("workers:health_create", {"worker_pk": 1}),
    ("workers:health_edit", {"pk": 1}),
    ("materials:delivery_create", {"po_pk": 1}),
)


def _png(name="cert.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def worker(company_a):
    return Worker.unscoped.create(
        company=company_a, name="田中太郎", employee_code="E001", hourly_cost=3000,
    )


@pytest.fixture
def logged_in(client, user_a):
    client.force_login(user_a)
    return client


def _qualification(key=None, **extra):
    data = {
        "name": "第二種電気工事士",
        "category": WorkerQualification.Category.LICENSE,
        "note": "",
    }
    if key is not None:
        data["client_request_id"] = str(key)
    data.update(extra)
    return data


def _detail(worker):
    return reverse("workers:detail", kwargs={"pk": worker.pk})


# ---------------------------------------------------------------------------
# Service Worker と画面
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestServiceWorker:
    def test_直下からJavaScriptとして配る(self, client):
        res = client.get("/sw.js")

        assert res.status_code == 200
        assert res["Content-Type"].startswith("application/javascript")
        assert res["Service-Worker-Allowed"] == "/"
        body = res.content.decode()
        assert 'var OUTBOX_URL = "/offline/";' in body
        assert "importScripts(" in body and "offline-db" in body
        for pattern in OFFLINE_FORM_PATTERNS:
            assert json.dumps(pattern)[1:-1] in body
        # JavaScript として配るので、HTML の文字の置き換えをしない
        assert "&quot;" not in body and "&#x27;" not in body

    def test_未送信の入力の画面はログインが要る(self, client, user_a):
        assert client.get("/offline/").status_code == 302

        client.force_login(user_a)
        html = client.get("/offline/").content.decode()
        assert "未送信の入力" in html
        assert 'id="offline-list"' in html

    def test_入力画面に圏外保存の部品が付く(self, logged_in, worker):
        url = reverse("workers:qual_create", kwargs={"worker_pk": worker.pk})
        html = logged_in.get(url).content.decode()

        assert "data-offline-form" in html
        assert "資格の登録（田中太郎）" in html
        assert "js/offline-db" in html and "js/offline." in html
        assert 'data-sw-url="/sw.js"' in html
        assert 'id="offline-outbox-badge"' in html
        assert "data-offline-logout" in html


class TestOfflinePages:
    def test_一覧の画面はすべて送り直しを受け付ける(self):
        for name, kwargs in OFFLINE_PAGES:
            path = reverse(name, kwargs=kwargs)
            assert any(re.match(p, path) for p in OFFLINE_FORM_PATTERNS), path
            assert getattr(resolve(path).func, "offline_resendable", False), path

    def test_一覧の形はどれも対象の画面に当たる(self):
        paths = [reverse(name, kwargs=kwargs) for name, kwargs in OFFLINE_PAGES]
        for pattern in OFFLINE_FORM_PATTERNS:
            assert any(re.match(pattern, path) for path in paths), pattern


# ---------------------------------------------------------------------------
# 二重登録を防ぐ
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDeduplication:
    def _url(self, worker):
        return reverse("workers:qual_create", kwargs={"worker_pk": worker.pk})

    def test_識別番号付きの送信は登録して記録する(self, logged_in, worker, media):
        key = uuid.uuid4()

        res = logged_in.post(self._url(worker), _qualification(key))

        assert res.status_code == 302
        assert res["Location"] == _detail(worker)
        assert WorkerQualification.unscoped.count() == 1
        submission = OfflineSubmission.unscoped.get()
        assert submission.client_request_id == key
        assert (submission.path, submission.location) == (self._url(worker), _detail(worker))

    def test_同じ識別番号の2回目は登録しない(self, logged_in, worker, media):
        key = uuid.uuid4()

        logged_in.post(self._url(worker), _qualification(key))
        again = logged_in.post(self._url(worker), _qualification(key))

        assert again.status_code == 302
        assert again["Location"] == _detail(worker)
        assert WorkerQualification.unscoped.count() == 1
        assert OfflineSubmission.unscoped.count() == 1

    def test_送り直しはJSONで結果を返す(self, logged_in, worker, media):
        key = uuid.uuid4()

        first = logged_in.post(self._url(worker), _qualification(key), **RESEND)
        again = logged_in.post(self._url(worker), _qualification(key), **RESEND)

        assert first.json() == {"ok": True, "location": _detail(worker)}
        assert again.json() == {"ok": True, "duplicate": True, "location": _detail(worker)}
        assert WorkerQualification.unscoped.count() == 1

    def test_入力に誤りがあれば422を返して記録を残さず_直せば送れる(
        self, logged_in, worker, media,
    ):
        key = uuid.uuid4()

        res = logged_in.post(self._url(worker), _qualification(key, name=""), **RESEND)

        assert res.status_code == 422
        assert res.json()["ok"] is False
        assert "入力に誤り" in res.json()["message"]
        assert not OfflineSubmission.unscoped.exists()
        assert not WorkerQualification.unscoped.exists()

        fixed = logged_in.post(self._url(worker), _qualification(key), **RESEND)
        assert fixed.json()["ok"] is True
        assert WorkerQualification.unscoped.count() == 1

    def test_ふつうの送信で入力に誤りがあれば画面を返す(self, logged_in, worker, media):
        res = logged_in.post(self._url(worker), _qualification(uuid.uuid4(), name=""))

        assert res.status_code == 200
        assert "errorlist" in res.content.decode()
        assert not OfflineSubmission.unscoped.exists()

    def test_識別番号が無い送信や読めない送信は今までどおり登録する(
        self, logged_in, worker, media,
    ):
        logged_in.post(self._url(worker), _qualification())
        logged_in.post(self._url(worker), _qualification(client_request_id="読めない"))

        assert WorkerQualification.unscoped.count() == 2
        assert not OfflineSubmission.unscoped.exists()

    def test_同じ識別番号でも別の人の送信は別に扱う(self, client, company_a, worker, media):
        key = uuid.uuid4()
        for username in ("user_1", "user_2"):
            user = User.objects.create_user(
                username=username, password="pass-12345", company=company_a,
            )
            client.force_login(user)
            client.post(self._url(worker), _qualification(key), **RESEND)

        assert WorkerQualification.unscoped.count() == 2
        assert OfflineSubmission.unscoped.count() == 2

    def test_編集の送り直しも二重にならない(self, logged_in, company_a, worker, media):
        qualification = WorkerQualification.unscoped.create(
            company=company_a, worker=worker, name="古い名前",
        )
        url = reverse("workers:qual_edit", kwargs={"pk": qualification.pk})
        key = uuid.uuid4()

        for _ in range(2):
            logged_in.post(url, _qualification(key, name="新しい名前"), **RESEND)

        qualification.refresh_from_db()
        assert qualification.name == "新しい名前"
        assert OfflineSubmission.unscoped.count() == 1


# ---------------------------------------------------------------------------
# 写真・書類を含む入力
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestResendWithFiles:
    def test_資格証の画像を送り直して登録できる(self, logged_in, worker, media):
        url = reverse("workers:qual_create", kwargs={"worker_pk": worker.pk})
        data = _qualification(uuid.uuid4(), certificate_image=_png())

        res = logged_in.post(url, data, **RESEND)

        assert res.json()["ok"] is True
        assert WorkerQualification.unscoped.get().certificate_image.name.endswith(".png")

    def test_健康診断の書類を送り直して登録できる(self, logged_in, worker, media):
        url = reverse("workers:health_create", kwargs={"worker_pk": worker.pk})
        data = {
            "checkup_date": "2026-09-01",
            "result": HealthCheckup.Result.NORMAL,
            "institution": "",
            "memo": "",
            "report_file": SimpleUploadedFile(
                "result.pdf", b"%PDF-1.4 test", content_type="application/pdf",
            ),
            "client_request_id": str(uuid.uuid4()),
        }

        res = logged_in.post(url, data, **RESEND)

        assert res.json() == {"ok": True, "location": _detail(worker)}
        assert HealthCheckup.unscoped.get().report_file.name.endswith(".pdf")

    def test_納品を送り直して記録できる(self, logged_in, company_a, media):
        site = Site.unscoped.create(company=company_a, code="S01", name="A社ビル新築")
        supplier = Supplier.unscoped.create(company=company_a, code="SP1", name="東電材")
        po = PurchaseOrder.unscoped.create(
            company=company_a, site=site, supplier=supplier, order_date=date(2026, 9, 1),
        )
        url = reverse("materials:delivery_create", kwargs={"po_pk": po.pk})
        data = {"delivery_date": "2026-09-12", "notes": "", "client_request_id": str(uuid.uuid4())}

        res = logged_in.post(url, data, **RESEND)
        again = logged_in.post(url, data, **RESEND)

        delivery = Delivery.unscoped.get()
        location = reverse("materials:delivery_detail", kwargs={"pk": delivery.pk})
        assert res.json() == {"ok": True, "location": location}
        assert again.json()["duplicate"] is True


# ---------------------------------------------------------------------------
# 記録のモデル
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestOfflineSubmissionModel:
    def _create(self, company, user, key=None):
        return OfflineSubmission.unscoped.create(
            company=company, user=user, client_request_id=key or uuid.uuid4(), path="/x/",
        )

    def test_他社の記録は見えない(self, company_a, company_b, user_a, user_b):
        mine = self._create(company_a, user_a)
        self._create(company_b, user_b)

        set_current_company(company_a)
        try:
            assert list(OfflineSubmission.objects.all()) == [mine]
        finally:
            set_current_company(None)

    def test_同じ会社と人と識別番号は1件だけ(self, company_a, user_a):
        key = uuid.uuid4()
        self._create(company_a, user_a, key)

        with pytest.raises(IntegrityError), transaction.atomic():
            self._create(company_a, user_a, key)

    def test_変更履歴が残り管理画面に出る(self, company_a, user_a):
        self._create(company_a, user_a)

        assert OfflineSubmission.history.count() == 1
        assert admin.site.is_registered(OfflineSubmission)
