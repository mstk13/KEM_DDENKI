// スマホへのプッシュ通知（ADR-0062）。
// - data-push-panel の欄に、この端末の状態（受け取る・受け取らない・使えない理由）を出す
// - 「受け取る」を押したときだけ通知の許可を求め、この端末の送り先をサーバーに登録する
// - 受け取っている端末は、ログインした人が変わったとき・サーバーの鍵が変わったとき・1日1回、登録し直す
// - ログアウトのとき、この端末の送り先を消す（offline.js が KecPush.forgetDevice を呼ぶ）
(function () {
  "use strict";

  var script = document.currentScript;
  if (!script) { return; }
  var PUBLIC_KEY = script.dataset.publicKey || "";
  var USER_ID = script.dataset.userId || "";
  var SW_URL = script.dataset.swUrl || "";
  var SUBSCRIBE_URL = script.dataset.subscribeUrl;
  var UNSUBSCRIBE_URL = script.dataset.unsubscribeUrl;
  var TEST_URL = script.dataset.testUrl;
  var SYNC_KEY = "kec-push-sync";
  var DISMISS_KEY = "kec-push-dismissed";
  var SYNC_MS = 24 * 60 * 60 * 1000;
  var READY_TIMEOUT_MS = 8000;
  var LOGOUT_WAIT_MS = 3000;

  function readStorage(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  function writeStorage(key, value) {
    try {
      if (value === null) { localStorage.removeItem(key); } else { localStorage.setItem(key, value); }
    } catch (e) { /* 保存できない端末では、画面を開くたびに登録し直す */ }
  }

  function isIos() {
    return /iPad|iPhone|iPod/.test(navigator.userAgent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  }

  function isStandalone() {
    return (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
      navigator.standalone === true;
  }

  // Service Worker は HTTPS のときだけ。iPhone はホーム画面に追加したアプリの中でだけ PushManager がある
  function supported() {
    return window.isSecureContext && "serviceWorker" in navigator &&
      "PushManager" in window && "Notification" in window;
  }

  function toBase64Url(bytes) {
    var text = "";
    for (var i = 0; i < bytes.length; i++) { text += String.fromCharCode(bytes[i]); }
    return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function fromBase64Url(text) {
    var base64 = text.replace(/-/g, "+").replace(/_/g, "/");
    base64 += "===".slice((base64.length + 3) % 4);
    var raw = atob(base64);
    var bytes = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) { bytes[i] = raw.charCodeAt(i); }
    return bytes;
  }

  function csrfToken() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(body || {}),
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok || !data.ok) {
          throw new Error(data.message || "サーバーに送れませんでした（" + res.status + "）。");
        }
        return data;
      });
    });
  }

  var readyPromise = null;
  function ready() {
    if (!readyPromise) {
      // Service Worker は offline.js も登録する。こちらからも頼んでおく（同じものなら何も起きない）
      if (SW_URL) { navigator.serviceWorker.register(SW_URL, { scope: "/" }).catch(function () {}); }
      readyPromise = Promise.race([
        navigator.serviceWorker.ready,
        new Promise(function (resolve, reject) {
          setTimeout(function () {
            reject(new Error("この端末では通知の準備ができませんでした。画面を開き直してください。"));
          }, READY_TIMEOUT_MS);
        }),
      ]);
      readyPromise.catch(function () { readyPromise = null; });
    }
    return readyPromise;
  }

  function currentSubscription() {
    return ready().then(function (registration) { return registration.pushManager.getSubscription(); });
  }

  function sameKey(subscription) {
    var key = subscription.options && subscription.options.applicationServerKey;
    if (!key) { return true; }  // 確かめられないブラウザは、そのまま使う
    return toBase64Url(new Uint8Array(key)) === PUBLIC_KEY;
  }

  function newSubscription(registration) {
    return registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: fromBase64Url(PUBLIC_KEY),
    });
  }

  function register(subscription) {
    return post(SUBSCRIBE_URL, subscription.toJSON()).then(function () {
      writeStorage(SYNC_KEY, JSON.stringify({ user: USER_ID, at: Date.now() }));
      return subscription;
    });
  }

  function detectState() {
    if (!PUBLIC_KEY) { return Promise.resolve("no-key"); }
    if (!supported()) { return Promise.resolve(isIos() && !isStandalone() ? "ios-home" : "unsupported"); }
    if (Notification.permission === "denied") { return Promise.resolve("denied"); }
    return currentSubscription().then(function (subscription) {
      return subscription && Notification.permission === "granted" ? "on" : "off";
    }, function () { return "unsupported"; });
  }

  function requestPermission() {
    var result = Notification.requestPermission();
    return result && result.then ? result : Promise.resolve(Notification.permission);
  }

  function subscribe() {
    // 許可を求めるのは、ボタンを押したその場でないといけない（iPhone は後からだと断られる）
    return requestPermission().then(function (permission) {
      if (permission !== "granted") {
        throw new Error(permission === "denied"
          ? "通知がブロックされました。端末の設定でこのアプリの通知を許可してください。"
          : "通知が許可されませんでした。");
      }
      return ready();
    }).then(function (registration) {
      return registration.pushManager.getSubscription().then(function (old) {
        if (old && !sameKey(old)) { return old.unsubscribe().then(function () { return null; }); }
        return old;
      }).then(function (subscription) {
        return subscription || newSubscription(registration);
      });
    }).then(register).then(function () {
      writeStorage(DISMISS_KEY, null);
    });
  }

  function unsubscribe() {
    return currentSubscription().then(function (subscription) {
      if (!subscription) { return null; }
      return post(UNSUBSCRIBE_URL, { endpoint: subscription.endpoint }).then(function () {
        return subscription.unsubscribe();
      });
    }).then(function () {
      writeStorage(SYNC_KEY, null);
    });
  }

  // ログアウトのとき。サーバーに届かなくても端末側はやめる。ログアウトを長く待たせない
  function forgetDevice() {
    writeStorage(SYNC_KEY, null);
    if (!supported()) { return Promise.resolve(); }
    var job = currentSubscription().then(function (subscription) {
      if (!subscription) { return null; }
      return post(UNSUBSCRIBE_URL, { endpoint: subscription.endpoint })
        .catch(function () {})
        .then(function () { return subscription.unsubscribe(); });
    }).catch(function () {});
    return Promise.race([job, new Promise(function (resolve) { setTimeout(resolve, LOGOUT_WAIT_MS); })]);
  }

  // 受け取っている端末は、送り先をときどき登録し直す。
  // ログインした人が変わった・サーバーの鍵が変わった・前に登録してから1日たったとき
  function sync(state) {
    if (state !== "on") { return; }
    var stamp = {};
    try { stamp = JSON.parse(readStorage(SYNC_KEY) || "{}") || {}; } catch (e) { stamp = {}; }
    ready().then(function (registration) {
      return registration.pushManager.getSubscription().then(function (subscription) {
        if (!subscription) { return null; }
        if (!sameKey(subscription)) {
          // 通知の許可は済んでいるので、聞き直さずに取り直す
          return subscription.unsubscribe()
            .then(function () { return newSubscription(registration); })
            .then(register);
        }
        if (stamp.user === USER_ID && Date.now() - (stamp.at || 0) < SYNC_MS) { return null; }
        return register(subscription);
      });
    }).catch(function () {});
  }

  function render(state) {
    var dismissed = !!readStorage(DISMISS_KEY);
    document.querySelectorAll("[data-push-panel]").forEach(function (panel) {
      panel.setAttribute("data-push-state", state);
      panel.querySelectorAll("[data-push-when]").forEach(function (el) {
        el.hidden = el.getAttribute("data-push-when").split(" ").indexOf(state) === -1;
      });
      if (panel.hasAttribute("data-push-banner")) {
        panel.hidden = dismissed || (state !== "off" && state !== "ios-home");
      }
    });
  }

  function showMessage(text, isError) {
    document.querySelectorAll("[data-push-message]").forEach(function (el) {
      el.textContent = text || "";
      el.hidden = !text;
      el.classList.toggle("is-error", !!isError);
    });
  }

  function refresh() {
    return detectState().then(function (state) {
      render(state);
      return state;
    });
  }

  document.addEventListener("click", function (event) {
    var button = event.target && event.target.closest ? event.target.closest("[data-push-action]") : null;
    if (!button) { return; }
    var action = button.getAttribute("data-push-action");
    if (action === "dismiss") {
      writeStorage(DISMISS_KEY, String(Date.now()));
      refresh();
      return;
    }
    var job;
    if (action === "subscribe") {
      job = subscribe().then(function () { return "この端末で通知を受け取るようにしました。"; });
    } else if (action === "unsubscribe") {
      job = unsubscribe().then(function () { return "この端末では通知を受け取らないようにしました。"; });
    } else if (action === "test") {
      job = post(TEST_URL).then(function (data) { return data.message; });
    } else {
      return;
    }
    button.disabled = true;
    job.then(function (message) {
      showMessage(message, false);
    }, function (error) {
      showMessage((error && error.message) || "うまくいきませんでした。", true);
    }).then(function () {
      button.disabled = false;
      return refresh();
    });
  });

  window.KecPush = { forgetDevice: forgetDevice, refresh: refresh };
  refresh().then(sync);
})();
