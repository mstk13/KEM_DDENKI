"""現場写真の登録・画像の扱い（ADR-0051）。

- 元の写真は加工せずに保存する（向きの補正も縮小もしない）
- 一覧用に縮小画像を別に作る。スマホは写真の向きを EXIF に書くだけのことが多いので、
  縮小画像ではその向きに回してから縮める
- 撮影日は、入力があればそれ、無ければ写真の EXIF、それも読めなければ今日にする。
  圏外で撮って後から送る（ADR-0048）と、登録日と撮影日がずれるため
"""

import io
from datetime import date, datetime

from django.core.files.base import ContentFile
from PIL import ExifTags, Image, ImageOps

from apps.sites.models import SitePhoto

THUMBNAIL_BOX = (480, 480)

# 撮影日として信じる範囲。時計の狂った端末の 1970 年や未来の日付は使わない
EARLIEST_TAKEN_ON = date(2000, 1, 1)

# 画像として読めなかったとき Pillow が投げるもの
_IMAGE_ERRORS = (OSError, ValueError, SyntaxError, Image.DecompressionBombError)


def _rewind(uploaded):
    if hasattr(uploaded, "seek"):
        uploaded.seek(0)


def read_taken_on(uploaded, *, today: date) -> date | None:
    """写真の EXIF から撮影日を読む。読めない・ありえない日付なら None。"""
    _rewind(uploaded)
    try:
        with Image.open(uploaded) as img:
            exif = img.getexif()
            raw = (
                exif.get_ifd(ExifTags.IFD.Exif).get(ExifTags.Base.DateTimeOriginal)
                or exif.get(ExifTags.Base.DateTime)
            )
    except _IMAGE_ERRORS:
        return None
    finally:
        _rewind(uploaded)

    if not raw:
        return None
    try:
        # EXIF の日時は "2026:09:12 10:30:00" の形
        taken = datetime.strptime(str(raw).strip()[:10], "%Y:%m:%d").date()
    except ValueError:
        return None
    if not EARLIEST_TAKEN_ON <= taken <= today:
        return None
    return taken


def make_thumbnail(uploaded) -> ContentFile | None:
    """一覧用の縮小画像（JPEG）を作る。作れなければ None（元の写真を出す）。"""
    _rewind(uploaded)
    try:
        with Image.open(uploaded) as img:
            thumb = ImageOps.exif_transpose(img)
            thumb.thumbnail(THUMBNAIL_BOX)
            if thumb.mode != "RGB":
                thumb = thumb.convert("RGB")
            buffer = io.BytesIO()
            thumb.save(buffer, format="JPEG", quality=80, optimize=True)
    except _IMAGE_ERRORS:
        return None
    finally:
        _rewind(uploaded)
    return ContentFile(buffer.getvalue(), name="thumbnail.jpg")


def save_site_photos(
    *, site, user, files, kind, location, taken_on, note, today: date,
) -> list[SitePhoto]:
    """まとめて選んだ写真を、同じ種類・撮影場所・メモで1枚ずつ登録する。"""
    photos = []
    for uploaded in files:
        photo = SitePhoto(
            company=site.company,
            site=site,
            created_by=user,
            kind=kind,
            location=location,
            note=note,
            taken_on=taken_on or read_taken_on(uploaded, today=today) or today,
            original_filename=uploaded.name[:255],
        )
        thumbnail = make_thumbnail(uploaded)
        photo.image.save(uploaded.name, uploaded, save=False)
        if thumbnail is not None:
            photo.thumbnail.save(thumbnail.name, thumbnail, save=False)
        photo.save()
        photos.append(photo)
    return photos
