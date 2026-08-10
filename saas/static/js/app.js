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
