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
});

// ガントチャートの月ラベルを数字表記にする。
// frappe-gantt 0.6.1 は英語の月名しか持たず（language:'ja' は月名テーブルが
// 無いため例外になり描画が止まる）、描画後にラベルだけ置き換えている。
// change_view_mode で毎回描き直されるので、表示切替のたびに呼ぶこと。
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
