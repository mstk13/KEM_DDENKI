// サインを書く欄（ADR-0061）。
// data-signature-pad の中の canvas に指（マウス・ペン）で書くと、書き終えるたびに
// 同じ欄の hidden の入力へ PNG の data URL を入れる。「書き直す」で消す。
// 入力に誤りがあって画面が戻ってきたときは、hidden に残っているサインを描き直す。
(function () {
  "use strict";

  function setup(root) {
    var canvas = root.querySelector("canvas");
    var input = root.querySelector('input[type="hidden"]');
    var clearButton = root.querySelector("[data-signature-clear]");
    if (!canvas || !input) { return; }
    var ctx = canvas.getContext("2d");
    var drawing = false;
    var last = null;

    function restore() {
      if (!input.value) { return; }
      var image = new Image();
      image.onload = function () {
        var rect = canvas.getBoundingClientRect();
        ctx.drawImage(image, 0, 0, rect.width, rect.height);
      };
      image.src = input.value;
    }

    function resize() {
      var ratio = window.devicePixelRatio || 1;
      var rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.round(rect.width * ratio));
      canvas.height = Math.max(1, Math.round(rect.height * ratio));
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.lineWidth = 2.4;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.strokeStyle = "#111";
      ctx.fillStyle = "#111";
      restore();
    }

    function point(event) {
      var rect = canvas.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    }

    canvas.addEventListener("pointerdown", function (event) {
      event.preventDefault();
      // 指が枠の外へ出ても書き続けられるように捕まえる。捕まえられない端末でも書けるようにする
      try { canvas.setPointerCapture(event.pointerId); } catch (e) { /* そのまま書く */ }
      drawing = true;
      last = point(event);
      ctx.beginPath();
      ctx.arc(last.x, last.y, 1.2, 0, Math.PI * 2);
      ctx.fill();
    });

    canvas.addEventListener("pointermove", function (event) {
      if (!drawing) { return; }
      event.preventDefault();
      var next = point(event);
      ctx.beginPath();
      ctx.moveTo(last.x, last.y);
      ctx.lineTo(next.x, next.y);
      ctx.stroke();
      last = next;
    });

    function finish() {
      if (!drawing) { return; }
      drawing = false;
      input.value = canvas.toDataURL("image/png");
    }
    canvas.addEventListener("pointerup", finish);
    canvas.addEventListener("pointercancel", finish);
    canvas.addEventListener("pointerleave", finish);

    if (clearButton) {
      clearButton.addEventListener("click", function () {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        input.value = "";
      });
    }

    resize();
    window.addEventListener("resize", resize);
  }

  document.querySelectorAll("[data-signature-pad]").forEach(setup);
})();
