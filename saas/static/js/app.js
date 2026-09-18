// Sidebar toggle (mobile)
document.addEventListener('DOMContentLoaded', function() {
  const hamburger = document.querySelector('.hamburger');
  const sidebar = document.querySelector('.sidebar');
  if (hamburger && sidebar) {
    hamburger.addEventListener('click', function() {
      sidebar.classList.toggle('open');
    });
    document.addEventListener('click', function(e) {
      if (window.innerWidth <= 768 && !sidebar.contains(e.target) && !hamburger.contains(e.target)) {
        sidebar.classList.remove('open');
      }
    });
  }

  // Collapsible nav groups
  document.querySelectorAll('.nav-group .nav-section').forEach(function(btn) {
    btn.addEventListener('click', function() {
      this.closest('.nav-group').classList.toggle('open');
    });
  });

  // Collapsible accordion (業種別一覧など)
  document.querySelectorAll('.acc-group .acc-head').forEach(function(btn) {
    btn.addEventListener('click', function() {
      this.closest('.acc-group').classList.toggle('open');
    });
  });

  // 一括選択チェックボックス。data-check-all="<name>" を付けると同名の
  // チェックボックスをまとめて切り替える。
  document.querySelectorAll('[data-check-all]').forEach(function(master) {
    var name = master.dataset.checkAll;
    master.addEventListener('change', function() {
      document.querySelectorAll('input[name="' + name + '"]').forEach(function(cb) {
        cb.checked = master.checked;
      });
    });
  });

  // 条件付きフィールド。チェックボックスに data-toggle-target="<field名>" を
  // 付けると、その名前のフィールドを含む .form-group をチェック時のみ表示する。
  // 例: 日報の「協力会社の作業員」→「協力会社」
  document.querySelectorAll('[data-toggle-target]').forEach(function(source) {
    var target = document.querySelector('[name="' + source.dataset.toggleTarget + '"]');
    if (!target) return;
    var group = target.closest('.form-group') || target;
    var sync = function() {
      group.style.display = source.checked ? '' : 'none';
    };
    source.addEventListener('change', sync);
    sync();
  });
});

// ガントチャートの月ラベルを数字表記にする。
// frappe-gantt 0.6.1 は英語の月名しか持たず（language:'ja' は月名テーブルが
// 無いため例外になり描画が止まる）、描画後にラベルだけ置き換えている。
// change_view_mode で毎回描き直されるので、表示切替のたびに呼ぶこと。
// ガントの目盛りを当日から始める（ADR-0072）。
// frappe-gantt 0.6.1 は「一番早い開始日の1か月前」から目盛りを引くので、
// タスクを当日から先だけにしても、左側に過ぎた日が残ってしまう。
// 表示（日・週・月）を切り替えるたびに日付を作り直すので、クラスの側で差し替える。
function clampGanttStartToToday(GanttClass) {
  if (!GanttClass || GanttClass.__clampedToToday) return;
  var setupDates = GanttClass.prototype.setup_gantt_dates;
  GanttClass.prototype.setup_gantt_dates = function () {
    setupDates.call(this);
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    if (this.gantt_start && this.gantt_start < today) {
      this.gantt_start = today;
    }
  };
  GanttClass.__clampedToToday = true;
}

