"""現場写真（ADR-0050）。

ここで固定すること:
1. 写真をまとめて、種類（どのような写真か）と撮影場所（どこの写真か）つきで登録できる
2. 撮影日は「入力 → 写真に記録された撮影日（EXIF）→ 今日」の順に決める
3. 元の写真は加工せず残し、一覧用の縮小画像は写真の向きを直して作る
4. 写真のファイルは、同じ会社のログインした人だけが見られる
5. 圏外から送り直しても二重に登録しない（ADR-0048）
6. 削除すると写真のファイルも消える（現場ごと消したときも）
7. 現場詳細: 内訳書・内訳明細書と見積内訳の欄を外して現場写真の欄を置き、
   材料の受発注を見積もり/実経費のすぐ下に置く
"""

import io
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from django.contrib import admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import ExifTags, Image

from apps.core.tenant_context import set_current_company
from apps.materials.models import Quotation, QuotationItem
from apps.sites.forms import MAX_PHOTOS_PER_UPLOAD
from apps.sites.models import Site, SitePhoto
from apps.sites.photos import read_taken_on
from apps.sites.services import collect_site_deletion_impact
from apps.sites.views import DETAIL_PHOTO_COUNT

RESEND = {"HTTP_X_OFFLINE_RESEND": "1"}


def _jpeg(name="IMG_0001.jpg", *, size=(60, 40), taken=None, modified=None, orientation=None):
    """テスト用の JPEG。taken / modified は EXIF の日時（"2026:08:30 09:00:00" の形）。"""
    exif = Image.Exif()
    if taken:
        exif[ExifTags.IFD.Exif] = {ExifTags.Base.DateTimeOriginal: taken}
    if modified:
        exif[ExifTags.Base.DateTime] = modified
    if orientation:
        exif[ExifTags.Base.Orientation] = orientation
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="JPEG", exif=exif)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def site_a(company_a):
    return Site.unscoped.create(
        company=company_a, code="S001", name="A社ビル新築", contract_amount=0,
    )


@pytest.fixture
def logged_in(client, user_a):
    client.force_login(user_a)
    return client


@pytest.fixture
def cost_client(client, company_a, django_user_model):
    """原価を見られる人（社員番号 G 始まり）。"""
    user = django_user_model.objects.create_user(
        username="g_user", password="testpass123", company=company_a, employee_no="G001",
    )
    set_current_company(company_a)
    client.force_login(user)
    yield client
    set_current_company(None)


def _photo(site, **extra):
    """画面を通さずに写真を作る（縮小画像なし）。"""
    data = {"kind": SitePhoto.Kind.DURING, "location": "1F 廊下", "taken_on": date(2026, 9, 1)}
    data.update(extra)
    photo = SitePhoto(company=site.company, site=site, **data)
    photo.image.save("p.jpg", _jpeg(), save=False)
    photo.save()
    return photo


def _upload(client, site, files, *, headers=None, **fields):
    data = {
        "images": files,
        "kind": SitePhoto.Kind.SURVEY,
        "location": "2F 東側 分電盤",
        "taken_on": "",
        "note": "",
    }
    data.update(fields)
    return client.post(
        reverse("sites:photo_upload", args=[site.pk]), data, **(headers or {}),
    )


def _detail(site):
    return reverse("sites:detail", args=[site.pk])


