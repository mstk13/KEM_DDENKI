// 圏外で保存した入力の置き場（端末の IndexedDB）。ADR-0048。
// 画面（window）と Service Worker（self）の両方から読み込んで同じ置き場を使う。
(function (global) {
  "use strict";

  var DB_NAME = "kec-offline";
  var STORE = "outbox";

  function open() {
    return new Promise(function (resolve, reject) {
      var req = global.indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = function () {
        req.result.createObjectStore(STORE, { keyPath: "id" });
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  // fn は store を受け取り、結果を読みたい IDBRequest を返してよい。
  function withStore(mode, fn) {
    return open().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, mode);
        var request = fn(tx.objectStore(STORE));
        tx.oncomplete = function () {
          db.close();
          resolve(request ? request.result : undefined);
        };
        tx.onerror = tx.onabort = function () {
          db.close();
          reject(tx.error);
        };
      });
    });
  }

  function newId() {
    if (global.crypto && global.crypto.randomUUID) { return global.crypto.randomUUID(); }
    // randomUUID の無い古い端末向け（UUID v4 の形）
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = Math.floor(Math.random() * 16);
      return (c === "x" ? r : (r % 4) + 8).toString(16);
    });
  }

  // 送信する FormData を、置き場に入れる形にする。
  // CSRF のトークンは送り直すときに付け直すので保存しない。空のファイル欄は入れない。
  function fromFormData(url, formData) {
    var fields = [];
    var id = "";
    var label = "";
    formData.forEach(function (value, name) {
      if (name === "csrfmiddlewaretoken") { return; }
      if (typeof value === "string") {
        if (name === "client_request_id") { id = value; }
        if (name === "offline_label") { label = value; }
        fields.push({ name: name, value: value });
        return;
      }
      if (!value || (!value.size && !value.name)) { return; }
      fields.push({ name: name, file: value, filename: value.name || "upload", type: value.type || "" });
    });
    if (!id) {
      id = newId();
      fields.push({ name: "client_request_id", value: id });
    }
    return {
      id: id,
      url: url,
      label: label || url,
      savedAt: new Date().toISOString(),
      status: "pending",
      message: "",
      fields: fields,
    };
  }

  function put(item) {
    return withStore("readwrite", function (store) { store.put(item); });
  }

  function list() {
    return withStore("readonly", function (store) { return store.getAll(); }).then(function (items) {
      return (items || []).sort(function (a, b) { return a.savedAt < b.savedAt ? -1 : 1; });
    });
  }

  function remove(id) {
    return withStore("readwrite", function (store) { store.delete(id); });
  }

  function clear() {
    return withStore("readwrite", function (store) { store.clear(); });
  }

  function count() {
    return withStore("readonly", function (store) { return store.count(); });
  }

  global.KecOfflineDB = {
    newId: newId,
    fromFormData: fromFormData,
    put: put,
    list: list,
    remove: remove,
    clear: clear,
    count: count,
  };
})(typeof self !== "undefined" ? self : window);
