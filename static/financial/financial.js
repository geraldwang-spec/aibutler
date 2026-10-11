// 財務小幫手：1) 依 data-pct 設定分類長條寬度（CSP 不允許 HTML 的 style 屬性，改由 CSSOM 設定）
//             2) 送出表單後鎖住按鈕，避免等待 AI 分類時重複送出、重複記帳
(() => {
  document.querySelectorAll('.fin-bar-fill[data-pct]').forEach((bar) => {
    const pct = Math.max(0, Math.min(100, Number(bar.dataset.pct) || 0));
    requestAnimationFrame(() => { bar.style.width = pct + '%'; });
  });

  document.querySelectorAll('form[data-fin-form]').forEach((form) => {
    form.addEventListener('submit', () => {
      const button = form.querySelector('button[data-busy-text]');
      if (!button) return;
      // 延到下一輪再停用，確保瀏覽器已經開始送出表單
      setTimeout(() => {
        button.disabled = true;
        button.textContent = button.dataset.busyText;
      }, 0);
    });
  });
})();