# ---------------------------------------------------------------------------
# 登録
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestUpload:
    def test_まとめて選んだ写真を種類と撮影場所つきで登録する(
        self, logged_in, site_a, user_a, media,
    ):
        res = _upload(
            logged_in, site_a, [_jpeg("IMG_0001.jpg"), _jpeg("IMG_0002.jpg")], note="配線前",
        )

        assert res.status_code == 302
        assert res["Location"] == reverse("sites:photo_list", args=[site_a.pk])
        photos = list(SitePhoto.unscoped.all())
        assert {p.original_filename for p in photos} == {"IMG_0001.jpg", "IMG_0002.jpg"}
        for photo in photos:
            assert photo.site == site_a
            assert photo.company == site_a.company
            assert photo.created_by == user_a
            assert photo.kind == SitePhoto.Kind.SURVEY
            assert photo.location == "2F 東側 分電盤"
            assert photo.note == "配線前"

    def test_保存先は会社と現場ごとで_元のファイル名を使わない(self, logged_in, site_a, media):
        _upload(logged_in, site_a, [_jpeg("IMG_0001.jpg")])

        photo = SitePhoto.unscoped.get()
        prefix = f"site_photos/{site_a.company_id}/{site_a.pk}/"
        assert photo.image.name.startswith(prefix)
        assert "IMG_0001" not in photo.image.name
        assert photo.thumbnail.name.startswith(prefix + "thumbs/")

    def test_撮影日は入力があればそれを使う(self, logged_in, site_a, media):
        _upload(
            logged_in, site_a, [_jpeg(taken="2026:08:30 09:00:00")], taken_on="2026-09-05",
        )

        assert SitePhoto.unscoped.get().taken_on == date(2026, 9, 5)

    def test_撮影日が空なら写真に記録された撮影日を使う(self, logged_in, site_a, media):
        _upload(logged_in, site_a, [_jpeg(taken="2026:08:30 09:00:00")])

        assert SitePhoto.unscoped.get().taken_on == date(2026, 8, 30)

    def test_撮影日の記録も無ければ今日にする(self, logged_in, site_a, media):
        _upload(logged_in, site_a, [_jpeg()])

        assert SitePhoto.unscoped.get().taken_on == timezone.localdate()

    def test_未来の撮影日の記録は使わない(self, logged_in, site_a, media):
        future = timezone.localdate() + timedelta(days=30)
        _upload(logged_in, site_a, [_jpeg(taken=future.strftime("%Y:%m:%d 10:00:00"))])

        assert SitePhoto.unscoped.get().taken_on == timezone.localdate()

    def test_元の写真は加工せず_縮小画像は向きを直して作る(self, logged_in, site_a, media):
        # 向き 6 = 端末を縦にして撮った（表示するときに右へ90度回す）
        upload = _jpeg(size=(60, 40), orientation=6)
        original_bytes = upload.read()
        upload.seek(0)

        _upload(logged_in, site_a, [upload])

        photo = SitePhoto.unscoped.get()
        assert Path(photo.image.path).read_bytes() == original_bytes
        with Image.open(photo.thumbnail.path) as thumb:
            assert thumb.size == (40, 60)

    def test_縮小画像は一覧用の大きさに収める(self, logged_in, site_a, media):
        _upload(logged_in, site_a, [_jpeg(size=(1600, 1200))])

        with Image.open(SitePhoto.unscoped.get().thumbnail.path) as thumb:
            assert thumb.size == (480, 360)

    def test_撮影場所が無いと登録しない(self, logged_in, site_a, media):
        res = _upload(logged_in, site_a, [_jpeg()], location="")

        assert res.status_code == 200
        assert "location" in res.context["form"].errors
        assert not SitePhoto.unscoped.exists()

    def test_写真を選ばないと登録しない(self, logged_in, site_a, media):
        res = _upload(logged_in, site_a, [])

        assert res.status_code == 200
        assert "images" in res.context["form"].errors

    def test_写真でないファイルは登録しない(self, logged_in, site_a, media):
        text = SimpleUploadedFile("memo.txt", b"not an image", content_type="text/plain")

        res = _upload(logged_in, site_a, [_jpeg(), text])

        assert "images" in res.context["form"].errors
        assert not SitePhoto.unscoped.exists()

    def test_一度に登録できる枚数を超えると登録しない(self, logged_in, site_a, media):
        files = [
            _jpeg(f"IMG_{i:04d}.jpg", size=(4, 4)) for i in range(MAX_PHOTOS_PER_UPLOAD + 1)
        ]

        res = _upload(logged_in, site_a, files)

        assert "images" in res.context["form"].errors
        assert not SitePhoto.unscoped.exists()

    def test_圏外から送り直しても二重に登録しない(self, logged_in, site_a, media):
        key = str(uuid.uuid4())

        first = _upload(logged_in, site_a, [_jpeg()], client_request_id=key, headers=RESEND)
        again = _upload(logged_in, site_a, [_jpeg()], client_request_id=key, headers=RESEND)

        location = reverse("sites:photo_list", args=[site_a.pk])
        assert first.json() == {"ok": True, "location": location}
        assert again.json()["duplicate"] is True
        assert SitePhoto.unscoped.count() == 1

    def test_登録画面は圏外保存の部品が付き_種類を選んで開ける(self, logged_in, site_a):
        res = logged_in.get(reverse("sites:photo_upload", args=[site_a.pk]), {"kind": "after"})
        html = res.content.decode()

        assert "data-offline-form" in html
        assert "multiple" in html
        assert res.context["form"].initial["kind"] == "after"

    def test_撮影場所の候補はこの現場で使った場所をよく使う順に出す(
        self, logged_in, site_a, company_a, media,
    ):
        other = Site.unscoped.create(
            company=company_a, code="S002", name="別の現場", contract_amount=0,
        )
        _photo(site_a, location="外観 北面")
        _photo(site_a, location="2F 東側 分電盤")
        _photo(site_a, location="2F 東側 分電盤")
        _photo(other, location="別の現場の場所")

        res = logged_in.get(reverse("sites:photo_upload", args=[site_a.pk]))

        assert res.context["form"].location_choices == ["2F 東側 分電盤", "外観 北面"]


