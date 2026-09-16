// 画面の文字をタップして、その場で直す（ADR-0073）。
//
// テンプレート側は bid_filters の {% inline_edit obj "field" %} で
// <span class="inline-edit" data-model=... data-pk=... data-field=... data-type=...> を出す。
// ここでは、その span をタップしたときに入力欄へ差し替え、
// Enter（複数行は Ctrl+Enter）または外をタップで保存する。Esc で取り消す。
(function () {
  var ENDPOINT = '/bids/inline-edit/';

  function csrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function buildInput(span) {
    var type = span.dataset.type;
    var value = span.dataset.value || '';
    var input;
    if (type === 'select' || type === 'boolean') {
      input = document.createElement('select');
      var choices = type === 'boolean'
        ? [['true', 'はい'], ['false', 'いいえ']]
        : JSON.parse(span.dataset.choices || '[]');
      choices.forEach(function (choice) {
        var option = document.createElement('option');
        option.value = choice[0];
        option.textContent = choice[1];
        if (choice[0] === value) option.selected = true;
        input.appendChild(option);
      });
    } else if (type === 'textarea') {
      input = document.createElement('textarea');
      var lines = value.split('\n').length + 1;
      input.rows = span.dataset.block === '1'
        ? Math.min(24, Math.max(8, lines))
        : Math.min(10, Math.max(3, lines));
      input.value = value;
    } else {
      input = document.createElement('input');
      input.type = type === 'number' ? 'number'
        : type === 'date' ? 'date'
        : type === 'datetime' ? 'datetime-local'
        : 'text';
      if (type === 'number') input.step = 'any';
      input.value = value;
    }
    input.className = 'inline-edit-input form-control';
    if (span.dataset.block === '1') input.classList.add('inline-edit-block-input');
    return input;
  }

  function showError(span, message) {
    var box = document.createElement('div');
    box.className = 'inline-edit-error';
    box.textContent = message;
    span.parentNode.insertBefore(box, span.nextSibling);
    setTimeout(function () {
      if (box.parentNode) box.parentNode.removeChild(box);
    }, 6000);
  }

  function startEdit(span) {
    if (span.dataset.editing === '1') return;
    span.dataset.editing = '1';
    var input = buildInput(span);
    var previous = span.innerHTML;
    span.innerHTML = '';
    span.appendChild(input);
    input.focus();
    if (input.select) input.select();

    var finished = false;

    function cancel() {
      if (finished) return;
      finished = true;
      span.innerHTML = previous;
      span.dataset.editing = '';
    }

    function save() {
      if (finished) return;
      finished = true;
      var value = input.value;
      if (value === (span.dataset.value || '')) {
        span.innerHTML = previous;
        span.dataset.editing = '';
        return;
      }
      span.textContent = '保存中…';
      fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
        body: JSON.stringify({
          model: span.dataset.model, pk: span.dataset.pk,
          field: span.dataset.field, value: value
        })
      }).then(function (res) {
        return res.json().catch(function () { return { ok: false, error: '保存できませんでした。' }; });
      }).then(function (data) {
        span.dataset.editing = '';
        if (data.ok) {
          // 判定結果や図が一緒に変わる欄は、画面を読み直して出し直す
          if (span.dataset.reload === '1') { window.location.reload(); return; }
          span.textContent = data.display;
          span.dataset.value = data.value;
          span.classList.add('inline-edit-saved');
          setTimeout(function () { span.classList.remove('inline-edit-saved'); }, 1200);
        } else {
          span.innerHTML = previous;
          showError(span, data.error || '保存できませんでした。');
        }
      }).catch(function () {
        span.dataset.editing = '';
        span.innerHTML = previous;
        showError(span, '保存できませんでした。通信を確かめてください。');
      });
    }

    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); cancel(); return; }
      if (e.key === 'Enter') {
        var multiline = input.tagName === 'TEXTAREA';
        if (!multiline || e.ctrlKey || e.metaKey) { e.preventDefault(); save(); }
      }
    });
    input.addEventListener('blur', save);
    // select は選んだ時点で保存する
    if (input.tagName === 'SELECT') input.addEventListener('change', save);
  }

  document.addEventListener('click', function (e) {
    var span = e.target.closest ? e.target.closest('.inline-edit') : null;
    if (!span || span.dataset.editing === '1') return;
    e.preventDefault();
    startEdit(span);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter') return;
    var span = e.target.closest ? e.target.closest('.inline-edit') : null;
    if (!span || span.dataset.editing === '1') return;
    e.preventDefault();
    startEdit(span);
  });
})();
