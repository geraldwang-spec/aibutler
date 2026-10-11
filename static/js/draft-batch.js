(() => {
  const form = document.getElementById('draft-bulk-form');
  if (!form) return;
  const list = document.getElementById('draft-review-list');
  const all = document.getElementById('draft-select-all');
  const selectedButton = document.getElementById('draft-process-selected');
  const allButton = document.getElementById('draft-process-all');
  const status = document.getElementById('draft-bulk-status');
  let busy = false;
  const cards = () => [...list.querySelectorAll('[data-draft-id]')];
  const checked = card => card.querySelector('[name="draft_ids"]').checked;
  function sync() {
    const rows = cards(), count = rows.filter(checked).length;
    document.getElementById('draft-total').textContent = `${rows.length} 題`;
    document.getElementById('draft-selected-count').textContent = `已選 ${count} 題`;
    allButton.textContent = `處理全部 ${rows.length} 題`;
    selectedButton.disabled = busy || !count;
    allButton.disabled = busy || !rows.length;
    all.disabled = busy || !rows.length;
    all.checked = !!rows.length && count === rows.length;
    all.indeterminate = count > 0 && count < rows.length;
    document.getElementById('draft-empty').hidden = !!rows.length;
    rows.forEach(card => card.classList.toggle('is-bulk-selected', checked(card)));
  }
  list.addEventListener('change', sync);
  all.addEventListener('change', () => {
    const select = all.checked;
    cards().forEach(card => {
      const input = card.querySelector('[name="draft_ids"]');
      input.checked = select;
      input.dispatchEvent(new Event('change', {bubbles: true}));
    });
    sync();
  });
  function message(text, error = false) {
    status.hidden = false;
    status.textContent = text;
    status.classList.toggle('error', error);
  }
  function updatePreview(card, data) {
    const editor = card.querySelector('[data-draft-editor]');
    for (const key of ['content', 'answer_key', 'explanation']) {
      card.querySelector(`[data-preview="${key}"]`).textContent = data[key] || '';
      editor.elements.namedItem(key).value = data[key] || '';
    }
    editor.elements.namedItem('chapter_id').value = String(data.chapter_id);
    card.querySelector('[data-preview="chapter"]').textContent = editor.elements.namedItem('chapter_id').selectedOptions[0].textContent;
    card.querySelector('.ui-preview-text').textContent = data.content.length > 110 ? data.content.slice(0, 107) + '…' : data.content;
    const options = card.querySelector('[data-preview="options"]');
    options.replaceChildren();
    for (const label of 'ABCD') {
      editor.elements.namedItem('option_' + label).value = data.options[label] || '';
      if (data.options[label]) {
        const p = document.createElement('p');
        p.textContent = `${label}. ${data.options[label]}`;
        options.append(p);
      }
    }
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    const action = form.elements.namedItem('action').value;
    const rows = cards().filter(card => event.submitter?.value === 'all' || checked(card));
    if (!rows.length) return message('請先勾選草稿。', true);
    const verbs = {approve: '核准加入題庫', reject: '退回草稿', save: '儲存修正'};
    if (action !== 'save' && !window.confirm(`確定${verbs[action]}這 ${rows.length} 題？`)) return;
    const payload = new FormData();
    payload.set('csrf_token', form.elements.namedItem('csrf_token').value);
    payload.set('action', action);
    const edits = {};
    rows.forEach(card => {
      const id = card.dataset.draftId;
      payload.append('draft_ids', id);
      edits[id] = Object.fromEntries([...new FormData(card.querySelector('[data-draft-editor]'))].filter(([key]) => !['csrf_token', 'action'].includes(key)));
    });
    payload.set('edits', JSON.stringify(edits));
    busy = true;
    const controls = [...list.querySelectorAll('input,textarea,select,button'), ...form.querySelectorAll('input,select,button')];
    const prior = controls.map(control => control.disabled);
    controls.forEach(control => control.disabled = true);
    message(`正在${verbs[action]} ${rows.length} 題…`);
    try {
      // Controls named "action" shadow HTMLFormElement.action; read the HTML attribute.
      const endpoint = form.getAttribute('action');
      if (!endpoint) throw new Error('草稿處理網址未設定。');
      const response = await fetch(endpoint, {method: 'POST', body: payload, headers: {'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json'}});
      if (response.redirected && /\/login(?:\/|$)/.test(new URL(response.url).pathname)) throw new Error('登入已到期，請重新登入後確認處理結果。');
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error(response.status >= 500 ? `草稿處理或結果讀取失敗（HTTP ${response.status}），請重新整理確認處理結果。` : response.status === 404 ? '找不到草稿處理端點（HTTP 404），請重新整理載入新版頁面。' : '頁面驗證失敗，請重新整理後確認處理結果。');
      const data = await response.json();
      if (!response.ok) {
        (data.errors || []).forEach(item => {
          const card = cards().find(row => row.dataset.draftId === String(item.draft_id));
          if (card) card.querySelector('details').open = true;
        });
        throw new Error(data.message || '批次處理失敗。');
      }
      const processed = new Set(data.processed.map(String)), skipped = new Set(data.skipped.map(String));
      cards().forEach(card => {
        if (skipped.has(card.dataset.draftId) || (action !== 'save' && processed.has(card.dataset.draftId))) card.remove();
      });
      (data.drafts || []).forEach(draft => {
        const card = cards().find(row => row.dataset.draftId === String(draft.id));
        if (card) updatePreview(card, draft);
      });
      // Maintain the no-JavaScript fallback snapshot after an asynchronous update.
      form.querySelectorAll('[name="all_draft_ids"]').forEach(input => {
        if (!cards().some(card => card.dataset.draftId === input.value)) input.remove();
      });
      message(data.message);
    } catch (error) {
      message(error.message + ' 若連線中斷，請先重新整理確認狀態，避免重複操作。', true);
    } finally {
      controls.forEach((control, index) => control.disabled = prior[index]);
      busy = false;
      sync();
    }
  });
  sync();
})();
