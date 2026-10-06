(() => {
  if (window.recordsWorkspace || !document.querySelector('[data-record-workspace]')) return;
  let busy = false;
  const message = document.createElement('p');
  message.className = 'notice info';
  message.hidden = true;
  message.setAttribute('role', 'status');
  document.querySelector('[data-record-workspace]').before(message);
  const allowed = url => url.origin === location.origin &&
    (/^\/records\/(subjects|chapters|questions)(?:\/\d+\/delete)?$/.test(url.pathname) ||
      /^\/subjects\/\d+\/organize$/.test(url.pathname) || url.pathname === '/knowledge' ||
      /^\/ai\/concepts(?:\/\d+\/change|\/source\/\d+)?$/.test(url.pathname));
  const announce = (text, error = false) => {
    message.hidden = false;
    message.className = 'notice ' + (error ? 'error' : 'info');
    message.replaceChildren(document.createTextNode(text));
  };
  async function update(target, {method = 'GET', body, preserve = false, push = false} = {}) {
    if (busy) return;
    const url = new URL(target, location.href);
    if (!allowed(url)) return;
    const current = document.querySelector('[data-record-workspace]');
    if (!current) return;
    const scroll = window.scrollY;
    const saved = preserve ? [...current.querySelectorAll('input:not([type="hidden"]), select, textarea')].map((input, index) =>
      ({index, value: input.value, checked: input.checked})) : [];
    const opened = preserve ? [...current.querySelectorAll('details')].map(node => node.open) : [];
    busy = true;
    current.setAttribute('aria-busy', 'true');
    current.inert = true;
    announce(method === 'POST' ? '正在儲存，畫面會直接更新…' : '正在載入資料…');
    try {
      const response = await fetch(url, {method, body, credentials: 'same-origin',
        headers: {'X-Workspace-Fragment': 'records', 'X-Requested-With': 'XMLHttpRequest'}});
      const destination = new URL(response.url);
      if (/\/login(?:\/|$)/.test(destination.pathname)) throw new Error('登入已到期，請重新登入。');
      if (!response.ok) throw new Error(`操作無法確認（HTTP ${response.status}）。`);
      if (!(response.headers.get('content-type') || '').includes('text/html')) throw new Error('伺服器回傳的資料格式不正確。');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const replacement = page.querySelector('[data-record-workspace]');
      if (!replacement || !allowed(destination)) throw new Error('未取得更新後的資料。');
      const notices = [...page.querySelectorAll('.workspace-content > .notice')];
      const failed = notices.some(node => node.classList.contains('error'));
      // Scripts stay attached to the existing document. Rebind only this workspace.
      replacement.querySelectorAll('script').forEach(script => script.remove());
      current.replaceWith(replacement);
      if (preserve) {
        const inputs = [...replacement.querySelectorAll('input:not([type="hidden"]), select, textarea')];
        saved.forEach(state => {
          if (!inputs[state.index]) return;
          inputs[state.index].value = state.value;
          inputs[state.index].checked = state.checked;
        });
        replacement.querySelectorAll('details').forEach((node, index) => { if (opened[index] !== undefined) node.open = opened[index]; });
      }
      document.dispatchEvent(new Event('records-workspace-updated'));
      if (preserve) replacement.querySelectorAll('input[type="search"]').forEach(input => input.dispatchEvent(new Event('input', {bubbles: true})));
      const heading = document.querySelector('.page-heading h1');
      const newHeading = page.querySelector('.page-heading h1');
      if (heading && newHeading) heading.textContent = newHeading.textContent;
      document.title = page.title;
      // Replace stale validation notices; the new status reports the server result.
      document.querySelectorAll('.workspace-content > .notice').forEach(node => { if (node !== message) node.remove(); });
      const path = destination.pathname + destination.search;
      if (location.pathname + location.search !== path) history[push ? 'pushState' : 'replaceState'](null, '', path);
      announce(notices.map(node => node.textContent.trim()).join(' ') || (method === 'POST' ? '已儲存，畫面已更新。' : '資料已更新。'), failed);
      window.scrollTo({top: scroll, behavior: 'instant'});
    } catch (error) {
      announce(error.message + (method === 'POST' ? ' 已送出的操作不會自動重送；請先重新取得資料確認結果。' : ''), true);
      const refresh = document.createElement('button');
      refresh.type = 'button'; refresh.className = 'secondary-button'; refresh.textContent = '重新取得資料';
      refresh.addEventListener('click', () => update(location.href));
      message.append(' ', refresh);
    } finally {
      busy = false;
      const workspace = document.querySelector('[data-record-workspace]');
      if (workspace) { workspace.removeAttribute('aria-busy'); workspace.inert = false; }
    }
  }
  window.recordsWorkspace = {update, get busy() { return busy; }};
  document.addEventListener('click', event => {
    const link = event.target.closest('[data-record-workspace] a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || link.download || (link.target && link.target !== '_self')) return;
    const url = new URL(link.href);
    if (!allowed(url) || !(/^\/records\/(subjects|chapters|questions)$/.test(url.pathname) || ['/knowledge', '/ai/concepts'].includes(url.pathname))) return;
    event.preventDefault();
    update(url, {push: true});
  });
  document.addEventListener('submit', event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.closest('[data-record-workspace]')) return;
    const url = new URL(form.getAttribute('action') || location.href, location.href);
    if (!allowed(url)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (busy || (form.dataset.confirm && !window.confirm(form.dataset.confirm))) return;
    const body = new FormData(form);
    if (event.submitter?.name) body.append(event.submitter.name, event.submitter.value);
    if ((form.getAttribute('method') || 'get').toLowerCase() === 'get') {
      url.search = new URLSearchParams(body).toString();
      update(url, {push: true});
    } else {
      update(url, {method: 'POST', body, preserve: ['up', 'down'].includes(body.get('action'))});
    }
  }, true);
  window.addEventListener('popstate', () => { if (allowed(new URL(location.href))) update(location.href); });
})();
