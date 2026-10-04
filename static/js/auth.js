document.getElementById('toggle-password')?.addEventListener('click', (event) => {
  const input = document.getElementById('password');
  const show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  event.currentTarget.textContent = show ? '隱藏' : '顯示';
  event.currentTarget.setAttribute('aria-label', show ? '隱藏密碼' : '顯示密碼');
});
document.getElementById('send-code')?.addEventListener('click', async (event) => {
  const button = event.currentTarget;
  const email = document.getElementById('email');
  const status = document.getElementById('mail-status');
  if (!email.reportValidity()) return;
  button.disabled = true;
  status.className = '';
  status.textContent = '正在發送驗證信…';
  let cooldown = false;
  try {
    const body = new URLSearchParams({email: email.value, csrf_token: document.querySelector('[name=csrf_token]').value});
    const response = await fetch(button.dataset.url, {method: 'POST', body, credentials: 'same-origin'});
    const result = await response.json();
    status.className = result.ok ? 'success' : 'error';
    status.textContent = result.message;
    if (result.ok) {
      cooldown = true;
      let seconds = result.retry_after;
      button.textContent = `${seconds} 秒後可重寄`;
      const timer = setInterval(() => {
        seconds -= 1;
        button.textContent = `${seconds} 秒後可重寄`;
        if (seconds <= 0) {
          clearInterval(timer);
          button.disabled = false;
          button.textContent = '重新發送驗證碼';
        }
      }, 1000);
    }
  } catch {
    status.className = 'error';
    status.textContent = '無法發送驗證信，請檢查網路連線後重試。';
  } finally {
    if (!cooldown) button.disabled = false;
  }
});