@pytest.mark.django_db
class TestReadTakenOn:
    TODAY = date(2026, 9, 12)

    def test_撮影日時が無ければ更新日時を使う(self):
        upload = _jpeg(modified="2026:07:01 08:00:00")

        assert read_taken_on(upload, today=self.TODAY) == date(2026, 7, 1)

    def test_古すぎる日付は使わない(self):
        upload = _jpeg(taken="1970:01:01 00:00:00")

        assert read_taken_on(upload, today=self.TODAY) is None

    def test_画像でなければ読まない(self):
        upload = SimpleUploadedFile("memo.txt", b"not an image")

        assert read_taken_on(upload, today=self.TODAY) is None


# ---------------------------------------------------------------------------
# 写真のファイル
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPhotoFile:
    def test_ログインしていないと見られない(self, client, site_a, media):
        photo = _photo(site_a)

        res = client.get(reverse("sites:photo_image", args=[photo.pk]))

        assert res.status_code == 302

    def test_同じ会社の人は写真と縮小画像を見られる(self, logged_in, site_a, media):
        _upload(logged_in, site_a, [_jpeg()])
        photo = SitePhoto.unscoped.get()

        image = logged_in.get(reverse("sites:photo_image", args=[photo.pk]))
        thumb = logged_in.get(reverse("sites:photo_thumb", args=[photo.pk]))

        assert image.status_code == 200
        assert image["Content-Type"] == "image/jpeg"
        assert "private" in image["Cache-Control"]
        assert b"".join(image.streaming_content) == Path(photo.image.path).read_bytes()
        assert b"".join(thumb.streaming_content) == Path(photo.thumbnail.path).read_bytes()

    def test_縮小画像が無ければ元の写真を返す(self, logged_in, site_a, media):
        photo = _photo(site_a)

        res = logged_in.get(reverse("sites:photo_thumb", args=[photo.pk]))

        assert b"".join(res.streaming_content) == Path(photo.image.path).read_bytes()

    def test_ファイルが無くなっていれば404(self, logged_in, site_a, media):
        photo = _photo(site_a)
        Path(photo.image.path).unlink()

        assert logged_in.get(reverse("sites:photo_image", args=[photo.pk])).status_code == 404

    def test_他社の写真と現場には届かない(self, client, user_b, site_a, media):
        photo = _photo(site_a)
        client.force_login(user_b)

        for name in (
            "sites:photo_image", "sites:photo_thumb", "sites:photo_edit", "sites:photo_delete",
        ):
            assert client.get(reverse(name, args=[photo.pk])).status_code == 404, name
        for name in ("sites:photo_list", "sites:photo_upload"):
            assert client.get(reverse(name, args=[site_a.pk])).status_code == 404, name
        assert _upload(client, site_a, [_jpeg()]).status_code == 404
        assert SitePhoto.unscoped.count() == 1


# ---------------------------------------------------------------------------
# 一覧・編集・削除
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestListEditDelete:
    def test_種類と撮影場所で絞り込む(self, logged_in, site_a, media):
        survey = _photo(site_a, kind=SitePhoto.Kind.SURVEY, location="屋上 キュービクル")
        during = _photo(site_a, kind=SitePhoto.Kind.DURING, location="2F 東側 分電盤")
        url = reverse("sites:photo_list", args=[site_a.pk])

        by_kind = logged_in.get(url, {"kind": "survey"}).context["page"].object_list
        by_word = logged_in.get(url, {"q": "分電盤"}).context["page"].object_list
        counts = {row["value"]: row["count"] for row in logged_in.get(url).context["kind_counts"]}

        assert list(by_kind) == [survey]
        assert list(by_word) == [during]
        assert (counts["survey"], counts["during"], counts["after"]) == (1, 1, 0)

    def test_知らない種類を指定されたら全部出す(self, logged_in, site_a, media):
        _photo(site_a)
        res = logged_in.get(reverse("sites:photo_list", args=[site_a.pk]), {"kind": "xxx"})

        assert res.context["kind"] == ""
        assert len(res.context["page"].object_list) == 1

    def test_写真の情報を直せる(self, logged_in, site_a, media):
        photo = _photo(site_a)

        res = logged_in.post(
            reverse("sites:photo_edit", args=[photo.pk]),
            {"kind": "after", "location": "1F 玄関", "taken_on": "2026-09-10", "note": "完了"},
        )

        assert res.status_code == 302
        photo.refresh_from_db()
        assert (photo.kind, photo.location, photo.taken_on, photo.note) == (
            "after", "1F 玄関", date(2026, 9, 10), "完了",
        )

    def test_削除の確認画面ではまだ消さない(self, logged_in, site_a, media):
        photo = _photo(site_a)

        res = logged_in.get(reverse("sites:photo_delete", args=[photo.pk]))

        assert res.status_code == 200
        assert SitePhoto.unscoped.filter(pk=photo.pk).exists()

    def test_削除すると写真のファイルも消える(
        self, logged_in, site_a, media, django_capture_on_commit_callbacks,
    ):
        _upload(logged_in, site_a, [_jpeg()])
        photo = SitePhoto.unscoped.get()
        paths = [Path(photo.image.path), Path(photo.thumbnail.path)]

        with django_capture_on_commit_callbacks(execute=True):
            res = logged_in.post(reverse("sites:photo_delete", args=[photo.pk]))

        assert res.status_code == 302
        assert not SitePhoto.unscoped.exists()
        assert not any(path.exists() for path in paths)

    def test_現場ごと消すと写真とファイルも消える(
        self, site_a, media, django_capture_on_commit_callbacks,
    ):
        photo = _photo(site_a)
        path = Path(photo.image.path)

        assert {"label": "現場写真", "count": 1} in collect_site_deletion_impact(site_a)
        with django_capture_on_commit_callbacks(execute=True):
            site_a.delete()

        assert not SitePhoto.unscoped.exists()
        assert not path.exists()


