(() => {
  if (window.parent === window) return;
  const notify = () => window.parent.postMessage({
    type: 'workspace-page', url: location.pathname + location.search + location.hash,
    title: document.title.replace(/｜考試智伴$/, '')
  }, location.origin);
  notify();
  window.addEventListener('pageshow', notify);
  window.addEventListener('hashchange', notify);
  window.addEventListener('popstate', notify);
  // BODY changes tabs/date using History API. Observe those changes here,
  // without editing its script or affecting the original history operation.
  for (const method of ['pushState', 'replaceState']) {
    const original = history[method];
    history[method] = function (...args) {
      const result = original.apply(this, args);
      notify();
      return result;
    };
  }
})();
