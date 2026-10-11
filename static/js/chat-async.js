(() => {
  const workspace = document.getElementById('chat-workspace');
  if (!workspace) return;
  const form = document.getElementById('chat-composer');
  const question = document.getElementById('chat-question');
  const stream = document.getElementById('chat-stream');
  const waiting = document.getElementById('chat-waiting');
  const errorBox = document.getElementById('chat-error');
  const errorText = document.getElementById('chat-error-text');
  const retry = document.getElementById('chat-retry');
  const send = document.getElementById('chat-send');
  let busy = false, stopped = false, timer = null, lastQuestion = workspace.dataset.retryQuestion || '';
  let chatUrl = form.action;
  let pendingStatusUrl = workspace.dataset.pendingUrl || '';
  const controller = new AbortController();
  const scroll = () => { stream.scrollTop = stream.scrollHeight; };
  function setBusy(value) {
    busy = value;
    waiting.hidden = !value;
    send.disabled = value;
    question.disabled = value;
    form.elements.subject_id.disabled = value;
    retry.disabled = value;
    send.textContent = value ? '回覆中…' : '送出 ↑';
    stream.setAttribute('aria-busy', String(value));
    if (value) scroll();
  }
  function fail(message) {
    if (stopped) return;
    setBusy(false);
    errorText.textContent = message;
    errorBox.hidden = false;
    retry.hidden = !pendingStatusUrl && !lastQuestion;
    retry.textContent = pendingStatusUrl ? '重新取得回答' : '重試這個問題';
  }
  function append(role, text, id) {
    if (id && [...stream.querySelectorAll('[data-message-id]')].some(node => node.dataset.messageId === String(id))) return;
    const article = document.createElement('article');
    article.className = 'chat-message ' + (role === 'user' ? 'chat-user' : 'chat-assistant');
    if (id) article.dataset.messageId = id;
    const label = document.createElement('strong');
    label.textContent = role === 'user' ? '你' : '✦ AI 老師';
    const content = document.createElement('p');
    content.className = 'prewrap'; content.textContent = text;
    article.append(label, content);
    stream.insertBefore(article, waiting);
    document.getElementById('chat-welcome')?.remove();
    scroll();
    return article;
  }
  function title(text) {
    document.getElementById('chat-title').textContent = text;
    document.title = text + '｜考試智伴';
    const links = document.getElementById('chat-history-links');
    const path = new URL(chatUrl, location.href).pathname;
    let active = [...links.querySelectorAll('a')].find(link => new URL(link.href).pathname === path);
    for (const link of links.querySelectorAll('a')) link.classList.remove('active');
    if (!active) { active = document.createElement('a'); active.href = chatUrl; links.prepend(active); }
    active.textContent = text; active.title = text; active.classList.add('active');
    document.getElementById('chat-history-empty')?.remove();
    history.replaceState(null, '', path);
  }
  async function readJson(response) {
    if (response.redirected && new URL(response.url).pathname.includes('/login')) throw new Error('登入已到期，請重新登入後繼續。');
    const type = response.headers.get('content-type') || '';
    if (!type.includes('application/json')) {
      const message = response.status >= 500 ? `伺服器暫時無法讀取或處理對話（HTTP ${response.status}）。` :
        response.status === 404 ? '這個對話工作已不存在或無法存取。' : '頁面驗證失敗，請重新整理後再試。';
      throw new Error(message);
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || data.message || '對話請求失敗，請稍後再試。');
    return data;
  }
  async function poll(url, started = Date.now(), failures = 0) {
    if (stopped) return;
    try {
      const data = await readJson(await fetch(url, {headers: {'Accept': 'application/json'}, cache: 'no-store', signal: controller.signal}));
      if (data.status === 'completed') {
        if (!data.result || typeof data.result.answer !== 'string' || typeof data.result.title !== 'string') throw new Error('回覆資料格式不完整，請重新取得回答。');
        append('assistant', data.result.answer, data.result.message_id);
        title(data.result.title);
        pendingStatusUrl = ''; lastQuestion = ''; retry.hidden = true;
        setBusy(false); errorBox.hidden = true; question.focus();
        return;
      }
      if (data.status === 'failed' || data.status === 'cancelled') { pendingStatusUrl = ''; fail(data.error || '回答未完成，可以重試。'); return; }
      document.getElementById('chat-waiting-text').textContent = data.status === 'queued' ? '已收到問題，正在等候回覆…' : 'AI 老師正在回覆…';
      if (Date.now() - started > 90000) { fail('回覆等待超過 90 秒。可按「重新取得回答」查看原工作；系統不會自動重送問題。'); return; }
      timer = setTimeout(() => poll(url, started), 1000);
    } catch (error) {
      if (stopped) return;
      if (failures < 3) timer = setTimeout(() => poll(url, started, failures + 1), 2000);
      else fail(error.message + ' 可按「重新取得回答」繼續查詢；已送出的問題不會自動重送。');
    }
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    if (pendingStatusUrl) { errorBox.hidden = true; setBusy(true); poll(pendingStatusUrl); return; }
    const text = question.value.trim();
    if (!text) return;
    const body = new FormData(form);
    body.set('question', text);
    const previous = stream.querySelector('.chat-message:last-of-type');
    const repeated = previous?.classList.contains('chat-user') && previous.querySelector('p')?.textContent === text;
    const optimistic = repeated ? null : append('user', text);
    lastQuestion = text;
    errorBox.hidden = true; question.value = ''; setBusy(true);
    try {
      const data = await readJson(await fetch(form.action, {method: 'POST', body, headers: {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}, signal: controller.signal}));
      chatUrl = data.chat_url;
      form.action = chatUrl;
      if (new URL(location.href).pathname !== new URL(chatUrl, location.href).pathname) title(text.slice(0, 32));
      pendingStatusUrl = data.status_url;
      poll(pendingStatusUrl);
    } catch (error) {
      if (stopped) return;
      optimistic?.remove(); question.value = text;
      fail(error.message);
    }
  });
  question.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (!busy) form.requestSubmit(); }
  });
  retry.addEventListener('click', () => {
    if (busy) return;
    if (pendingStatusUrl) { errorBox.hidden = true; setBusy(true); poll(pendingStatusUrl); return; }
    if (!question.value.trim()) question.value = lastQuestion;
    form.requestSubmit();
  });
  for (const hint of document.querySelectorAll('[data-chat-hint]')) hint.addEventListener('click', () => { if (!busy) { question.value = hint.dataset.chatHint; question.focus(); } });
  const existing = stream.querySelector('.chat-message:last-of-type');
  if (existing?.classList.contains('chat-user')) lastQuestion = existing.querySelector('p').textContent;
  retry.hidden = !lastQuestion;
  if (pendingStatusUrl) { setBusy(true); poll(pendingStatusUrl); }
  scroll();
  window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); controller.abort(); });
})();
