"""アップロードしたファイル（MEDIA_ROOT 配下）を、ログインした人にだけ返す（ADR-0093）。

これまで `/media/` は `DEBUG=True` のときだけ配信していた。本番は DEBUG=False なので、
資格証の「表示」を押すと Django の 404（Not Found）になっていた
（プロダクトオーナーの申告、2026-09-18）。

置き場所を公開ディレクトリにしないのは、ここに入るのが資格証・運転免許証・健診報告書など
**個人の書類**だからである。誰でも開ける URL にはせず、ログインを通った人にだけ返す。

画像・PDF は画面に直接出したいので、添付（ダウンロード）ではなく inline で返す。
"""

import mimetypes
import posixpath
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404


def _safe_path(path: str) -> Path | None:
    """MEDIA_ROOT の中に収まる実ファイルの場所。外へ出る指定は None。"""
    # posixpath.normpath で "a/../../etc" のような指定を畳んでから確かめる
    relative = posixpath.normpath(path.replace("\\", "/")).lstrip("/")
    if relative.startswith("../") or relative == "..":
        return None

    root = Path(settings.MEDIA_ROOT).resolve()
    target = (root / relative).resolve()
    if root not in target.parents and target != root:
        return None
    return target


@login_required
def serve_media(request, path):
    """アップロードしたファイルを返す。ログインしていない人はログイン画面へ。"""
    target = _safe_path(path)
    if target is None or not target.is_file():
        raise Http404("ファイルが見つかりません。")

    content_type, _encoding = mimetypes.guess_type(target.name)
    response = FileResponse(
        target.open("rb"), content_type=content_type or "application/octet-stream",
    )
    # 画面の中で開きたいので inline。ファイル名は日本語が入るので指定しない
    response["Content-Disposition"] = "inline"
    # 個人の書類なので、共有のキャッシュには載せない
    response["Cache-Control"] = "private, max-age=0"
    return response
