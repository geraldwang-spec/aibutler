(() => {
  const NS = 'http://www.w3.org/2000/svg';
  const COLORS = {correct: '#7868df', wrong: '#f2ae82', muted: '#c7c1e5'};
  function element(tag, attrs = {}, content) {
    const node = document.createElementNS(NS, tag);
    for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, String(value));
    if (content !== undefined) node.textContent = content;
    return node;
  }
  function svg(width, height, description) {
    const node = element('svg', {viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': description});
    node.append(element('title', {}, description));
    return node;
  }
  function empty(container) {
    const message = document.createElement('p');
    message.className = 'chart-empty';
    message.textContent = '尚無已完成的作答資料；完成測驗後會顯示圖表。';
    container.replaceChildren(message);
  }
  function pie(container, correct, wrong) {
    const total = correct + wrong;
    if (!total) { empty(container); return; }
    const rate = correct / total;
    const chart = svg(240, 240, `答對 ${correct} 題，未答對 ${wrong} 題，正確率 ${(rate * 100).toFixed(1)}%`);
    const radius = 88;
    const circumference = 2 * Math.PI * radius;
    chart.append(element('circle', {cx:120,cy:120,r:radius,fill:'none',stroke:COLORS.wrong,'stroke-width':28}));
    if (correct) chart.append(element('circle', {cx:120,cy:120,r:radius,fill:'none',stroke:COLORS.correct,'stroke-width':28,'stroke-dasharray':`${rate*circumference} ${circumference}` ,transform:'rotate(-90 120 120)'}));
    chart.append(element('text', {x:120,y:120,'text-anchor':'middle',fill:'#303349','font-size':30,'font-weight':650}, `${(rate * 100).toFixed(1)}%`));
    chart.append(element('text', {x:120,y:144,'text-anchor':'middle',fill:'#858997','font-size':12}, '整體正確率'));
    container.replaceChildren(chart);
  }
  function bars(container, rows, kind) {
    if (!rows.length) { empty(container); return; }
    const selected = kind === 'chapters' ? rows.slice(0,12) : rows.slice(0,10).reverse();
    const height = 42 + selected.length * 60;
    const chart = svg(620, height, kind === 'chapters' ? '章節正確率長條圖，詳細數據見下方表格' : '最近測驗正確率長條圖，詳細數據見下方測驗紀錄');
    for (const rate of [0,25,50,75,100]) {
      const x = 205 + rate * 3.4;
      chart.append(element('line', {x1:x,y1:30,x2:x,y2:height,stroke:'#ececf3'}));
      chart.append(element('text', {x,y:18,'text-anchor':'middle',fill:'#9295a6','font-size':11}, `${rate}%`));
    }
    selected.forEach((row, index) => {
      const y = 45 + index * 60;
      const raw = kind === 'chapters' ? Number(row.accuracy) : (Number(row.correct_count) / Number(row.total_count) * 100 || 0);
      const rate = Math.max(0, Math.min(100, raw));
      const label = kind === 'chapters' ? row.chapter_name : `${row.subject_name} · #${row.id}`;
      const text = element('text', {x:0,y:y+12,fill:'#535a71','font-size':12}, label.length > 16 ? label.slice(0,16)+'…' : label);
      text.append(element('title', {}, label));
      chart.append(text);
      const subtitle = kind === 'chapters' ? `${row.subject_name} · ${row.n} 次${row.insufficient ? ' · 資料不足' : ''}` : String(row.finished_at || '').slice(0,16);
      chart.append(element('text', {x:0,y:y+29,fill:'#9295a6','font-size':10}, subtitle));
      chart.append(element('rect', {x:205,y,width:340,height:22,rx:5,fill:'#f3f1fa'}));
      const bar = element('rect', {x:205,y,width:rate*3.4,height:22,rx:5,fill:row.insufficient ? COLORS.muted : COLORS.correct});
      bar.append(element('title', {}, `${label}：${rate.toFixed(1)}%`));
      chart.append(bar);
      chart.append(element('text', {x:555,y:y+16,fill:'#535a71','font-size':12}, `${rate.toFixed(1)}%`));
    });
    container.replaceChildren(chart);
  }
  document.querySelectorAll('.learning-charts').forEach(section => {
    const source = JSON.parse(section.querySelector('.learning-chart-data').textContent);
    const kind = section.dataset.chartKind;
    const filter = section.querySelector('select');
    const subjects = [...new Set(source.map(row => row.subject_name))];
    subjects.forEach(subject => {
      const option = document.createElement('option');
      option.value = option.textContent = subject;
      filter.append(option);
    });
    function draw() {
      const rows = source.filter(row => !filter.value || row.subject_name === filter.value);
      const correct = rows.reduce((sum,row) => sum + Number(kind === 'chapters' ? row.correct : row.correct_count || 0),0);
      const total = rows.reduce((sum,row) => sum + Number(kind === 'chapters' ? row.n : row.total_count || 0),0);
      pie(section.querySelector('.learning-pie'),correct,Math.max(0,total-correct));
      section.querySelector('.learning-chart-summary').textContent = total ? `共 ${total} 題 · 答對 ${correct} 題 · 未答對 ${total-correct} 題` : '目前沒有可分析的資料';
      bars(section.querySelector('.learning-bars'),rows,kind);
    }
    filter.addEventListener('change',draw);
    draw();
  });
})();
