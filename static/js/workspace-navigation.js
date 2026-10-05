(() => {
  const pane = document.getElementById('workspace-pane');
  if (!pane) return;
  const loading = document.getElementById('workspace-loading');
  const title = document.getElementById('workspace-title');
  const nav = document.getElementById('main-nav');
  const links = [...nav.querySelectorAll('a[href]')];
  const path = url => url.pathname.replace(/\/$/, '') || '/';
  const key = url => url.pathname + url.search + url.hash;
  const isAuth = url => /\/(login|register|forgot-password|reset-password)(\/|$)/.test(url.pathname);
  function navigate(url) {
    // Replace the pane's history entry; the outer shell owns sidebar navigation.
    // This prevents a sidebar click from adding two browser history entries.
    try { pane.contentWindow.location.replace(key(url)); }
    catch { pane.src = key(url); }
  }

  function highlight(url) {
    let best = null;
    let bestScore = -1;
    for (const link of links) {
      const target = new URL(link.href);
      const bodyMatch = path(target) === '/body' && path(url) === '/body';
      const samePath = path(target) === path(url);
      const childPath = target.pathname !== '/' && url.pathname.startsWith(target.pathname + '/');
      const score = bodyMatch
        ? ((target.searchParams.get('tab') || 'train') === (url.searchParams.get('tab') || 'train') ? 1000 : -1)
        : (samePath ? 1000 + target.pathname.length : (childPath ? target.pathname.length : -1));
      if (score > bestScore) { best = link; bestScore = score; }
      link.classList.remove('active');
      link.removeAttribute('aria-current');
      link.querySelector('.nav-current')?.remove();
    }
    if (best && bestScore >= 0) {
      best.classList.add('active');
      best.setAttribute('aria-current', 'page');
      const marker = document.createElement('span');
      marker.className = 'nav-current';
      marker.setAttribute('aria-hidden', 'true');
      best.append(marker);
      for (let ancestor = best.parentElement; ancestor && ancestor !== nav; ancestor = ancestor.parentElement) {
        if (ancestor.tagName === 'DETAILS') ancestor.open = true;
      }
    }
  }

  function sync(url, pageTitle) {
    if (url.origin !== location.origin) return;
    if (isAuth(url)) { location.replace(key(url)); return; }
    if (key(url) !== key(new URL(location.href))) history.replaceState(null, '', key(url));
    if (pageTitle) {
      title.textContent = pageTitle;
      pane.title = pageTitle;
      document.title = pageTitle + '｜考試智伴';
    }
    highlight(url);
    pane.removeAttribute('aria-busy');
    loading.hidden = true;
  }

  document.addEventListener('click', event => {
    const link = event.target.closest('.workspace-sidebar a[href], .workspace-topbar a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || link.download || (link.target && link.target !== '_self')) return;
    const url = new URL(link.href);
    if (url.origin !== location.origin || isAuth(url)) return;
    event.preventDefault();
    if (key(url) !== key(new URL(location.href))) history.pushState(null, '', key(url));
    pane.setAttribute('aria-busy', 'true');
    loading.hidden = false;
    navigate(url);
    highlight(url);
  });

  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== pane.contentWindow || event.data?.type !== 'workspace-page') return;
    sync(new URL(event.data.url, location.origin), event.data.title);
  });
  pane.addEventListener('load', () => {
    // Also handles authentication redirects and error pages without the pane script.
    try { sync(new URL(pane.contentWindow.location.href), pane.contentDocument.title.replace(/｜考試智伴$/, '')); }
    catch { loading.hidden = true; pane.removeAttribute('aria-busy'); }
  });
  window.addEventListener('popstate', () => {
    try {
      if (key(new URL(pane.contentWindow.location.href)) !== key(new URL(location.href))) navigate(new URL(location.href));
    } catch { navigate(new URL(location.href)); }
    highlight(new URL(location.href));
  });
  highlight(new URL(location.href));
})();
