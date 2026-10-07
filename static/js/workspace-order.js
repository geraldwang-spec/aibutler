(() => {
  for (const summary of document.querySelectorAll('[data-choice-summary]')) {
    const form = summary.closest('form');
    if (!form) continue;
    const controls = [...form.elements].filter(control => control.name === summary.dataset.choiceSummary && control.type === 'checkbox');
    const update = () => {
      const count = controls.filter(control => control.checked).length;
      summary.textContent = count ? `已選 ${count} ${summary.dataset.countUnit}` : summary.dataset.emptyLabel;
    };
    for (const control of controls) control.addEventListener('change', update);
    update();
  }
  // Only the reading-record action is asynchronous. Exam creation, uploads and
  // BODY forms retain their original submission and validation behavior.
  document.addEventListener('submit', async event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    const url = new URL(form.getAttribute('action') || location.href, location.href);
    if (url.origin !== location.origin || !/^\/ai\/planner\/task\/\d+\/read$/.test(url.pathname)) return;
    event.preventDefault();
    const button = form.querySelector('button');
    if (!button || button.disabled) return;
    const body = new FormData(form);
    const previous = button.textContent;
    button.disabled = true; button.textContent = '儲存中…';
    form.querySelector('[data-read-error]')?.remove();
    try {
      const response = await fetch(url, {method: 'POST', body, headers: {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}});
      if (response.redirected && /\/login(?:\/|$)/.test(new URL(response.url).pathname)) throw new Error('登入已到期，請重新登入。');
      if (!(response.headers.get('content-type') || '').includes('application/json')) throw new Error(response.status >= 500 ? `閱讀紀錄暫時無法儲存（HTTP ${response.status}），請重新整理確認狀態。` : '頁面驗證失敗，請重新整理後再試。');
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '閱讀紀錄暫時無法儲存。');
      const update = root => {
        for (const candidate of root.querySelectorAll('form[action]')) {
          if (new URL(candidate.getAttribute('action'), location.href).pathname !== url.pathname) continue;
          const status = candidate.closest('.calendar-detail-item')?.querySelector('.calendar-task-status');
          if (status) status.textContent = data.status === 'done' ? '已完成' : '已閱讀';
          const label = document.createElement('small');
          label.setAttribute('role', 'status');
          label.textContent = data.status === 'done' ? '已驗收完成' : '已閱讀（不等於驗收通過）';
          candidate.replaceWith(label);
        }
      };
      update(document);
      for (const template of document.querySelectorAll('template')) update(template.content);
    } catch (error) {
      button.disabled = false; button.textContent = previous;
      const message = document.createElement('small');
      message.dataset.readError = 'true'; message.className = 'error';
      message.setAttribute('role', 'alert'); message.textContent = error.message;
      form.append(message);
    }
  });
})();
