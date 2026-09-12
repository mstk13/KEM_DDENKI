// 圏外保存の画面側（ADR-0048）。
// - data-offline-form の付いたフォームに、端末の識別番号と名前を付けて送る
// - 圏外なら送らずに端末へ保存し、電波が戻ったら自動で送る
// - 上部に「未送信 N」を出す。ログアウトの前に未送信があれば確かめる
(function () {
  "use strict";

  var DB = window.KecOfflineDB;
  var script = document.currentScript;
  if (!DB || !window.indexedDB || !script) { return; }

  var SW_URL = script.dataset.swUrl;
  var OUTBOX_URL = script.dataset.outboxUrl;
  var RETRY_MS = 60000;
  var flushing = false;

  // Service Worker は HTTPS のときだけ登録できる（IP を直接打つ http の URL では使えない）。
  // 登録できなくても、圏外での保存と自動の送り直しは動く。圏外で画面を開けないだけ。
  if ("serviceWorker" in navigator && window.isSecureContext && SW_URL) {
    navigator.serviceWorker.register(SW_URL, { scope: "/" }).catch(function () {});
  }

  function ensureHidden(form, name, value) {
    var input = form.querySelector('input[name="' + name + '"]');
    if (!input) {
      input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      form.appendChild(input);
    }
    if (!input.value) { input.value = value; }
  }

  function formDataOf(form, submitter) {
    var formData = new FormData(form);
    if (submitter && submitter.name && !formData.has(submitter.name)) {
      formData.append(submitter.name, submitter.value);
    }
    return formData;
  }

  function toast(message) {
    var el = document.createElement("div");
    el.className = "offline-toast";
    el.setAttribute("role", "status");
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(function () { el.remove(); }, 4000);
  }

  function refreshBadge() {
    var badge = document.getElementById("offline-outbox-badge");
    return DB.count().then(function (n) {
      if (badge) {
        badge.style.display = n ? "" : "none";
        var countEl = badge.querySelector("[data-count]");
        if (countEl) { countEl.textContent = n; }
      }
      document.dispatchEvent(new CustomEvent("kec-offline-changed", { detail: { count: n } }));
      return n;
    }).catch(function () { return 0; });
  }

  // ---- 送信を横取りする ----
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) { return; }

    if (form.hasAttribute("data-offline-logout")) {
      confirmLogout(event, form);
      return;
    }
    if (!form.hasAttribute("data-offline-form")) { return; }

    ensureHidden(form, "client_request_id", DB.newId());
    ensureHidden(form, "offline_label", form.getAttribute("data-offline-label") || document.title);
    // 電波があれば、ふつうに送る（識別番号でサーバーが二重登録を防ぐ）。
    // 送信が通信エラーになった場合は Service Worker が端末に保存する。
    if (navigator.onLine) { return; }

    event.preventDefault();
    var item = DB.fromFormData(form.action || location.href, formDataOf(form, event.submitter));
    DB.put(item).then(function () {
      if (navigator.serviceWorker && navigator.serviceWorker.controller) {
        location.href = OUTBOX_URL + "?saved=" + encodeURIComponent(item.id);
        return;
      }
      refreshBadge();
      toast("圏外のため、この端末に保存しました。電波が戻ったら自動で送ります。");
    }).catch(function () {
      alert("この端末に保存できませんでした。電波のある場所で送ってください。");
    });
  }, true);

  function confirmLogout(event, form) {
    event.preventDefault();
    DB.count().then(function (n) {
      if (n && !confirm("未送信の入力が " + n + " 件あります。ログアウトすると、この端末から消えて送れなくなります。ログアウトしますか？")) {
        return false;
      }
      return clearDevice().then(function () { return true; });
    }, function () { return true; }).then(function (proceed) {
      if (proceed) { form.submit(); }
    });
  }

  // ログアウトのとき、端末に残した入力と画面の控えを消す（端末を共有しても読まれないように）。
  function clearDevice() {
    var jobs = [DB.clear().catch(function () {})];
    if (window.caches) {
      jobs.push(caches.keys().then(function (keys) {
        return Promise.all(keys.filter(function (key) {
          return key.indexOf("kec-") === 0;
        }).map(function (key) { return caches.delete(key); }));
      }).catch(function () {}));
    }
    return Promise.all(jobs);
  }

  // ---- 送り直し ----
  function csrfToken() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function toFormData(item) {
    var formData = new FormData();
    item.fields.forEach(function (field) {
      if (field.file) {
        formData.append(field.name, field.file, field.filename);
      } else {
        formData.append(field.name, field.value);
      }
    });
    formData.set("csrfmiddlewaretoken", csrfToken());
    return formData;
  }

  // 結果: sent（登録できた・登録済みだった）/ login（ログインが切れている）/ error（直す必要がある）。
  // 通信できないときは reject する（次の機会に送る）。
  function send(item) {
    return fetch(item.url, {
      method: "POST",
      body: toFormData(item),
      credentials: "same-origin",
      headers: { "X-Offline-Resend": "1" },
    }).then(function (res) {
      if (res.redirected && /\/login\//.test(res.url)) {
        return { status: "login", message: "ログインし直すと自動で送ります。" };
      }
      if (res.status === 403) {
        return { status: "login", message: "送信が断られました。ログインし直すと自動で送ります。" };
      }
      var type = res.headers.get("Content-Type") || "";
      if (type.indexOf("application/json") === -1) {
        return { status: "error", message: "送信できませんでした（" + res.status + "）。" };
      }
      return res.json().then(function (data) {
        if (data.ok) { return { status: "sent" }; }
        return { status: "error", message: data.message || "送信できませんでした。" };
      });
    });
  }

  function flush() {
    if (flushing || !navigator.onLine) { return Promise.resolve(); }
    flushing = true;
    return DB.list().then(function (items) {
      var targets = items.filter(function (item) {
        return item.status === "pending" || item.status === "login";
      });
      return targets.reduce(function (chain, item) {
        return chain.then(function (stop) {
          if (stop) { return true; }
          return send(item).then(function (result) {
            if (result.status === "sent") {
              return DB.remove(item.id).then(function () {
                toast("送信しました: " + item.label);
                return false;
              });
            }
            item.status = result.status;
            item.message = result.message;
            // ログインが切れていたら、残りも同じなのでここで止める
            return DB.put(item).then(function () { return result.status === "login"; });
          }, function () {
            return true;  // 通信できない。次の機会に送る
          });
        });
      }, Promise.resolve(false));
    }).catch(function () {}).then(function () {
      flushing = false;
      return refreshBadge();
    });
  }

  // ---- きっかけ ----
  window.addEventListener("online", flush);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") { flush(); }
  });
  setInterval(flush, RETRY_MS);
  refreshBadge();
  flush();

  window.KecOffline = { flush: flush, refreshBadge: refreshBadge, db: DB };
})();