// 一番左の目盛り（当日）のラベルを読めるようにする（ADR-0072）。
// 1) 中央そろえだと半分が枠の外に出るので、最初の1つだけ左そろえにする。
//    frappe-gantt の CSS が text-anchor: middle を指定しているため、属性ではなく style で上書きする
// 2) frappe-gantt 0.6.1 は日表示の一番左の日付（上の段）を出さない。
//    1つ前の日と比べる処理で、最初だけ「1年後の同じ日」と比べてしまい、日が同じとみなされるため。
//    当日の日付を自分で足す
function showFirstGanttLabel(container) {
  var lower = container.querySelectorAll('.lower-text');
  if (!lower.length) return;
  lower[0].style.textAnchor = 'start';

  var upper = container.querySelector('.upper-text');
  if (!upper || !upper.parentNode) return;
  // 上の段が「9/17」のような日付のとき（日表示）だけ補う。週・月表示は「10月」なので触らない
  if (!/^\d{1,2}\/\d{1,2}$/.test(upper.textContent.trim())) return;
  var firstX = parseFloat(lower[0].getAttribute('x'));
  if (parseFloat(upper.getAttribute('x')) - firstX < 1) return;

  var today = new Date();
  var label = upper.cloneNode(true);
  label.textContent = (today.getMonth() + 1) + '/' + today.getDate();
  // その日のかたまりの左端にそろえる（下の段のラベルは日のまん中に置かれている）
  label.setAttribute('x', 2);
  label.style.textAnchor = 'start';
  upper.parentNode.insertBefore(label, upper);
}

function localizeGanttMonths(container) {
  var MONTHS = {
    January: 1, February: 2, March: 3, April: 4, May: 5, June: 6,
    July: 7, August: 8, September: 9, October: 10, November: 11, December: 12
  };
  container.querySelectorAll('.upper-text, .lower-text').forEach(function(el) {
    // 月のみ（"August"）と 日＋月（"05 August"）の2形式が来る
    var m = el.textContent.trim().match(/^(?:(\d{1,2})\s+)?([A-Za-z]+)$/);
    if (!m || !MONTHS[m[2]]) return;
    el.textContent = m[1] ? MONTHS[m[2]] + '/' + parseInt(m[1], 10) : MONTHS[m[2]] + '月';
  });
}

// 一覧から選んだものをまとめて消す（ADR-0098）。
// 行のチェックボックスは form 属性でバーの form につながっている。
// 1つの画面に表が複数あることがあるので、バーごとに数える。
(function () {
  function bars() {
    return Array.prototype.slice.call(document.querySelectorAll('.bulk-delete-bar'));
  }

  function boxesFor(bar) {
    // バー自体が form（共通部品）か、form の中の div（日報の一覧）のどちらか
    var owner = bar.tagName === 'FORM' ? bar : bar.closest('form');
    var byAttribute = owner && owner.id
      ? document.querySelectorAll('.bulk-check[form="' + owner.id + '"]')
      : [];
    if (byAttribute.length) return Array.prototype.slice.call(byAttribute);
    var scope = owner || document;
    return Array.prototype.slice.call(scope.querySelectorAll('.bulk-check'));
  }

  function refresh() {
    bars().forEach(function (bar) {
      var checked = boxesFor(bar).filter(function (box) { return box.checked; });
      var count = bar.querySelector('.bulk-delete-count');
      var button = bar.querySelector('.bulk-delete-button');
      var label = button ? button.dataset.label : '';
      bar.classList.toggle('has-selection', checked.length > 0);
      if (button) button.disabled = checked.length === 0;
      if (count) {
        count.textContent = checked.length
          ? checked.length + ' 件の' + label + 'を選んでいます'
          : count.dataset.empty;
      }
    });
  }

  document.addEventListener('change', function (e) {
    if (e.target.classList.contains('bulk-check-all')) {
      // 「全部選ぶ」は、その表の中だけに効かせる
      var table = e.target.closest('table') || document;
      Array.prototype.slice.call(table.querySelectorAll('.bulk-check')).forEach(
        function (box) { box.checked = e.target.checked; }
      );
      refresh();
      return;
    }
    if (e.target.classList.contains('bulk-check')) refresh();
  });

  document.addEventListener('click', function (e) {
    var button = e.target.closest ? e.target.closest('.bulk-delete-button') : null;
    if (!button) return;
    var bar = button.closest('.bulk-delete-bar');
    var checked = boxesFor(bar).filter(function (box) { return box.checked; });
    var message = checked.length + ' 件の' + button.dataset.label
      + 'を削除します。
この操作は元に戻せません。よろしいですか？';
    if (!window.confirm(message)) e.preventDefault();
  });

  document.addEventListener('DOMContentLoaded', refresh);
})();