# ---------------------------------------------------------------------------
# 現場詳細
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSiteDetail:
    def test_現場写真の欄と登録の入口がある(self, logged_in, site_a):
        body = logged_in.get(_detail(site_a)).content.decode()

        assert "<h2>現場写真</h2>" in body
        assert reverse("sites:photo_upload", args=[site_a.pk]) in body

    def test_新しい写真を数枚だけ出し_残りは一覧で見る(self, logged_in, site_a, media):
        for day in range(1, 11):
            _photo(site_a, taken_on=date(2026, 9, day))

        res = logged_in.get(_detail(site_a))

        assert len(res.context["recent_photos"]) == DETAIL_PHOTO_COUNT
        assert res.context["recent_photos"][0].taken_on == date(2026, 9, 10)
        assert res.context["photo_total"] == 10
        assert "すべて見る（10枚）" in res.content.decode()

    def test_内訳書と見積内訳の欄は出さない(self, logged_in, site_a, company_a):
        quotation = Quotation.unscoped.create(
            company=company_a,
            kind=Quotation.Kind.ISSUED,
            site=site_a,
            quotation_number="Q-1",
            quotation_date=date(2026, 8, 12),
            total_amount=240000,
        )
        QuotationItem.unscoped.create(
            company=company_a, quotation=quotation, material_name="電線管",
            spec="E19 溶融亜鉛メッキ", amount=240000, sort_order=0,
        )

        body = logged_in.get(_detail(site_a)).content.decode()

        assert "内訳書・内訳明細書" not in body
        assert "見積内訳" not in body
        assert "E19 溶融亜鉛メッキ" not in body
        # 見積そのものは、材料の受発注の行から開ける
        assert reverse("materials:quotation_detail", args=[quotation.pk]) in body

    def test_材料の受発注は見積もり実経費のすぐ下(self, cost_client, site_a):
        body = cost_client.get(_detail(site_a)).content.decode()

        positions = [
            body.index(f"<h2>{title}</h2>")
            for title in ("見積もり/実経費", "材料の受発注", "工程", "現場写真")
        ]
        assert positions == sorted(positions)

    def test_原価を見られない人にも材料の受発注と写真の欄は出る(self, logged_in, site_a):
        body = logged_in.get(_detail(site_a)).content.decode()

        assert "<h2>見積もり/実経費</h2>" not in body
        assert "<h2>材料の受発注</h2>" in body
        assert "<h2>現場写真</h2>" in body


# ---------------------------------------------------------------------------
# モデル
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSitePhotoModel:
    def test_他社の写真は見えない(self, company_a, company_b, site_a, media):
        mine = _photo(site_a)
        other_site = Site.unscoped.create(
            company=company_b, code="S001", name="B社現場", contract_amount=0,
        )
        _photo(other_site)

        set_current_company(company_a)
        try:
            assert list(SitePhoto.objects.all()) == [mine]
        finally:
            set_current_company(None)

    def test_変更履歴が残り管理画面に出る(self, site_a, media):
        _photo(site_a)

        assert SitePhoto.history.count() == 1
        assert admin.site.is_registered(SitePhoto)
