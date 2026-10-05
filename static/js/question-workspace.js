(function () {
  'use strict';
  var form = document.getElementById('question-import-form');
  if (!form) return;
  var editor = document.getElementById('question-editor');
  var numbers = document.getElementById('editor-lines');
  var format = document.getElementById('editor-format');
  var file = form.querySelector('input[type=file]');
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
