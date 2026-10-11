(() => {
 const collapsedBySubject = new Map();
 function initialize() {
  const workspace = document.querySelector('.subject-workspace');
  if (!workspace) return;
  document.querySelectorAll('[data-open-details]').forEach(button => {
    button.addEventListener('click', () => {
      const panel = document.getElementById(button.dataset.openDetails);
      if (!panel) return;
      panel.open = true;
      panel.querySelector('input:not([type="hidden"])')?.focus();
    });
  });
  document.querySelectorAll('.directory-more').forEach(menu => menu.addEventListener('toggle', () => {
    if (menu.open) document.querySelectorAll('.directory-more').forEach(other => { if (other !== menu) other.open = false; });
  }));
  const folders = [...document.querySelectorAll('[data-subject-name]')];
  document.getElementById('subject-search')?.addEventListener('input', event => {
    const query = event.target.value.trim().toLocaleLowerCase();
    for (const folder of folders) folder.hidden = !folder.dataset.subjectName.toLocaleLowerCase().includes(query);
    document.getElementById('subject-search-empty').hidden = folders.some(folder => !folder.hidden);
  });
  const chapters = [...document.querySelectorAll('[data-chapter-id]')];
  const root = document.querySelector('[data-organize-url]');
  const status = document.getElementById('chapter-drag-status');
  let dragged = null;
  const clearDrop = () => document.querySelectorAll('.chapter-drop-active').forEach(node => node.classList.remove('chapter-drop-active'));
  for (const chapter of chapters) {
    for (const link of chapter.querySelectorAll('a')) link.draggable = false;
    chapter.addEventListener('dragstart', event => {
      if (event.target.closest('button, input, select, textarea, summary, a')) { event.preventDefault(); return; }
      dragged = chapter;
      event.dataTransfer.setData('application/x-study-chapter', chapter.dataset.chapterId);
      event.dataTransfer.effectAllowed = 'move';
      chapter.classList.add('chapter-dragging');
      document.querySelector('.subject-workspace').classList.add('is-organizing');
      status.textContent = '拖到另一個章節可收為子章節；拖到科目資料夾可移動空章節。';
    });
    chapter.addEventListener('dragend', () => {
      chapter.classList.remove('chapter-dragging');
      document.querySelector('.subject-workspace').classList.remove('is-organizing');
      clearDrop();
      dragged = null;
      if (!window.recordsWorkspace?.busy) status.textContent = '';
    });
  }
  for (const zone of [...chapters, ...document.querySelectorAll('[data-drop-position]'), ...folders]) {
    zone.addEventListener('dragover', event => {
      if (!dragged || zone === dragged || !root || window.recordsWorkspace?.busy) return;
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = 'move';
      clearDrop();
      zone.classList.add('chapter-drop-active');
    });
    zone.addEventListener('dragleave', event => {
      if (!zone.contains(event.relatedTarget)) zone.classList.remove('chapter-drop-active');
    });
    zone.addEventListener('drop', event => {
      if (!dragged || zone === dragged || !root) return;
      event.preventDefault();
      event.stopPropagation();
      const target = zone.closest('[data-chapter-id]');
      const folder = zone.closest('[data-subject-id]');
      if (target === dragged) return;
      const fields = {
        csrf_token: document.querySelector('input[name="csrf_token"]').value,
        action: 'move', chapter_id: dragged.dataset.chapterId,
        position: folder ? 'root' : (zone.dataset.dropPosition || 'inside'),
        target_id: target?.dataset.chapterId || '',
        destination_subject_id: folder?.dataset.subjectId || root.dataset.currentSubject
      };
      if (window.recordsWorkspace) {
        clearDrop();
        document.querySelector('.subject-workspace').classList.remove('is-organizing');
        window.recordsWorkspace.update(root.dataset.organizeUrl, {method: 'POST', body: new URLSearchParams(fields), preserve: true});
        return;
      }
      const form = document.createElement('form');
      form.method = 'post';
      form.action = root.dataset.organizeUrl;
      for (const [name, value] of Object.entries(fields)) {
        const input = document.createElement('input');
        input.type = 'hidden'; input.name = name; input.value = value;
        form.append(input);
      }
      document.body.append(form);
      status.textContent = '正在儲存整理位置…';
      form.submit();
    });
  }
  const subjectKey = workspace.dataset.selectedSubject;
  const collapsed = collapsedBySubject.get(subjectKey) || new Set();
  collapsedBySubject.set(subjectKey, collapsed);
  const search = document.getElementById('chapter-search');
  const toggles = [...document.querySelectorAll('[data-collapse-chapter]')];
  function updateTree() {
    const query = (search?.value || '').trim().toLocaleLowerCase();
    const visible = new Set();
    let matches = 0;
    for (const chapter of chapters) {
      if (chapter.dataset.chapterName.toLocaleLowerCase().includes(query)) {
        matches++;
        visible.add(chapter.dataset.chapterId);
        for (const ancestor of chapter.dataset.ancestors.split(' ').filter(Boolean)) visible.add(ancestor);
      }
    }
    for (const chapter of chapters) {
      const folded = chapter.dataset.ancestors.split(' ').some(id => collapsed.has(id));
      chapter.hidden = query ? !visible.has(chapter.dataset.chapterId) : folded;
    }
    for (const toggle of toggles) {
      const open = Boolean(query) || !collapsed.has(toggle.dataset.collapseChapter);
      toggle.setAttribute('aria-expanded', String(open));
      toggle.textContent = open ? '▾' : '▸';
      const name = toggle.closest('[data-chapter-id]').dataset.chapterName;
      toggle.setAttribute('aria-label', (open ? '收合 ' : '展開 ') + name + ' 的子章節');
    }
    const empty = document.getElementById('chapter-search-empty');
    if (empty) empty.hidden = !query || matches > 0;
    const count = document.getElementById('chapter-result-count');
    if (count) count.textContent = query ? `找到 ${matches} 個章節（保留上層位置）` : `${chapters.length} 個章節`;
  }
  search?.addEventListener('input', updateTree);
  for (const toggle of toggles) toggle.addEventListener('click', () => {
    if (search?.value.trim()) search.value = '';
    const id = toggle.dataset.collapseChapter;
    if (collapsed.has(id)) collapsed.delete(id); else collapsed.add(id);
    updateTree();
  });
  document.getElementById('chapter-expand-all')?.addEventListener('click', () => { collapsed.clear(); if (search) search.value = ''; updateTree(); });
  document.getElementById('chapter-collapse-all')?.addEventListener('click', () => { toggles.forEach(toggle => collapsed.add(toggle.dataset.collapseChapter)); if (search) search.value = ''; updateTree(); });
  updateTree();
  // Parent options belong to the displayed subject; do not submit stale parents
  // when selecting a different destination subject for an empty chapter.
  const subject = document.getElementById('subject_id');
  const parent = document.getElementById('parent_chapter_id');
  if (subject && parent) {
    const original = subject.value;
    subject.addEventListener('change', () => {
      if (subject.value !== original) parent.value = '';
      for (const option of parent.options) if (option.value) option.disabled = subject.value !== original;
    });
  }
 }
 initialize();
 document.addEventListener('records-workspace-updated', initialize);
 document.addEventListener('click', event => {
  document.querySelectorAll('.directory-more[open]').forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
 });
})();
