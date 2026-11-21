// 저장된 화면 설정(글자 크기·화면 모드)을 페이지를 그리기 전에 적용 — KRDS 화면 크기 조절·선명한 화면 모드
(function () {
  var root = document.documentElement;
  try {
    var s = JSON.parse(localStorage.getItem('view-settings') || 'null');
    if (!s) {
      // 예전 다크모드 설정('theme')을 새 화면 모드로 옮김
      var old = localStorage.getItem('theme');
      s = { scale: 1, mode: old === 'dark' ? 'high-contrast' : old === 'light' ? 'light' : 'theme' };
    }
    root.dataset.mode = s.mode || 'theme';
    if (s.scale && s.scale !== 1) root.style.fontSize = (62.5 * s.scale) + '%';
  } catch (e) {
    root.dataset.mode = 'theme';
  }
})();
