(function () {
  'use strict';
  var form = document.getElementById('question-import-form');
  if (!form) return;
  var editor = document.getElementById('question-editor');
  var numbers = document.getElementById('editor-lines');
  var format = document.getElementById('editor-format');
  var file = form.querySelector('input[type=file]');
  var subject = document.getElementById('import-subject');
  var createSubject = document.getElementById('import-create-subject');
  var newSubject = document.getElementById('import-new-subject');
  var subjectStatus = document.getElementById('import-subject-status');
  var manageSubject = document.getElementById('import-manage-subject');
  var creatingSubject = false;
  function syncSubjectLink() {
    if (!manageSubject) return;
    var url = new URL(manageSubject.dataset.url, window.location.origin);
    if (subject.value) url.searchParams.set('subject_id', subject.value);
    manageSubject.href = url.pathname + url.search;
  }
  subject.addEventListener('change', syncSubjectLink);
  syncSubjectLink();
  form.addEventListener('submit', function (event) {
    if (creatingSubject) {
      event.preventDefault();
      subjectStatus.textContent = '科目正在儲存，完成後即可匯入。';
    }
  });
  createSubject.addEventListener('click', async function () {
    if (creatingSubject) return;
    var name = newSubject.value.trim();
    if (!name || name.length > 80) {
      subjectStatus.textContent = '請輸入 1–80 字的科目名稱。';
      subjectStatus.setAttribute('role', 'alert');
      newSubject.focus(); return;
    }
    creatingSubject = true;
    createSubject.disabled = true;
    newSubject.disabled = true;
    subjectStatus.setAttribute('role', 'status');
    subjectStatus.textContent = '正在建立科目…';
    try {
      var response = await fetch(createSubject.dataset.url, {
        method: 'POST', credentials: 'same-origin', headers: {'Accept': 'application/json'},
        body: new URLSearchParams({subject_name: name, csrf_token: form.querySelector('input[name=csrf_token]').value})
      });
      if (response.redirected) throw new Error('登入已過期，請另開登入頁重新登入，再回到這裡。');
      if (!response.headers.get('Content-Type')?.includes('application/json')) {
        throw new Error(response.status === 503 ? '目前資料庫暫時無法寫入，請稍後再試。' : '頁面或登入狀態已過期，請保留題目內容後重新整理。');
      }
      var result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.message || '無法建立科目，請稍後再試。');
      var id = String(result.subject.id);
      var option = Array.from(subject.options).find(function (item) { return item.value === id; });
      if (!option) {
        option = new Option(result.subject.subject_name, id);
        subject.add(option);
      }
      subject.value = id;
      subject.dispatchEvent(new Event('change', {bubbles: true}));
      newSubject.value = '';
      subjectStatus.textContent = result.message;
    } catch (error) {
      subjectStatus.setAttribute('role', 'alert');
      subjectStatus.textContent = error.message || '連線失敗，請稍後再試。';
    } finally {
      creatingSubject = false;
      createSubject.disabled = false;
      newSubject.disabled = false;
    }
  });
  newSubject.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') {
      event.preventDefault();
      if (!createSubject.disabled) createSubject.click();
    }
  });
  function syncMode() {
    var textMode = form.querySelector('input[name=source_mode]:checked').value === 'text';
    document.getElementById('import-file-pane').hidden = textMode;
    document.getElementById('import-text-pane').hidden = !textMode;
    file.required = !textMode;
    file.disabled = textMode;
    editor.required = textMode;
  }
  function syncEditor() {
    var count = editor.value.split('\n').length;
    numbers.textContent = Array.from({length: count}, function (_, i) { return i + 1; }).join('\n');
    document.getElementById('editor-count').textContent = count + ' 行 · ' + editor.value.length + ' 字元';
    numbers.scrollTop = editor.scrollTop;
  }
  form.querySelectorAll('input[name=source_mode]').forEach(function (radio) { radio.addEventListener('change', syncMode); });
  editor.addEventListener('input', syncEditor);
  editor.addEventListener('scroll', function () { numbers.scrollTop = editor.scrollTop; });
  editor.addEventListener('keydown', function (event) {
    if (event.key === 'Tab' && !event.shiftKey) {
      event.preventDefault();
      editor.setRangeText('    ', editor.selectionStart, editor.selectionEnd, 'end');
      syncEditor();
    }
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); form.requestSubmit(); }
  });
  document.getElementById('editor-example').addEventListener('click', function () {
    if (editor.value.trim() && !window.confirm('載入範例將取代編輯區內容，是否繼續？')) return;
    editor.value = format.value === 'csv'
      ? 'chapter_name,q_type,content,answer_key,explanation,difficulty,option_A,option_B,option_C,option_D\nPython 入門,單選,Python 中哪個值是整數？,A,12 是整數。,1,12,"""12""",12.5,True\n'
      : '1. 單選 Python 中哪個值是整數？\nA. 12\nB. "12"\nC. 12.5\nD. True\n答案：A\n解析：12 是整數。\n\n2. 是非 Python 的串列可以包含多個元素。\n答案：是\n解析：串列用來存放一組元素。\n\n3. 填空 Python 查詢串列長度使用哪個函式？\n答案：len\n解析：len 回傳容器的元素數量。';
    syncEditor(); editor.focus();
  });
  document.getElementById('editor-clear').addEventListener('click', function () {
    if (editor.value && !window.confirm('確定清空尚未匯入的文字？')) return;
    editor.value = ''; syncEditor(); editor.focus();
  });
  syncMode(); syncEditor();
})();
