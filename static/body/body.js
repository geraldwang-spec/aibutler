// 體重與訓練頁：依 JSON 狀態繪製畫面，並以 JSON 呼叫 /body/api/*
// （網站 CSP 只允許同源外部 JS，所以畫面用 DOM API 產生，不用 inline script / style）
(() => {
  const root = document.getElementById('bd');
  if (!root) return;

  const API = root.dataset.api;
  const CSRF = root.dataset.csrf;
  const $ = (id) => document.getElementById(id);
  let state = JSON.parse($('bd-initial').textContent);
  let busy = false;

  // ------------------------------------------------------------ 小工具
  const pad = (n) => String(n).padStart(2, '0');
  const mmss = (s) => pad(Math.floor(s / 60)) + ':' + pad(s % 60);
  const hms = (s) => pad(Math.floor(s / 3600)) + ':' + pad(Math.floor(s % 3600 / 60)) + ':' + pad(s % 60);
  const num = (v) => (v === null || v === undefined || v === '' ? '' : String(Number(v)));
  const int = (v) => Math.round(Number(v) || 0).toLocaleString('zh-TW');
  const pair = (p) => (p ? `${num(p.weight_kg)}×${p.reps}` : '');

  /** h('div', {class: 'x', dataset: {a: 1}, onclick}, child, ...) — 只用 textContent，不用 innerHTML */
  function h(tag, attrs, ...children) {
    const svg = ['svg', 'line', 'polyline', 'circle'].includes(tag);
    const el = svg ? document.createElementNS('http://www.w3.org/2000/svg', tag) : document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (value === null || value === undefined || value === false) return;
      if (key === 'dataset') Object.assign(el.dataset, value);
      else if (key === 'class') el.setAttribute('class', value);
      else if (key === 'text') el.textContent = value;
      else if (key in el && !svg && typeof value !== 'string') el[key] = value;
      else el.setAttribute(key, value === true ? '' : value);
    });
    children.flat().forEach((child) => {
      if (child === null || child === undefined || child === false) return;
      el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    });
    return el;
  }
  const icon = (name) => h('i', { class: `fa fa-${name}`, 'aria-hidden': 'true' });
  const chip = (text, tone) => h('span', { class: 'bd-chip' + (tone ? ` bd-chip--${tone}` : ''), text });
  const fill = (el, ...children) => { el.replaceChildren(...children.flat().filter((c) => c !== null && c !== undefined && c !== false)); };

  const store = {
    get(key) { try { return window.localStorage.getItem(key); } catch (e) { return null; } },
    set(key, value) { try { window.localStorage.setItem(key, value); } catch (e) { /* 私密模式等 */ } },
    del(key) { try { window.localStorage.removeItem(key); } catch (e) { /* ignore */ } }
  };

  // ------------------------------------------------------------ 今天要做的動作（開始前的草稿）
  // 還沒記錄任何一組的動作不在資料庫裡，先存在這台瀏覽器；開始訓練時一起送到後端檢查。
  const planKey = (d) => `bdPlan:${root.dataset.user}:${d}`;
  const libraryIds = () => new Set(state.library.map((e) => e.id));
  function getPlan(d = state.d) {
    let ids = [];
    try { ids = JSON.parse(store.get(planKey(d)) || '[]'); } catch (e) { ids = []; }
    const known = libraryIds();
    return Array.isArray(ids) ? ids.map(Number).filter((id) => known.has(id)) : [];
  }
  function setPlan(ids, d = state.d) {
    const unique = [...new Set(ids)];
    if (unique.length) store.set(planKey(d), JSON.stringify(unique)); else store.del(planKey(d));
  }
  /** 畫面上的動作清單：已有組數的（伺服器）＋ 還沒記錄的（草稿） */
  function exerciseList() {
    const w = state.workout;
    const items = w ? w.exercises.map((e) => ({ ...e })) : [];
    const seen = new Set(items.map((e) => e.id));
    const byId = new Map(state.library.map((e) => [e.id, e]));
    getPlan().forEach((id) => {
      if (!seen.has(id)) { items.push({ ...byId.get(id), done: 0, volume: 0 }); seen.add(id); }
    });
    return items;
  }
  const canStart = () => !state.is_future && !state.workout && getPlan().length > 0;

  // ------------------------------------------------------------ JSON 通訊
  function showMessage(text, kind) {
    const box = $('bd-message');
    if (!text) { box.hidden = true; return; }
    box.className = `notice ${kind || 'success'}`;
    box.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    box.textContent = text;
    box.hidden = false;
  }

  async function call(method, path, body) {
    const options = { method, headers: { Accept: 'application/json' }, credentials: 'same-origin' };
    if (method !== 'GET') {
      options.headers['Content-Type'] = 'application/json';
      options.headers['X-CSRF-Token'] = CSRF;
      options.body = JSON.stringify(body || {});
    }
    let data;
    try {
      const response = await fetch(API + path, options);
      data = await response.json().catch(() => ({ ok: false, error: `伺服器回應錯誤（${response.status}）。` }));
      if (response.status === 401) { window.location.reload(); return null; }
    } catch (e) {
      data = { ok: false, error: '無法連線，請檢查網路後再試。' };
    }
    if (!data.ok) throw new Error(data.error || data.message || '操作失敗，請再試一次。');
    return data;
  }

  /** 送出請求 → 用回傳的 state 重繪。history: 'push' | 'replace' */
  async function run(method, path, body, { history = 'replace' } = {}) {
    if (busy) return null;
    busy = true;
    root.setAttribute('aria-busy', 'true');
    try {
      const data = await call(method, path, body);
      if (!data) return null;
      showMessage(data.message || '');
      state = data.state;
      render();
      syncUrl(history);
      if (data.rest) startRest(defaultRest());
      return data;
    } catch (err) {
      showMessage(err.message, 'error');
      return null;
    } finally {
      busy = false;
      root.removeAttribute('aria-busy');
    }
  }

  const load = (d, ex, history = 'push') => {
    const query = new URLSearchParams({ d });
    if (ex) query.set('ex', ex);
    return run('GET', `/state?${query}`, null, { history });
  };

  function syncUrl(mode) {
    const url = new URL(window.location.href);
    url.searchParams.set('d', state.d);
    if (state.current) url.searchParams.set('ex', state.current.exercise_id); else url.searchParams.delete('ex');
    url.searchParams.delete('rest');
    if (url.href === window.location.href) return;
    window.history[mode === 'push' ? 'pushState' : 'replaceState'](null, '', url.pathname + url.search + url.hash);
  }

  // ------------------------------------------------------------ 繪製
  function render() {
    const focusKey = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.key : null;
    renderHeader();
    renderWeek();
    renderTabs();
    renderTrain();
    renderWeight();
    renderLog();
    restLabel();
    if (focusKey) {
      const again = root.querySelector(`[data-key="${CSS.escape(focusKey)}"]`) || root.querySelector('[data-key="next-check"]');
      if (again) again.focus();
    }
  }

  function renderHeader() {
    const [, m, d] = state.d.split('-').map(Number);
    const isToday = state.d === state.today;
    fill($('bd-date'),
      `${m} 月 ${d} 日（${state.weekday}）${isToday ? '・今天' : ''}`,
      isToday ? null : h('button', { type: 'button', class: 'bd-link', dataset: { action: 'goto', d: state.today, key: 'today' }, text: '回到今天' }));
    $('bd-prev-week').dataset.d = state.prev_week;
    $('bd-next-week').dataset.d = state.next_week;
  }

  function renderWeek() {
    fill($('bd-week'), state.week.map((x) => h('li', null,
      h('button', {
        type: 'button',
        class: 'bd-day' + (x.selected ? ' is-selected' : '') + (x.today ? ' is-today' : ''),
        dataset: { action: 'goto', d: x.d, key: `day-${x.d}` },
        'aria-current': x.selected ? 'date' : null,
        'aria-label': `${x.d}（${x.weekday}）${x.trained ? '，有訓練' : ''}`
      },
      h('span', { class: 'bd-day__w', text: x.weekday }),
      h('span', { class: 'bd-day__n', text: x.day }),
      h('span', { class: 'bd-day__tag', text: x.groups.slice(0, 2).join('・') || (x.trained ? '訓練' : '') })))));
  }

  function renderTabs() {
    const w = state.workout;
    $('bd-tab-train-label').textContent = '訓練' + (w && w.groups.length ? `・${w.groups.join('、')}` : '');
    const latest = state.weight.latest;
    fill($('bd-tabs-meta'),
      w ? (w.in_progress ? chip('訓練進行中', 'warm') : chip('已完成')) : null,
      latest ? h('span', { text: `體重 ${num(latest.weight_kg)} kg` }) : null);
  }

  let elapsedTimer = null;
  function renderTrain() {
    const panel = $('bd-panel-train');
    const w = state.workout;
    clearInterval(elapsedTimer);
    if (!w) {
      fill(panel, state.is_future
        ? h('p', { class: 'bd-empty', text: '這天還沒到，先回到今天記錄吧。' })
        : h('div', { class: 'bd-empty' },
          h('p', { text: getPlan().length
            ? `已排好 ${getPlan().length} 個動作，可以開始訓練了。`
            : '先在下方「今天要做的動作」加入動作，再開始訓練。' }),
          startButton('start')));
      return;
    }
    const elapsed = h('span', { class: 'bd-stat__value bd-mono', text: hms(w.duration_min * 60) });
    if (w.in_progress && w.started_at) {
      // 補登過去日期時，後端也是用「開始的時刻 → 現在的時刻」算時長，這裡用同樣方式
      const t = new Date(w.started_at);
      const now = new Date();
      const start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), t.getHours(), t.getMinutes()).getTime();
      const tick = () => { elapsed.textContent = hms(Math.max(0, Math.floor((Date.now() - start) / 1000))); };
      if (!Number.isNaN(start)) { tick(); elapsedTimer = setInterval(tick, 1000); }
    }
    const stat = (label, value) => h('div', { class: 'bd-stat' }, h('span', { class: 'bd-stat__label', text: label }), value);
    fill(panel, h('div', { class: 'bd-stats' },
      stat('訓練時間', elapsed),
      stat('總訓練量 kg×次', h('span', { class: 'bd-stat__value bd-mono', text: int(w.volume) })),
      stat('完成組數', h('span', { class: 'bd-stat__value bd-mono', text: w.set_count })),
      stat('訓練部位', h('span', { class: 'bd-stat__chips' },
        w.groups.length ? w.groups.map((g) => chip(g, 'teal')) : h('span', { class: 'bd-muted', text: '—' }))),
      w.in_progress ? h('div', { class: 'bd-stat bd-stat--action' },
        h('button', { type: 'button', class: 'bd-btn bd-btn--danger', dataset: { action: 'end', id: w.id, key: 'end' }, text: '結束並儲存' })) : null));
  }

  function renderWeight() {
    const { record, latest, delta, trend } = state.weight;
    fill($('bd-weight-now'),
      latest ? [
        h('p', { class: 'bd-weight__big' }, h('span', { class: 'bd-mono', text: num(latest.weight_kg) }), ' kg'),
        latest.record_date !== state.d ? h('p', { class: 'bd-muted', text: `${latest.record_date} 的紀錄` }) : null,
        delta !== null ? chip(`較 7 日前 ${delta > 0 ? '+' : ''}${delta.toFixed(1)} kg`) : null
      ] : h('p', { class: 'bd-muted', text: '尚無體重紀錄' }),
      h('a', { href: root.dataset.recordsWeight, text: '完整紀錄 →' }));

    const chart = $('bd-weight-chart');
    if (trend.length < 2) {
      fill(chart, h('p', { class: 'bd-muted', text: '記錄兩天以上就會顯示趨勢。' }));
    } else {
      const ws = trend.map((t) => t.weight_kg);
      const low = Math.min(...ws); const high = Math.max(...ws);
      const pts = ws.map((w, i) => [10 + i * (280 / (ws.length - 1)), high === low ? 36 : 10 + (high - w) / (high - low) * 50]);
      const last = pts[pts.length - 1];
      fill(chart,
        h('svg', { viewBox: '0 0 300 72', role: 'img', 'aria-label': `近期體重趨勢，${num(low)} 到 ${num(high)} kg` },
          h('line', { x1: 0, y1: 66, x2: 300, y2: 66, stroke: '#e1e9e9', 'stroke-width': 1 }),
          h('polyline', { points: pts.map((p) => p.map((v) => v.toFixed(1)).join(',')).join(' '), fill: 'none', stroke: '#e8834f', 'stroke-width': 2.5, 'stroke-linejoin': 'round' }),
          h('circle', { cx: last[0].toFixed(1), cy: last[1].toFixed(1), r: 4, fill: '#e8834f' })),
        h('p', { class: 'bd-weight__axis' },
          h('span', { text: trend[0].d.slice(5) }), h('span', { text: `${num(low)}–${num(high)} kg` }), h('span', { text: trend[trend.length - 1].d.slice(5) })));
    }

    const form = $('bd-weight-form');
    form.hidden = state.is_future;
    // 使用者正在輸入時不要覆蓋
    if (!form.contains(document.activeElement)) {
      form.elements.weight_kg.value = record ? num(record.weight_kg) : '';
      form.elements.body_fat_pct.value = record ? num(record.body_fat_pct) : '';
    }
    $('bd-weight-submit').textContent = record ? '更新' : '儲存';
  }

  function startButton(key) {
    return h('button', {
      type: 'button', class: 'bd-btn bd-btn--primary', disabled: !canStart(),
      dataset: { action: 'start', key }, title: canStart() ? null : '請先加入至少一個動作'
    }, icon('play'), ' 開始訓練');
  }

  function exerciseItem(e, cur, w) {
    const on = Boolean(cur && cur.exercise_id === e.id);
    const detail = w ? `${e.done} 組` + (e.volume ? `・${int(e.volume)} kg×次` : '') : [e.muscle_group, e.equipment].filter(Boolean).join('・');
    const text = h('span', { class: 'bd-ex__text' }, h('strong', { text: e.name }), h('small', { text: detail }));
    const pick = w
      ? h('button', {
        type: 'button', class: 'bd-ex__pick', dataset: { action: 'pick', ex: e.id, key: `ex-${e.id}` }, 'aria-current': on ? 'true' : null
      }, text, on ? chip('記錄中', 'warm') : icon('chevron-right'))
      : h('div', { class: 'bd-ex__pick' }, text);
    // 還沒記錄任何一組的動作才能移除
    const remove = e.done ? null : h('button', {
      type: 'button', class: 'bd-ex__remove', dataset: { action: 'remove-plan', ex: e.id, key: `rm-${e.id}` }, 'aria-label': `移除 ${e.name}`
    }, icon('times'));
    return h('div', { class: 'bd-ex' + (on ? ' is-current' : '') }, pick, remove);
  }

  function renderLog() {
    const wrap = $('bd-log-wrap');
    const w = state.workout;
    if (!w && state.is_future) { fill(wrap); return; }
    const cur = state.current;
    const items = exerciseList();

    const list = h('div', { class: 'bd-exlist' },
      items.map((e) => exerciseItem(e, cur, w)),
      state.library.length ? addExerciseForm() : h('p', { class: 'bd-empty bd-empty--small' },
        '動作庫還是空的，先到 ', h('a', { href: root.dataset.recordsExercises, text: '運動動作庫' }), ' 新增動作。'));

    if (!w) {
      fill(wrap,
        h('div', { class: 'bd-section-head', id: 'bd-log' },
          h('h2', { text: '今天要做的動作' }),
          h('p', { text: '先加好動作，再開始訓練；開始後可以隨時再加。' })),
        h('div', { class: 'bd-log' }, list,
          h('section', { class: 'bd-card bd-current bd-ready', 'aria-label': '開始訓練' },
            items.length
              ? h('p', { text: `已排好 ${items.length} 個動作：${items.map((e) => e.name).join('、')}` })
              : h('p', { class: 'bd-muted', text: '還沒有動作。從左邊的「加入動作」選擇今天要練的項目。' }),
            startButton('start-plan'))));
      return;
    }

    fill(wrap,
      h('div', { class: 'bd-section-head', id: 'bd-log' },
        h('h2', { text: '逐組紀錄' }),
        h('p', { text: w.in_progress ? '點 ✓ 完成一組，會自動開始休息計時；再點一次可取消。' : '這次訓練已結束，仍可補登或取消組數。' })),
      h('div', { class: 'bd-log' }, list, currentCard(cur, w)));
  }

  function addExerciseForm() {
    const groups = new Map();
    state.library.forEach((e) => {
      const key = e.muscle_group || '其他';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(e);
    });
    return h('form', { class: 'bd-addex', dataset: { form: 'add-exercise' } },
      h('label', { class: 'bd-sr', for: 'bd-addex-select', text: '加入動作' }),
      h('select', { id: 'bd-addex-select', name: 'ex', required: true },
        h('option', { value: '', text: '＋ 加入動作…' }),
        [...groups].map(([label, items]) => h('optgroup', { label },
          items.map((e) => h('option', { value: e.id, text: e.name }))))),
      h('button', { class: 'bd-btn', dataset: { key: 'add-exercise' }, text: '加入' }));
  }

  function currentCard(cur, w) {
    if (!cur) {
      return h('section', { class: 'bd-card bd-current', 'aria-label': '逐組輸入' },
        h('p', { class: 'bd-empty', text: '從左邊選一個動作，或用「加入動作」開始第一組。' }));
    }
    const meta = [cur.muscle_group, cur.equipment].filter(Boolean);
    if (cur.best) meta.push(`上次最佳 ${pair(cur.best)}`);
    const n = cur.next.set_no;
    return h('section', { class: 'bd-card bd-current', 'aria-label': '逐組輸入' },
      h('header', { class: 'bd-current__head' }, h('h3', { text: cur.name }), h('p', { class: 'bd-muted', text: meta.join('・') })),
      h('div', { class: 'bd-grid bd-grid--head', 'aria-hidden': 'true' },
        ['組', '上次', 'kg', '次', 'RPE', ''].map((t) => h('span', { text: t }))),
      cur.sets.map((s) => h('div', { class: 'bd-grid bd-row is-done' },
        h('span', { class: 'bd-row__no', text: s.set_no }),
        h('span', { class: 'bd-row__last', text: pair(s.last) || '—' }),
        h('span', { class: 'bd-row__val', text: num(s.weight_kg) }),
        h('span', { class: 'bd-row__val', text: s.reps }),
        h('span', { class: 'bd-row__val bd-row__val--sm', text: s.rpe || '—' }),
        h('button', {
          type: 'button', class: 'bd-check is-done', title: '取消完成',
          dataset: { action: 'delete-set', id: s.id, key: `del-${s.id}` }, 'aria-label': `取消第 ${s.set_no} 組`
        }, icon('check')))),
      h('form', { class: 'bd-grid bd-row is-next', dataset: { form: 'add-set', workout: w.id, exercise: cur.exercise_id } },
        h('span', { class: 'bd-row__no', text: n }),
        h('span', { class: 'bd-row__last', text: pair(cur.next.last) || '—' }),
        h('input', { class: 'bd-input', type: 'number', name: 'weight_kg', step: 'any', min: 0, max: 1000, inputmode: 'decimal', required: true, value: num(cur.next.weight_kg), 'aria-label': `第 ${n} 組重量 kg` }),
        h('input', { class: 'bd-input', type: 'number', name: 'reps', step: 1, min: 1, max: 10000, inputmode: 'numeric', required: true, value: num(cur.next.reps), 'aria-label': `第 ${n} 組次數` }),
        h('input', { class: 'bd-input bd-input--sm', type: 'number', name: 'rpe', step: 1, min: 1, max: 10, inputmode: 'numeric', placeholder: '—', 'aria-label': `第 ${n} 組 RPE（選填）` }),
        h('button', { class: 'bd-check', dataset: { key: 'next-check' }, 'aria-label': `完成第 ${n} 組` }, icon('check'))));
  }

  // ------------------------------------------------------------ 事件
  root.addEventListener('click', (event) => {
    const target = event.target.closest('[data-action]');
    if (!target || !root.contains(target)) return;
    const { action, d, id, ex } = target.dataset;
    if (action === 'goto') load(d);
    else if (action === 'pick') load(state.d, ex);
    else if (action === 'start') {
      if (!canStart()) { showMessage('請先加入至少一個動作，再開始訓練。', 'error'); return; }
      run('POST', '/workouts', { d: state.d, exercise_ids: getPlan() }, { history: 'replace' });
    } else if (action === 'remove-plan') {
      const id = Number(ex);
      setPlan(getPlan().filter((x) => x !== id));
      if (state.current && state.current.exercise_id === id) load(state.d, null, 'replace');
      else render();
    }
    else if (action === 'end') {
      if (window.confirm('結束並儲存這次訓練？')) {
        const d = state.d;
        run('POST', `/workouts/${id}/end`).then((data) => {
          if (data && data.state.workout) setPlan([], d);   // 已儲存 → 清掉草稿；若因沒有組數被取消，保留清單方便重來
          if (data) render();
        });
      }
    } else if (action === 'delete-set') run('POST', `/sets/${id}/delete`);
  });

  const blank = (v) => (v.trim() === '' ? null : v.trim());
  root.addEventListener('submit', (event) => {
    const form = event.target;
    event.preventDefault();
    if (form.id === 'bd-weight-form') {
      run('POST', '/weight', {
        d: state.d,
        weight_kg: blank(form.elements.weight_kg.value),
        body_fat_pct: blank(form.elements.body_fat_pct.value),
        ex: state.current ? state.current.exercise_id : null
      });
    } else if (form.dataset.form === 'add-set') {
      if (!form.reportValidity()) return;
      const data = {
        exercise_id: Number(form.dataset.exercise),
        weight_kg: blank(form.elements.weight_kg.value),
        reps: blank(form.elements.reps.value),
        rpe: blank(form.elements.rpe.value)
      };
      run('POST', `/workouts/${form.dataset.workout}/sets`, data);
    } else if (form.dataset.form === 'add-exercise') {
      const ex = Number(form.elements.ex.value);
      if (!ex) return;
      setPlan([...getPlan(), ex]);
      if (state.workout) load(state.d, ex); else render();
    }
  });

  window.addEventListener('popstate', () => {
    const params = new URLSearchParams(window.location.search);
    load(params.get('d') || state.today, params.get('ex'), 'none');
  });

  // ------------------------------------------------------------ 頁籤
  const tabs = Array.from(root.querySelectorAll('[data-tab-target]'));
  const showTab = (name) => {
    tabs.forEach((tab) => {
      const on = tab.dataset.tabTarget === name;
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
      $(tab.getAttribute('aria-controls')).hidden = !on;
    });
  };
  tabs.forEach((tab, i) => {
    tab.addEventListener('click', () => showTab(tab.dataset.tabTarget));
    tab.addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
      const next = tabs[(i + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
      showTab(next.dataset.tabTarget);
      next.focus();
    });
  });

  // ------------------------------------------------------------ 組間休息計時
  const KEY = 'bdRest';            // {end, total}
  const DEFAULT_KEY = 'bdRestDefault';
  const bar = $('bd-rest');
  let restTimer = null;
  const defaultRest = () => {
    const value = parseInt(store.get(DEFAULT_KEY), 10);
    return value >= 10 && value <= 600 ? value : 90;
  };
  const readRest = () => { try { return JSON.parse(store.get(KEY) || 'null'); } catch (e) { return null; } };
  const stopRest = (finished) => {
    clearInterval(restTimer);
    restTimer = null;
    store.del(KEY);
    bar.hidden = true;
    if (finished && navigator.vibrate) navigator.vibrate(200);
  };
  const runRest = () => {
    const rest = readRest();
    if (!rest || rest.end <= Date.now()) { stopRest(false); return; }
    restLabel();
    bar.hidden = false;
    clearInterval(restTimer);
    const tick = () => {
      const now = readRest();
      if (!now) { stopRest(false); return; }
      const left = Math.ceil((now.end - Date.now()) / 1000);
      if (left <= 0) { stopRest(true); return; }
      $('bd-rest-time').textContent = mmss(left);
      $('bd-rest-bar').max = Math.max(now.total, 1);
      $('bd-rest-bar').value = left;
    };
    tick();
    restTimer = setInterval(tick, 250);
  };
  function restLabel() {
    const cur = state.current;
    $('bd-rest-label').textContent = '休息中' + (cur ? `・下一組：${cur.name} 第 ${cur.next.set_no} 組` : '');
  }
  function startRest(seconds) {
    store.set(KEY, JSON.stringify({ end: Date.now() + seconds * 1000, total: seconds }));
    runRest();
  }
  bar.querySelectorAll('[data-rest-add]').forEach((button) => {
    button.addEventListener('click', () => {
      const rest = readRest();
      if (!rest) return;
      const total = Math.min(600, Math.max(10, rest.total + parseInt(button.dataset.restAdd, 10)));
      rest.end += (total - rest.total) * 1000;
      rest.total = total;
      store.set(KEY, JSON.stringify(rest));
      store.set(DEFAULT_KEY, String(total));   // 記住偏好的休息秒數
      runRest();
    });
  });
  bar.querySelector('[data-rest-skip]').addEventListener('click', () => stopRest(false));

  // ------------------------------------------------------------ 啟動
  render();
  showTab(root.dataset.tab === 'weight' ? 'weight' : 'train');
  syncUrl('replace');
  runRest();
})();
