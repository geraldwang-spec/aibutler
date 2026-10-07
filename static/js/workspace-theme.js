/* Runs in the head to restore the palette before the first paint. BODY uses only the --theme-* tokens (static/body/body.css). */
(() => {
  const key = 'aibutler.workspace.theme';
  const modes = ['violet', 'apricot', 'midnight'];
  const names = {violet: '紫藤', apricot: '暖杏', midnight: '夜幕'};
  let initial = 'violet';
  try { initial = localStorage.getItem(key) || initial; } catch (_) { /* Storage may be disabled. */ }
  function apply(mode, persist = false) {
    if (!modes.includes(mode)) mode = 'violet';
    document.documentElement.dataset.workspaceTheme = mode;
    if (persist) {
      try { localStorage.setItem(key, mode); } catch (_) { /* Current session still works. */ }
    }
    document.querySelectorAll('[data-theme-mode]').forEach(button => {
      const active = button.dataset.themeMode === mode;
      button.setAttribute('aria-pressed', String(active));
      button.classList.toggle('active', active);
    });
    const status = document.getElementById('workspace-theme-status');
    if (status) status.textContent = `目前配色：${names[mode]}`;
    document.dispatchEvent(new CustomEvent('workspace-theme-change', {detail: {mode}}));
    const frame = document.getElementById('workspace-pane');
    if (frame?.contentWindow) frame.contentWindow.postMessage({type: 'workspace-theme', mode}, location.origin);
  }
  apply(initial);
  document.addEventListener('DOMContentLoaded', () => {
    apply(document.documentElement.dataset.workspaceTheme);
    document.querySelectorAll('[data-theme-mode]').forEach(button => {
      button.addEventListener('click', () => apply(button.dataset.themeMode, true));
    });
    document.getElementById('workspace-pane')?.addEventListener('load', () => apply(document.documentElement.dataset.workspaceTheme));
  });
  window.addEventListener('storage', event => {
    if (event.key === key) apply(event.newValue);
  });
  window.addEventListener('message', event => {
    if (event.origin === location.origin && event.source === window.parent && event.data?.type === 'workspace-theme') apply(event.data.mode);
  });
})();
