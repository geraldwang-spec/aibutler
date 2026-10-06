(() => {
  const form = document.getElementById('quiz-form');
  if (!form) return;
  const finished = form.dataset.finished === '1';
  const answerKey = 'quiz-position:' + form.dataset.quizId;
  const key = finished ? 'quiz-review-position:' + form.dataset.quizId : answerKey;
  if (finished) {
    try { sessionStorage.removeItem(answerKey); } catch (_) { /* Optional persistence. */ }
  }
  const questions = [...form.querySelectorAll('.cbt-question')];
  const numbers = [...form.querySelectorAll('[data-question-target]')];
  if (!questions.length) return;
  const previous = document.getElementById('cbt-previous');
  const next = document.getElementById('cbt-next');
  let index = 0;
  try {
    const saved = Number(sessionStorage.getItem(key));
    if (Number.isInteger(saved) && saved >= 0 && saved < questions.length) index = saved;
  } catch (_) { /* Answering also works without browser storage. */ }
  const answered = question => [...question.querySelectorAll('input[name^="answer_"]')].some(input =>
    ['radio', 'checkbox'].includes(input.type) ? input.checked : !!input.value.trim());
  function sync() {
    let count = 0;
    questions.forEach((question, position) => {
      const done = finished ? question.dataset.correct === '1' : answered(question), button = numbers[position];
      if (done) count++;
      button.classList.toggle('is-answered', done);
      button.classList.toggle('is-wrong', finished && !done);
      button.classList.toggle('is-current', position === index);
      const state = finished ? (done ? '答對' : '答錯或未作答') : (done ? '已作答' : '未作答');
      button.setAttribute('aria-label', `第 ${position + 1} 題，${state}${position === index ? '，目前題目' : ''}`);
      if (position === index) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
    });
    document.getElementById('cbt-answer-count').textContent = finished
      ? `答對 ${count} 題 · 答錯／未作答 ${questions.length - count} 題`
      : `已作答 ${count} / ${questions.length} · 未作答 ${questions.length - count}`;
    return count;
  }
  function show(position, focus = true) {
    index = Math.max(0, Math.min(questions.length - 1, position));
    questions.forEach((question, n) => { question.hidden = n !== index; });
    previous.disabled = index === 0;
    next.disabled = index === questions.length - 1;
    document.getElementById('cbt-current-label').textContent = `第 ${index + 1} 題 / 共 ${questions.length} 題`;
    try { sessionStorage.setItem(key, String(index)); } catch (_) { /* Optional persistence. */ }
    sync();
    if (focus) {
      const heading = questions[index].querySelector('h2');
      heading.tabIndex = -1;
      heading.focus({preventScroll: true});
      questions[index].scrollIntoView({block: 'nearest'});
    }
  }
  previous.addEventListener('click', () => show(index - 1));
  next.addEventListener('click', () => show(index + 1));
  numbers.forEach(button => button.addEventListener('click', () => show(Number(button.dataset.questionTarget))));
  form.addEventListener('change', sync);
  form.addEventListener('input', sync);
  const nextWrong = document.getElementById('cbt-next-wrong');
  if (nextWrong) {
    nextWrong.disabled = !questions.some(question => question.dataset.correct !== '1');
    nextWrong.addEventListener('click', () => {
      for (let offset = 1; offset <= questions.length; offset++) {
        const target = (index + offset) % questions.length;
        if (questions[target].dataset.correct !== '1') { show(target); break; }
      }
    });
  }
  document.getElementById('cbt-clear')?.addEventListener('click', () => {
    questions[index].querySelectorAll('input[name^="answer_"]').forEach(input => {
      if (['radio', 'checkbox'].includes(input.type)) input.checked = false;
      else input.value = '';
      input.dispatchEvent(new Event('change', {bubbles: true}));
    });
    sync();
  });
  form.addEventListener('submit', event => {
    if (finished) { event.preventDefault(); return; }
    const count = sync();
    const missing = questions.length - count;
    const summary = `確定交卷？\n已作答 ${count} 題，未作答 ${missing} 題。` +
      (missing ? '\n未作答以答錯計分，仍可直接交卷。' : '');
    if (!window.confirm(summary)) event.preventDefault();
  });
  const elapsed = Math.max(0, Number(form.dataset.elapsedSeconds) || 0);
  const loaded = Date.now();
  function tick() {
    const seconds = elapsed + (finished ? 0 : Math.max(0, Math.floor((Date.now() - loaded) / 1000)));
    const hours = Math.floor(seconds / 3600), minutes = Math.floor(seconds / 60) % 60;
    document.getElementById('cbt-timer').textContent = [hours, minutes, seconds % 60].map(n => String(n).padStart(2, '0')).join(':');
  }
  tick();
  if (!finished) {
    let clock = setInterval(tick, 1000);
    window.addEventListener('pagehide', () => clearInterval(clock));
    window.addEventListener('pageshow', event => { if (event.persisted) { tick(); clock = setInterval(tick, 1000); } });
  }
  show(index, false);
})();
