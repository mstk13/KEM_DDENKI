"""圏外保存の画面と Service Worker（ADR-0048）。"""

import hashlib

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse

from apps.core.json_utils import json_for_script
from apps.offline.pages import OFFLINE_FORM_PATTERNS

# 端末に控える静的ファイル。名前に中身のハッシュが付くので、変われば Service Worker の版も変わる。
PRECACHE_STATIC = ("css/style.css", "js/app.js", "js/offline-db.js", "js/offline.js")


def service_worker(request):
    """Service Worker の本体を返す（/sw.js）。

    Service Worker は置いた場所より上の階層の画面を扱えないので、/static/ ではなく
    サイトの直下から配る。ログインが切れていても更新の確認が届くよう、ログインは求めない
    （中身は画面の URL の形と静的ファイルの名前だけで、個人の情報は含まない）。
    """
    static_urls = [static(path) for path in PRECACHE_STATIC]
    version = hashlib.sha256("|".join(static_urls).encode()).hexdigest()[:12]
    body = render_to_string("offline/sw.js", {
        "version": version,
        "outbox_url": reverse("offline:outbox"),
        "offline_db_url": static("js/offline-db.js"),
        "static_urls_json": json_for_script(static_urls),
        "page_patterns_json": json_for_script(list(OFFLINE_FORM_PATTERNS)),
    })
    response = HttpResponse(body, content_type="application/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


@login_required
def outbox(request):
    """この端末に保存した、未送信の入力の一覧。

    入力の中身は端末の中（IndexedDB）にだけあるので、一覧は画面の JavaScript が描く。
    """
    return render(request, "offline/outbox.html")
