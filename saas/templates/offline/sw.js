{% autoescape off %}/* 圏外保存の Service Worker（ADR-0048）。apps/offline/views.py の service_worker が /sw.js として配る。
 *
 * - 入力画面（apps/offline/pages.py）は、電波のあるときに開いたら端末に控え、圏外ではその控えを出す
 * - その画面からの送信が通信エラーになったら、入力を端末（IndexedDB）に保存し「未送信の入力」へ移る
 * - 静的ファイルは名前に中身のハッシュが付くので、端末の控えを先に使う
 * - 送り直し（ヘッダ X-Offline-Resend）は横取りしない。結果を画面の JavaScript が読むため
 */
importScripts("{{ offline_db_url }}");

var VERSION = "{{ version }}";
var STATIC_CACHE = "kec-static-" + VERSION;
var PAGE_CACHE = "kec-pages";
var OUTBOX_URL = "{{ outbox_url }}";
var STATIC_URLS = {{ static_urls_json }};
var FORM_PATTERNS = {{ page_patterns_json }}.map(function (pattern) {
  return new RegExp(pattern);
});

function isFormPage(pathname) {
  return FORM_PATTERNS.some(function (re) { return re.test(pathname); });
}

function isOfflinePage(pathname) {
  return pathname === OUTBOX_URL || isFormPage(pathname);
}

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(function (cache) { return cache.addAll(STATIC_URLS); })
      .catch(function () {})
      .then(function () {
        return caches.open(PAGE_CACHE).then(function (cache) {
          return fetch(OUTBOX_URL, { credentials: "same-origin" }).then(function (res) {
            if (res.ok && !res.redirected) { return cache.put(OUTBOX_URL, res); }
          });
        });
      })
      .catch(function () {})
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys()
      .then(function (keys) {
        return Promise.all(keys.filter(function (key) {
          return key.indexOf("kec-static-") === 0 && key !== STATIC_CACHE;
        }).map(function (key) { return caches.delete(key); }));
      })
      .then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (event) {
  var request = event.request;
  var url = new URL(request.url);
  if (url.origin !== self.location.origin) { return; }

  if (request.method === "POST") {
    if (isFormPage(url.pathname) && request.headers.get("X-Offline-Resend") !== "1") {
      event.respondWith(postOrSave(request));
    }
    return;
  }
  if (request.method !== "GET") { return; }

  if (url.pathname.indexOf("/static/") === 0) {
    event.respondWith(cacheFirst(request));
    return;
  }
  if (request.mode === "navigate" && isOfflinePage(url.pathname)) {
    event.respondWith(networkFirst(request, url));
  }
});

function cacheFirst(request) {
  return caches.match(request).then(function (cached) {
    if (cached) { return cached; }
    return fetch(request).then(function (res) {
      if (res.ok) {
        var copy = res.clone();
        caches.open(STATIC_CACHE).then(function (cache) { cache.put(request, copy); });
      }
      return res;
    });
  });
}

// 画面は電波があれば最新を出して控えを更新し、圏外なら控えを出す。
// ログインが切れていてログイン画面へ飛ばされた応答は控えない。
function networkFirst(request, url) {
  return fetch(request).then(function (res) {
    if (res.ok && !res.redirected) {
      var copy = res.clone();
      caches.open(PAGE_CACHE).then(function (cache) { cache.put(url.pathname, copy); });
    }
    return res;
  }).catch(function () {
    return caches.open(PAGE_CACHE)
      .then(function (cache) { return cache.match(url.pathname); })
      .then(function (cached) {
        return cached || new Response(
          "圏外です。電波のあるときに一度開いた入力画面だけ、圏外でも開けます。",
          { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } }
        );
      });
  });
}

// 送信が通信エラーになったら、入力を端末に保存して「未送信の入力」へ移る。
function postOrSave(request) {
  var copy = request.clone();
  return fetch(request).catch(function () {
    return copy.formData().then(function (formData) {
      var item = KecOfflineDB.fromFormData(copy.url, formData);
      return KecOfflineDB.put(item).then(function () {
        return Response.redirect(OUTBOX_URL + "?saved=" + encodeURIComponent(item.id), 303);
      });
    });
  });
}
{% endautoescape %}
