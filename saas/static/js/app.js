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
