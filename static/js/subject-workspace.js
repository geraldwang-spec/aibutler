(() => {
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
      if (event.target.closest('button, input, select, textarea')) { event.preventDefault(); return; }
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
      status.textContent = '';
    });
  }
  for (const zone of [...chapters, ...document.querySelectorAll('[data-drop-position]'), ...folders]) {
    zone.addEventListener('dragover', event => {
      if (!dragged || zone === dragged || !root) return;
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
  document.getElementById('chapter-search')?.addEventListener('input', event => {
    const query = event.target.value.trim().toLocaleLowerCase();
    const visible = new Set();
    for (const chapter of chapters) {
      if (chapter.dataset.chapterName.toLocaleLowerCase().includes(query)) {
        visible.add(chapter.dataset.chapterId);
        for (const ancestor of chapter.dataset.ancestors.split(' ').filter(Boolean)) visible.add(ancestor);
      }
    }
    for (const chapter of chapters) chapter.hidden = !visible.has(chapter.dataset.chapterId);
    document.getElementById('chapter-search-empty').hidden = visible.size > 0;
  });
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
})();
