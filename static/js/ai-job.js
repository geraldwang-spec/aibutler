(() => {
  const panel = document.getElementById('ai-job');
  if (!panel) return;
  const status = document.getElementById('job-status');
  const error = document.getElementById('job-error');
  const connection = document.getElementById('job-connection');
  const retry = document.getElementById('job-refresh');
  const cancel = document.getElementById('job-cancel-form');
  let timer = null, stopped = false, polling = false;
  const controller = new AbortController();
  function schedule(failures, delay) {
    clearTimeout(timer);
    timer = setTimeout(() => poll(failures), delay);
  }
  async function poll(failures = 0) {
    if (stopped || polling) return;
    polling = true;
    retry.disabled = true;
    try {
      const response = await fetch(panel.dataset.statusUrl, {
        credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
        headers: {Accept: 'application/json'}
      });
      if (response.redirected && /\/login(?:\/|$)/.test(new URL(response.url).pathname)) throw new Error('登入已到期，請重新登入後查看原工作。');
      if (!(response.headers.get('content-type') || '').includes('application/json')) throw new Error(`無法讀取工作進度（HTTP ${response.status}）。`);
      const job = await response.json();
      if (!response.ok) throw new Error(job.error || `無法讀取工作進度（HTTP ${response.status}）。`);
      if (!['queued', 'running', 'completed', 'failed', 'cancelled'].includes(job.status)) throw new Error('工作狀態資料不完整。');
      status.textContent = job.status;
      document.getElementById('job-usage').textContent = `請求 ${job.calls} 次 · 輸入 ${job.input_tokens} / 輸出 ${job.output_tokens} tokens`;
      error.textContent = job.error || '';
      connection.textContent = '';
      retry.hidden = true;
      const pending = ['queued', 'running'].includes(job.status);
      if (cancel) cancel.hidden = !pending;
      const resume = document.getElementById('job-resume-form');
        if (resume) resume.hidden = !(['failed', 'cancelled'].includes(job.status) ||
          (job.status === 'completed' && (job.progress?.answer_failures?.length || 0) > 0));
      const progress = document.getElementById('job-progress');
      if (progress && job.progress) progress.textContent = `本機解析 ${job.progress.parsed_count || 0} 題草稿 · 答案完成 ${job.progress.completed} / ${job.progress.total} 題 · ${job.progress.stage}`;
      if (job.result?.url) {
        const destination = new URL(job.result.url, location.href);
        if (destination.origin !== location.origin) throw new Error('成果連結格式不正確。');
        const link = document.getElementById('job-result');
        link.href = destination.href;
        link.hidden = false;
        link.textContent = (job.result.message || '查看成果') + ' →';
      }
      if (pending) schedule(0, 2500);
    } catch (failure) {
      if (stopped) return;
      connection.textContent = failure.message + (failures < 3 ? ' 正在重新取得進度…' : ' 可按「重新取得進度」查詢原工作。');
      if (failures < 3) schedule(failures + 1, 2000 * (failures + 1));
      else retry.hidden = false;
    } finally {
      polling = false;
      retry.disabled = false;
    }
  }
  retry.addEventListener('click', () => { clearTimeout(timer); poll(); });
  window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); controller.abort(); });
  poll();
})();
