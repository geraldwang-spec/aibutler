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

  // ------------------------------------------------------------ 今天要做的動作與每組的預計重量／次數（草稿）
  // 還沒完成的組不在資料庫裡，先存在這台瀏覽器：[{id, sets: [{kg, reps}, ...]}, ...]
  // 開始訓練時把動作清單送到後端檢查；每按一次 ✓ 才把那一組寫進 workout_sets。
  const planKey = (d) => `bdPlan:${root.dataset.user}:${d}`;
  const DEFAULT_SET_COUNT = 3;
  const libById = (id) => state.library.find((e) => e.id === id);
  const blankSet = () => ({ kg: '', reps: '' });

  /** 新加入的動作預設幾組：有上次紀錄就照上次，沒有就 3 組空白 */
  function defaultSets(id) {
    const lib = libById(id);
    if (lib && lib.last && lib.last.length) return lib.last.map((x) => ({ kg: num(x.weight_kg), reps: num(x.reps) }));
    return Array.from({ length: DEFAULT_SET_COUNT }, blankSet);
  }
  function readPlan(d = state.d) {
    let raw = [];
    try { raw = JSON.parse(store.get(planKey(d)) || '[]'); } catch (e) { raw = []; }
    if (!Array.isArray(raw)) return [];
    const seen = new Set();
    return raw
      .map((item) => (typeof item === 'number' ? { id: item, sets: defaultSets(item) } : item))   // 舊格式只有 id
      .filter((item) => item && libById(Number(item.id)) && !seen.has(Number(item.id)) && seen.add(Number(item.id)))
      .map((item) => ({
        id: Number(item.id),
        sets: Array.isArray(item.sets) ? item.sets.map((x) => ({ kg: String(x.kg ?? ''), reps: String(x.reps ?? '') })) : defaultSets(Number(item.id))
      }));
  }
  function writePlan(plan, d = state.d) {
    if (plan.length) store.set(planKey(d), JSON.stringify(plan)); else store.del(planKey(d));
  }
  const getPlan = () => readPlan().map((p) => p.id);
  const planFor = (id) => readPlan().find((p) => p.id === id) || null;
  function updatePlan(id, change) {
    const plan = readPlan();
    let entry = plan.find((p) => p.id === id);
    if (!entry) { entry = { id, sets: [] }; plan.push(entry); }
    change(entry);
    writePlan(plan);
  }
  function addToPlan(id) {
    if (!readPlan().some((p) => p.id === id)) updatePlan(id, (entry) => { entry.sets = defaultSets(id); });
  }
  function removeFromPlan(id) { writePlan(readPlan().filter((p) => p.id !== id)); }

  /** 畫面上的動作清單：已有組數的（伺服器）＋ 還沒記錄的（草稿） */
  function exerciseList() {
    const w = state.workout;
    const items = w ? w.exercises.map((e) => ({ ...e })) : [];
    const seen = new Set(items.map((e) => e.id));
    readPlan().forEach((p) => {
      if (!seen.has(p.id)) { items.push({ ...libById(p.id), done: 0, volume: 0 }); seen.add(p.id); }
    });
    return items;
  }
  let planSel = null;   // 開始前正在設定哪個動作
  const canStart = () => !state.is_future && !state.workout && getPlan().length > 0;

  // ------------------------------------------------------------ 預設休息時間（使用者可改，存在瀏覽器）
  const REST_SETTING_KEY = 'bdRestDefaultSec';
  const REST_MIN = 10, REST_MAX = 600, REST_STEP = 10;   // 每次 ±10 秒，範圍 10 秒～10 分鐘
  function restSetting() {
    const value = parseInt(store.get(REST_SETTING_KEY), 10);
    return value >= REST_MIN && value <= REST_MAX ? value : 90;
  }
  function setRestSetting(seconds) {
    const value = Math.min(REST_MAX, Math.max(REST_MIN, seconds));
    if (value === 90) store.del(REST_SETTING_KEY); else store.set(REST_SETTING_KEY, String(value));
    return value;
  }
  const restText = (s) => (s % 60 ? `${Math.floor(s / 60) ? `${Math.floor(s / 60)} 分 ` : ''}${s % 60} 秒` : `${s / 60} 分鐘`);
  function restControl() {
    const sec = restSetting();
    return h('div', { class: 'bd-restset', role: 'group', 'aria-label': '預設休息時間' },
      h('span', { class: 'bd-restset__label', text: '組間休息' }),
      h('button', {
        type: 'button', class: 'bd-restset__btn', disabled: sec <= REST_MIN,
        dataset: { action: 'rest-default', step: -REST_STEP, key: 'rest-minus' }, 'aria-label': `預設休息時間減少 ${REST_STEP} 秒`
      }, icon('minus')),
      h('output', { class: 'bd-restset__value', 'aria-live': 'polite', text: restText(sec) }),
      h('button', {
        type: 'button', class: 'bd-restset__btn', disabled: sec >= REST_MAX,
        dataset: { action: 'rest-default', step: REST_STEP, key: 'rest-plus' }, 'aria-label': `預設休息時間增加 ${REST_STEP} 秒`
      }, icon('plus')));
  }

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
    if (currentTab === 'analysis') loadReport();   // 換日期時重新分析（同一天、同期間不重複呼叫）
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
      const t = new Date(String(w.started_at).replace(' ', 'T'));   // MariaDB 回傳 'YYYY-MM-DD HH:MM:SS'，Safari 需要 T
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
    const planned = planFor(e.id);
    const plannedCount = planned ? planned.sets.length : 0;
    const on = w ? Boolean(cur && cur.exercise_id === e.id) : planSel === e.id;
    const detail = w
      ? `${e.done}${plannedCount > e.done ? ` / ${plannedCount}` : ''} 組` + (e.volume ? `・${int(e.volume)} kg×次` : '')
      : `${plannedCount} 組・` + [e.muscle_group, e.equipment].filter(Boolean).join('・');
    const text = h('span', { class: 'bd-ex__text' }, h('strong', { text: e.name }), h('small', { text: detail }));
    const pick = h('button', {
      type: 'button', class: 'bd-ex__pick', 'aria-current': on ? 'true' : null,
      dataset: { action: w ? 'pick' : 'plan-pick', ex: e.id, key: `ex-${e.id}` }
    }, text, on ? chip(w ? '記錄中' : '設定中', 'warm') : icon('chevron-right'));
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
      state.library.length && !state.is_future ? quickPanel() : null,
      items.map((e) => exerciseItem(e, cur, w)),
      state.library.length ? addExerciseForm() : h('p', { class: 'bd-empty bd-empty--small' },
        '動作庫還是空的，先到 ', h('a', { href: root.dataset.recordsExercises, text: '運動動作庫' }), ' 新增動作。'));

    if (!w) {
      fill(wrap,
        h('div', { class: 'bd-section-head', id: 'bd-log' },
          h('div', null, h('h2', { text: '今天要做的動作' }),
            h('p', { text: '先加好動作，再開始訓練；開始後可以隨時再加。' })),
          restControl()),
        h('div', { class: 'bd-log' }, list, planCard(items)));
      return;
    }

    fill(wrap,
      h('div', { class: 'bd-section-head', id: 'bd-log' },
        h('div', null, h('h2', { text: '逐組紀錄' }),
          h('p', { text: w.in_progress ? '點 ✓ 完成一組，會自動開始休息計時；再點一次可取消。' : '這次訓練已結束，仍可補登或取消組數。' })),
        restControl()),
      h('div', { class: 'bd-log' }, list, currentCard(cur, w)));
  }

  // ------------------------------------------------------------ 分析（數字都由後端程式計算）
  const report = { period: 'week', key: null, data: null, busy: false };
  const MUSCLES = ['胸', '背', '腿', '肩', '手臂', '核心'];
  const fmtDate = (iso) => { const [, m, d] = iso.split('-').map(Number); return `${m}/${d}`; };
  // 期間還沒結束時，跟上一期整段比較會偏低，所以不上顏色，避免看起來像退步
  const delta = (pct, neutral) => (pct === null || pct === undefined ? null
    : h('span', { class: 'bd-delta ' + (neutral ? '' : pct > 0 ? 'is-up' : pct < 0 ? 'is-down' : ''), text: `${pct > 0 ? '+' : ''}${pct}%` }));

  async function loadReport(force) {
    const key = `${report.period}:${state.d}`;
    if (!force && (report.busy || report.key === key)) return;
    report.busy = true; report.key = key;
    fill($('bd-report'), h('p', { class: 'bd-muted', text: '分析中…' }));
    try {
      const data = await call('GET', `/report?period=${report.period}&d=${state.d}`);
      if (data && report.key === key) { report.data = data.report; renderReport(); }
    } catch (err) {
      report.key = null;
      fill($('bd-report'), h('p', { class: 'bd-empty', text: err.message }));
    } finally {
      report.busy = false;
    }
  }

  function renderReport() {
    root.querySelectorAll('[data-action="report-period"]').forEach((b) => b.setAttribute('aria-pressed', b.dataset.period === report.period ? 'true' : 'false'));
    const r = report.data;
    if (!r) return;
    const label = r.period === 'week' ? '本週' : '本月';
    $('bd-report-range').textContent = `${fmtDate(r.start)}～${fmtDate(r.end)}${r.in_progress ? `・${label}進行中，與上一${r.period === 'week' ? '週' : '月'}整段比較` : ''}`;
    const s = r.summary, p = r.previous;
    const card = (title, value, unit, pct, prev) => h('div', { class: 'bd-stat' },
      h('span', { class: 'bd-stat__label', text: title }),
      h('span', { class: 'bd-stat__value bd-mono' }, value, unit ? h('small', { text: ` ${unit}` }) : null),
      h('span', { class: 'bd-stat__sub' }, prev !== null && prev !== undefined ? `上期 ${prev}` : '　', delta(pct, r.in_progress)));
    const maxSets = Math.max(1, ...MUSCLES.map((m) => (r.by_muscle[m] || {}).sets || 0));
    const icon2 = { good: 'check-circle', warn: 'exclamation-triangle', info: 'info-circle' };

    fill($('bd-report'),
      h('div', { class: 'bd-stats bd-stats--4' },
        card('訓練次數', s.sessions, '次', r.change.sessions, p.sessions),
        card('總組數', s.sets, '組', r.change.sets, p.sets),
        card('總訓練量', int(s.volume), 'kg×次', r.change.volume, int(p.volume)),
        card('平均時長', s.avg_minutes ?? '—', s.avg_minutes ? '分' : '', null, p.avg_minutes ?? null)),

      h('section', { class: 'bd-report__block' },
        h('h3', { text: '重點發現' }),
        h('ul', { class: 'bd-findings' }, r.findings.map((f) => h('li', { class: `bd-finding is-${f.level}` },
          icon(icon2[f.level] || 'info-circle'), h('span', { text: f.text })))),
        h('p', { class: 'bd-muted', text: '以上由程式依紀錄計算；之後會加上 AI 的建議。' })),

      h('div', { class: 'bd-report__grid' },
        h('section', { class: 'bd-report__block' },
          h('h3', { text: '各部位組數' }),
          h('ul', { class: 'bd-bars' }, MUSCLES.map((m) => {
            const v = r.by_muscle[m] || { sets: 0, volume: 0 };
            const since = r.days_since[m];
            return h('li', { class: 'bd-bar' },
              h('span', { class: 'bd-bar__label', text: m }),
              h('progress', { class: 'bd-bar__meter', max: maxSets, value: v.sets, 'aria-label': `${m} ${v.sets} 組` }),
              h('span', { class: 'bd-bar__value', text: `${v.sets} 組` }),
              h('span', { class: 'bd-bar__since' + (since !== null && since >= 7 ? ' is-warn' : ''),
                text: since === null ? '沒練過' : since === 0 ? (r.in_progress ? '今天' : '期末當天') : `${since} 天前` }));
          })),
          h('p', { class: 'bd-muted', text: `推 ${r.balance.push} 組・拉 ${r.balance.pull} 組${r.balance.push_pull ? `（推／拉 ${r.balance.push_pull}）` : ''}；上半身 ${r.balance.upper} 組・下半身 ${r.balance.lower} 組` })),

        h('section', { class: 'bd-report__block' },
          h('h3', { text: '動作進度' }),
          r.progress.length ? h('div', { class: 'bd-table-wrap' }, h('table', { class: 'bd-table' },
            h('thead', null, h('tr', null, ['動作', '組數', '本期', '上期', '變化'].map((t) => h('th', { scope: 'col', text: t })))),
            h('tbody', null, r.progress.slice(0, 10).map((x) => h('tr', null,
              h('th', { scope: 'row', text: x.name }),
              h('td', { text: x.sets }),
              h('td', { text: x.metric === 'e1rm' ? (x.value ? `${num(x.value)} kg` : '—') : `${x.value} 下` }),
              h('td', { text: x.prev_value ? (x.metric === 'e1rm' ? `${num(x.prev_value)} kg` : `${x.prev_value} 下`) : '—' }),
              h('td', null, delta(x.change_pct) || '—')))))) : h('p', { class: 'bd-muted', text: '這段期間沒有訓練紀錄。' }),
          h('p', { class: 'bd-muted', text: '有負重的動作以估計 1RM（Epley 公式，12 下以內）比較；徒手動作以單組最多次數比較。' }),
          r.weight ? h('p', { class: 'bd-report__weight' },
            `體重 ${num(r.weight.start)} → ${num(r.weight.end)} kg（${r.weight.change > 0 ? '+' : ''}${r.weight.change}，${r.weight.records} 筆紀錄）`) : null)));
  }

  // ------------------------------------------------------------ 一句話輸入（解析結果只是草稿）
  // quick: {text, busy, result: {items, unparsed, note, source}, picks: {index: exercise_id}, use: {index: bool}}
  // forms: {index: {open, name, muscle_group, equipment, is_cardio}} 新增動作的表單；added: {index: true} 已加入的項目
  const emptyQuick = (text = '') => ({ text, busy: false, result: null, picks: {}, use: {}, forms: {}, added: {}, saving: null });
  let quick = emptyQuick();
  const MUSCLE_CHOICES = ['胸', '背', '腿', '肩', '手臂', '核心'];
  const EQUIPMENT_CHOICES = ['槓鈴', '啞鈴', '機械', '纜繩', '徒手', '史密斯機', 'EZ 槓', '壺鈴', '彈力帶', '其他'];
  function openNewForm(i) {
    const item = quick.result.items[i];
    const guess = item.suggest || {};
    quick.forms[i] = quick.forms[i] || { name: item.input_text, muscle_group: guess.muscle_group || '',
      equipment: guess.equipment || '', is_cardio: guess.is_cardio ? '1' : '0' };
    quick.forms[i].open = true;
  }
  const setsSummary = (sets) => {
    if (!sets.length) return '沒有組數';
    const same = sets.every((x) => x.weight_kg === sets[0].weight_kg && x.reps === sets[0].reps);
    const one = (x) => `${x.weight_kg ? `${num(x.weight_kg)} kg` : '徒手'} × ${x.reps ?? '?'}`;   // ? = 沒寫次數
    return same ? `${sets.length} 組・${one(sets[0])}` : sets.map(one).join('、');
  };

  function quickPanel() {
    const r = quick.result;
    return h('div', { class: 'bd-quick' },
      h('form', { class: 'bd-quick__form', dataset: { form: 'quick-parse' } },
        h('label', { class: 'bd-sr', for: 'bd-quick-text', text: '用一句話輸入訓練' }),
        h('input', {
          id: 'bd-quick-text', class: 'bd-quick__input', type: 'text', maxlength: 300, value: quick.text,
          placeholder: '一句話輸入，例如：臥推 60公斤 5組8下，引體向上 3組10下', autocomplete: 'off',
          dataset: { key: 'quick-text', quick: 'text' }
        }),
        h('button', { class: 'bd-btn bd-btn--primary', disabled: quick.busy, dataset: { key: 'quick-parse' } }, quick.busy ? '解析中…' : '解析')),
      r ? quickResult(r) : null);
  }

  function quickResult(r) {
    const options = (item) => {
      const seen = new Set(item.candidates.map((c) => c.id).concat(item.exercise_id ? [item.exercise_id] : []));
      return [
        h('option', { value: '', text: item.candidates.length ? '請選擇動作…' : '從動作庫選擇…' }),
        h('option', { value: '__new__', text: `＋ 新增「${item.input_text}」為新動作…` }),
        item.exercise_id ? h('option', { value: item.exercise_id, text: item.name }) : null,
        item.candidates.length ? h('optgroup', { label: '可能是' }, item.candidates.map((c) => h('option', { value: c.id, text: c.name }))) : null,
        h('optgroup', { label: '全部動作' }, state.library.filter((e) => !seen.has(e.id)).map((e) => h('option', { value: e.id, text: e.name })))
      ];
    };
    return h('div', { class: 'bd-quick__result', role: 'region', 'aria-label': '解析結果（尚未寫入）' },
      r.items.length ? r.items.map((item, i) => {
        if (quick.added[i]) {
          return h('div', { class: 'bd-quick__item is-added' },
            icon('check-circle'), h('span', { text: ` 「${item.input_text}」已新增到動作庫並加入預計組數` }));
        }
        const pick = quick.picks[i] ?? item.exercise_id ?? '';
        const select = h('select', { class: 'bd-quick__select', dataset: { quickPick: i, key: `qp-${i}` }, 'aria-label': `「${item.input_text}」對應的動作` }, options(item));
        select.value = String(pick || '');
        return h('div', { class: 'bd-quick__item' + (item.error ? ' has-error' : '') },
          h('label', { class: 'bd-quick__use' },
            h('input', { type: 'checkbox', checked: quick.use[i] ?? !item.error, dataset: { quickUse: i, key: `qu-${i}` } }),
            h('span', { class: 'bd-sr', text: `加入「${item.input_text}」` })),
          h('div', { class: 'bd-quick__body' },
            h('div', { class: 'bd-quick__line' }, h('span', { class: 'bd-quick__said', text: `「${item.input_text}」` }), select),
            h('small', { text: setsSummary(item.sets) }),
            item.error ? h('small', { class: 'bd-quick__error', text: `${item.error}，預設不加入，可勾選後再到下方修改。` }) : null,
            !item.error && item.warning ? h('small', { class: 'bd-quick__hint', text: item.warning }) : null,
            quick.forms[i] && quick.forms[i].open ? newExerciseForm(i, item) : null));
      }) : h('p', { class: 'bd-muted', text: '沒有解析到訓練內容。' }),
      r.unparsed.length ? h('p', { class: 'bd-quick__warn', text: `以下內容沒有被記錄：${r.unparsed.join('、')}` }) : null,
      r.note ? h('p', { class: 'bd-quick__warn', text: r.note }) : null,
      h('div', { class: 'bd-quick__actions' },
        h('span', { class: 'bd-muted', text: r.source === 'llm'
          ? `AI 解析${r.usage ? `（${(r.usage.latency_ms / 1000).toFixed(1)} 秒）` : ''}・請確認後加入`
          : '規則解析・請確認後加入' }),
        h('button', { type: 'button', class: 'bd-btn', dataset: { action: 'quick-cancel', key: 'quick-cancel' }, text: '取消' }),
        r.items.length ? h('button', { type: 'button', class: 'bd-btn bd-btn--primary', dataset: { action: 'quick-apply', key: 'quick-apply' }, text: '加入預計組數' }) : null));
  }

  /** 動作庫沒有這個動作時：詢問名稱、部位、器材、是否有氧，確認後新增並加入預計組數 */
  function newExerciseForm(i, item) {
    const f = quick.forms[i];
    const field = (name, extra = {}) => ({ dataset: { quickNew: i, field: name, key: `qn-${i}-${name}` }, ...extra });
    const select = (name, options, label) => {
      const el = h('select', field(name, { class: 'bd-quick__select', 'aria-label': label }),
        options.map(([value, text]) => h('option', { value, text })));
      el.value = f[name];
      return el;
    };
    const saving = quick.saving === i;
    return h('div', { class: 'bd-newex', role: 'group', 'aria-label': `新增動作「${item.input_text}」` },
      h('p', { class: 'bd-newex__title' }, icon('plus-circle'), ` 動作庫沒有「${item.input_text}」，要新增這個動作嗎？`),
      h('label', { class: 'bd-newex__row' }, h('span', { text: '名稱' }),
        h('input', field('name', { class: 'bd-quick__select', type: 'text', maxlength: 80, value: f.name, required: true }))),
      h('label', { class: 'bd-newex__row' }, h('span', { text: '部位' }),
        select('muscle_group', [['', '請選擇…']].concat(MUSCLE_CHOICES.map((m) => [m, m])), '部位')),
      h('label', { class: 'bd-newex__row' }, h('span', { text: '器材' }),
        h('input', field('equipment', { class: 'bd-quick__select', type: 'text', maxlength: 50, value: f.equipment,
          list: 'bd-equipment-list', placeholder: '例如 啞鈴、機械、徒手' })),
        h('datalist', { id: 'bd-equipment-list' }, EQUIPMENT_CHOICES.map((e) => h('option', { value: e })))),
      h('label', { class: 'bd-newex__row' }, h('span', { text: '有氧' }),
        select('is_cardio', [['0', '否（重量訓練）'], ['1', '是（有氧）']], '是否為有氧')),
      h('div', { class: 'bd-newex__actions' },
        h('button', { type: 'button', class: 'bd-btn', dataset: { action: 'quick-new-cancel', idx: i, key: `qnc-${i}` }, text: '先不要' }),
        h('button', { type: 'button', class: 'bd-btn bd-btn--primary', disabled: saving,
          dataset: { action: 'quick-new-save', idx: i, key: `qns-${i}` }, text: saving ? '新增中…' : '新增動作並加入訓練' })));
  }

  async function saveNewExercise(i) {
    const f = quick.forms[i];
    const item = quick.result.items[i];
    if (!f.name.trim()) { showMessage('請輸入動作名稱。', 'error'); return; }
    if (!f.muscle_group) { showMessage('請選擇部位。', 'error'); return; }
    if (!f.equipment.trim()) { showMessage('請輸入使用的器材。', 'error'); return; }
    quick.saving = i; render();
    try {
      const data = await call('POST', '/exercises', {
        d: state.d, name: f.name.trim(), muscle_group: f.muscle_group, equipment: f.equipment.trim(), is_cardio: f.is_cardio === '1'
      });
      if (!data) return;
      state = data.state;
      const id = data.exercise.id;
      quick.picks[i] = id;
      quick.added[i] = true;
      f.open = false;
      if (item.sets.length) applySets(id, item.sets); else addToPlan(id);
      showMessage(data.existed ? `動作庫已經有「${data.exercise.name}」，已直接加入預計組數。`
        : `已新增動作「${data.exercise.name}」並加入預計組數。`);
      if (quick.result.items.every((_, j) => quick.added[j])) quick = emptyQuick();
      planSel = id;
      syncUrl('replace');
    } catch (err) {
      showMessage(err.message, 'error');
    } finally {
      quick.saving = null; render();
    }
  }

  /** 把一個動作的組數填進預計組數（草稿）；已完成的組保留，後面接上新的組 */
  function applySets(id, sets) {
    const done = (state.workout && (state.workout.exercises.find((e) => e.id === id) || {}).done) || 0;
    updatePlan(id, (entry) => {
      const kept = entry.sets.slice(0, done);
      while (kept.length < done) kept.push(blankSet());
      entry.sets = kept.concat(sets.map((x) => ({ kg: num(x.weight_kg), reps: num(x.reps) })));
    });
  }

  async function quickParse() {
    const text = quick.text.trim();
    if (!text || quick.busy) return;
    quick.busy = true; render();
    try {
      const data = await call('POST', '/parse', { text });
      if (data) {
        quick = emptyQuick(text);
        quick.result = data;
        data.items.forEach((item, i) => { if (!item.exercise_id && !item.candidates.length) openNewForm(i); });
      }
      showMessage('');
    } catch (err) {
      showMessage(err.message, 'error');
    } finally {
      quick.busy = false; render();
    }
  }

  /** 把解析結果填進預計組數（草稿）；已完成的組保留，後面接上解析出來的組 */
  function quickApply() {
    const r = quick.result;
    const chosen = [];
    let waiting = 0;
    r.items.forEach((item, i) => {
      if (quick.added[i] || !(quick.use[i] ?? !item.error)) return;
      const id = Number(quick.picks[i] ?? item.exercise_id);
      if (!id) { if (quick.forms[i] && quick.forms[i].open) waiting += 1; return; }
      if (!item.sets.length) return;
      chosen.push([id, item.sets]);
    });
    if (!chosen.length) {
      showMessage(waiting ? '請先完成「新增動作」，或從下拉選單選擇動作。' : '請至少勾選一個動作，並選好對應的動作。', 'error');
      return;
    }
    chosen.forEach(([id, sets]) => applySets(id, sets));
    quick = emptyQuick();
    showMessage(`已加入 ${chosen.length} 個動作的預計組數，請確認後再開始或逐組完成。`);
    const first = chosen[0][0];
    if (state.workout) load(state.d, first, 'replace'); else { planSel = first; render(); }
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

  const kgInput = (value, label, extra = {}) => h('input', {
    class: 'bd-input', type: 'number', name: 'weight_kg', step: 'any', min: 0, max: 1000, inputmode: 'decimal',
    value, placeholder: 'kg', 'aria-label': label, ...extra
  });
  const repsInput = (value, label, extra = {}) => h('input', {
    class: 'bd-input', type: 'number', name: 'reps', step: 1, min: 1, max: 10000, inputmode: 'numeric',
    value, placeholder: '次', 'aria-label': label, ...extra
  });
  const lastOf = (lib, no) => {
    const x = lib && lib.last ? lib.last.find((r) => r.set_no === no) : null;
    return x ? pair(x) : '';
  };

  /** 開始前：設定選中動作的每一組重量與次數 */
  function planCard(items) {
    if (!items.length) {
      return h('section', { class: 'bd-card bd-current bd-ready', 'aria-label': '開始訓練' },
        h('p', { class: 'bd-muted', text: '還沒有動作。可以在左邊用一句話輸入，或用「加入動作」選擇今天要練的項目。' }),
        startButton('start-plan'));
    }
    if (!items.some((e) => e.id === planSel)) planSel = items[0].id;
    const lib = libById(planSel);
    const entry = planFor(planSel) || { sets: [] };
    const meta = [lib.muscle_group, lib.equipment].filter(Boolean);
    if (lib.last && lib.last.length) meta.push(`上次 ${lib.last.map(pair).join('、')}`);
    return h('section', { class: 'bd-card bd-current', 'aria-label': `設定 ${lib.name} 的每一組` },
      h('header', { class: 'bd-current__head' }, h('h3', { text: lib.name }), h('p', { class: 'bd-muted', text: meta.join('・') })),
      h('div', { class: 'bd-grid bd-grid--plan bd-grid--head', 'aria-hidden': 'true' },
        ['組', '上次', 'kg', '次', ''].map((t) => h('span', { text: t }))),
      entry.sets.map((x, i) => h('div', { class: 'bd-grid bd-grid--plan bd-row is-plan' },
        h('span', { class: 'bd-row__no', text: i + 1 }),
        h('span', { class: 'bd-row__last', text: lastOf(lib, i + 1) || '—' }),
        kgInput(x.kg, `第 ${i + 1} 組預計重量 kg`, { dataset: { planEx: planSel, planIdx: i, planField: 'kg', key: `pkg-${i}` } }),
        repsInput(x.reps, `第 ${i + 1} 組預計次數`, { dataset: { planEx: planSel, planIdx: i, planField: 'reps', key: `prp-${i}` } }),
        h('button', {
          type: 'button', class: 'bd-check bd-check--remove', dataset: { action: 'plan-del-set', ex: planSel, idx: i, key: `pdel-${i}` },
          'aria-label': `刪除第 ${i + 1} 組`, title: '刪除這一組'
        }, icon('times')))),
      h('button', { type: 'button', class: 'bd-btn bd-btn--soft', dataset: { action: 'plan-add-set', ex: planSel, key: 'plan-add-set' } }, icon('plus'), ' 新增一組'),
      h('div', { class: 'bd-ready__foot' },
        h('p', { class: 'bd-muted', text: `已排好 ${items.length} 個動作，共 ${readPlan().reduce((n, p) => n + p.sets.length, 0)} 組` }),
        startButton('start-plan')));
  }

  /** 開始後：已完成的組 ＋ 還沒做的預計組（每組都能改重量／次數，按 ✓ 完成） */
  function currentCard(cur, w) {
    if (!cur) {
      return h('section', { class: 'bd-card bd-current', 'aria-label': '逐組輸入' },
        h('p', { class: 'bd-empty', text: '從左邊選一個動作，或用「加入動作」開始第一組。' }));
    }
    const meta = [cur.muscle_group, cur.equipment].filter(Boolean);
    if (cur.best) meta.push(`上次最佳 ${pair(cur.best)}`);
    const lib = libById(cur.exercise_id);
    const planned = (planFor(cur.exercise_id) || { sets: [] }).sets;
    const done = cur.sets.length;
    // 還沒做的組：照預計的；預計的都做完了就給一列（預填剛做的那組）
    const pending = planned.length > done
      ? planned.slice(done).map((x, j) => ({ no: done + j + 1, kg: x.kg, reps: x.reps, planIdx: done + j }))
      : [{ no: cur.next.set_no, kg: num(cur.next.weight_kg), reps: num(cur.next.reps), planIdx: null }];
    const seed = { kg: num(cur.next.weight_kg), reps: num(cur.next.reps) };

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
      pending.map((row, j) => {
        // 沒填的組沿用上一列的數字（第一列沿用剛做的那組）
        const prev = j === 0 ? seed : pending[j - 1];
        row.kg = row.kg || prev.kg;
        row.reps = row.reps || prev.reps;
        const planData = row.planIdx === null ? {} : { planEx: cur.exercise_id, planIdx: row.planIdx };
        return h('form', {
          class: 'bd-grid bd-row ' + (j === 0 ? 'is-next' : 'is-todo'),
          dataset: { form: 'add-set', workout: w.id, exercise: cur.exercise_id }
        },
        h('span', { class: 'bd-row__no', text: row.no }),
        h('span', { class: 'bd-row__last', text: lastOf(lib, row.no) || '—' }),
        kgInput(row.kg, `第 ${row.no} 組重量 kg`, { required: true, dataset: { ...planData, planField: 'kg', key: `kg-${row.no}` } }),
        repsInput(row.reps, `第 ${row.no} 組次數`, { required: true, dataset: { ...planData, planField: 'reps', key: `rp-${row.no}` } }),
        h('input', { class: 'bd-input bd-input--sm', type: 'number', name: 'rpe', step: 1, min: 1, max: 10, inputmode: 'numeric', placeholder: '—', 'aria-label': `第 ${row.no} 組 RPE（選填）` }),
        h('button', { class: 'bd-check', dataset: { key: j === 0 ? 'next-check' : `check-${row.no}` }, 'aria-label': `完成第 ${row.no} 組` }, icon('check')));
      }),
      h('button', { type: 'button', class: 'bd-btn bd-btn--soft', dataset: { action: 'plan-add-set', ex: cur.exercise_id, key: 'plan-add-set' } }, icon('plus'), ' 新增一組'));
  }

  // ------------------------------------------------------------ 事件
  root.addEventListener('click', (event) => {
    const target = event.target.closest('[data-action]');
    if (!target || !root.contains(target)) return;
    const { action, d, id, ex } = target.dataset;
    if (action === 'goto') load(d);
    else if (action === 'pick') load(state.d, ex);
    else if (action === 'plan-pick') { planSel = Number(ex); render(); }
    else if (action === 'report-period') { report.period = target.dataset.period; loadReport(true); }
    else if (action === 'quick-cancel') { quick = emptyQuick(quick.text); render(); }
    else if (action === 'quick-new-save') saveNewExercise(Number(target.dataset.idx));
    else if (action === 'quick-new-cancel') { quick.forms[target.dataset.idx].open = false; render(); }
    else if (action === 'quick-apply') quickApply();
    else if (action === 'rest-default') {
      // 只改之後每次休息的起始秒數；正在倒數的這一次不受影響
      // 對齊到 10 秒的倍數（舊版以 15 秒為單位存過的值，例如 105，會變成 110 / 100）
      const step = Number(target.dataset.step);
      setRestSetting((step > 0 ? Math.floor : Math.ceil)(restSetting() / REST_STEP) * REST_STEP + step);
      render();
    }
    else if (action === 'plan-add-set') {
      const id = Number(ex);
      updatePlan(id, (entry) => {
        // 新的一組照最後一組的數字；還沒有預計組時，接在已完成的組後面
        const done = state.current && state.current.exercise_id === id ? state.current.sets : [];
        while (entry.sets.length < done.length) {
          const x = done[entry.sets.length];
          entry.sets.push({ kg: num(x.weight_kg), reps: num(x.reps) });
        }
        const last = entry.sets[entry.sets.length - 1];
        entry.sets.push(last ? { ...last } : blankSet());
      });
      render();
    } else if (action === 'plan-del-set') {
      updatePlan(Number(ex), (entry) => { entry.sets.splice(Number(target.dataset.idx), 1); });
      render();
    } else if (action === 'start') {
      if (!canStart()) { showMessage('請先加入至少一個動作，再開始訓練。', 'error'); return; }
      run('POST', '/workouts', { d: state.d, exercise_ids: getPlan() }, { history: 'replace' });
    } else if (action === 'remove-plan') {
      const id = Number(ex);
      removeFromPlan(id);
      if (state.current && state.current.exercise_id === id) load(state.d, null, 'replace');
      else render();
    }
    else if (action === 'end') {
      if (window.confirm('結束並儲存這次訓練？')) {
        const d = state.d;
        run('POST', `/workouts/${id}/end`).then((data) => {
          if (data && data.state.workout) writePlan([], d);   // 已儲存 → 清掉草稿；若因沒有組數被取消，保留清單方便重來
          if (data) render();
        });
      }
    } else if (action === 'delete-set') run('POST', `/sets/${id}/delete`);
  });

  const blank = (v) => (v.trim() === '' ? null : v.trim());
  root.addEventListener('submit', (event) => {
    const form = event.target;
    event.preventDefault();
    if (form.dataset.form === 'quick-parse') { quickParse(); return; }
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
      addToPlan(ex);
      planSel = ex;
      if (state.workout) load(state.d, ex); else render();
    }
  });

  root.addEventListener('change', (event) => {
    const el = event.target;
    if (el.dataset.quickPick !== undefined) {
      const i = Number(el.dataset.quickPick);
      if (el.value === '__new__') { quick.picks[i] = null; openNewForm(i); render(); return; }
      quick.picks[i] = el.value ? Number(el.value) : null;
      if (quick.forms[i]) quick.forms[i].open = false;
      render();
    }
    if (el.dataset.quickUse !== undefined) quick.use[el.dataset.quickUse] = el.checked;
  });

  root.addEventListener('input', (event) => {
    const el = event.target;
    if (el.dataset.quick === 'text') { quick.text = el.value; return; }
    if (el.dataset.quickNew !== undefined) { quick.forms[el.dataset.quickNew][el.dataset.field] = el.value; return; }
    if (!el.dataset || el.dataset.planIdx === undefined || !el.dataset.planEx) return;
    const idx = Number(el.dataset.planIdx);
    updatePlan(Number(el.dataset.planEx), (entry) => {
      while (entry.sets.length <= idx) entry.sets.push(blankSet());
      entry.sets[idx][el.dataset.planField] = el.value;
    });
  });

  window.addEventListener('popstate', () => {
    const params = new URLSearchParams(window.location.search);
    load(params.get('d') || state.today, params.get('ex'), 'none');
  });

  // ------------------------------------------------------------ 頁籤
  const tabs = Array.from(root.querySelectorAll('[data-tab-target]'));
  let currentTab = 'train';
  const showTab = (name) => {
    currentTab = name;
    tabs.forEach((tab) => {
      const on = tab.dataset.tabTarget === name;
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
      $(tab.getAttribute('aria-controls')).hidden = !on;
    });
    if (name === 'analysis') loadReport();
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
  // 每一次休息都從「預設休息時間」開始；休息中按 ±10 秒只影響這一次，不會變成下一次的預設
  // 預設休息時間由使用者在「逐組紀錄」標題旁設定，存在這台瀏覽器（REST_SETTING_KEY）
  const REST_DEFAULT_SEC = 90;
  const bar = $('bd-rest');
  let restTimer = null;
  const defaultRest = () => restSetting();
  store.del('bdRestDefault');   // 清掉舊版記住的秒數（已不再使用）
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
      runRest();
    });
  });
  bar.querySelector('[data-rest-skip]').addEventListener('click', () => stopRest(false));

  // ------------------------------------------------------------ 啟動
  render();
  showTab(['weight', 'analysis'].includes(root.dataset.tab) ? root.dataset.tab : 'train');
  syncUrl('replace');
  runRest();
})();
