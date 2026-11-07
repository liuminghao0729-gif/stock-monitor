// ===== 工具 =====
const $ = s => document.querySelector(s);
const UP = '#26c281', DOWN = '#ef4444';           // 美股习惯:涨绿跌红
const REFRESH = 15;                                // 自动刷新间隔(秒)
const MA_DEF = [[5, '#f5c542'], [10, '#b57bee'], [20, '#35c5e8'], [50, '#ff9a3c'], [100, '#ff6fa8'], [200, '#e6edf3']];
let Data = MockData; // 启动时会检查后台,可用则切换为真实数据(网址加 ?mock 可强制用模拟数据)
const fmt = (n, d = 2) => Number.isFinite(n) ? n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }) : '--';
const cls = n => n >= 0 ? 'up' : 'down';
const sgn = (n, d = 2) => Number.isFinite(n) ? (n >= 0 ? '+' : '') + fmt(n, d) : '--';
const big = n => n >= 1e9 ? fmt(n / 1e9) + 'B' : n >= 1e6 ? fmt(n / 1e6) + 'M' : n >= 1e3 ? fmt(n / 1e3) + 'K' : String(n);
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { } }
};

const state = {
  watch: store.get('watch', ['AAPL', 'NVDA', 'VOO', 'QQQ']),
  sel: null, range: '6M',
  ind: store.get('ind', { ma: [1, 1, 1, 1, 0, 0], vol: 1, rsi: 1, macd: 1, chip: 1 }),
  hover: -1, tab: 'watch', day: 0
};
state.sel = state.watch[0] || 'AAPL';

// ===== 指标计算 =====
function sma(a, n) { return a.map((_, i) => i < n - 1 ? null : a.slice(i - n + 1, i + 1).reduce((x, y) => x + y, 0) / n); }
function ema(a, n) { const k = 2 / (n + 1), o = []; a.forEach((v, i) => o.push(i ? v * k + o[i - 1] * (1 - k) : v)); return o; }
function rsi(c, n = 14) {
  const o = c.map(() => null); let g = 0, l = 0;
  for (let i = 1; i < c.length; i++) {
    const d = c[i] - c[i - 1], up = Math.max(d, 0), dn = Math.max(-d, 0);
    if (i <= n) { g += up / n; l += dn / n; } else { g = (g * (n - 1) + up) / n; l = (l * (n - 1) + dn) / n; }
    if (i >= n) o[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
  }
  return o;
}
function macd(c) {
  const e12 = ema(c, 12), e26 = ema(c, 26), dif = c.map((_, i) => e12[i] - e26[i]), dea = ema(dif, 9);
  return { dif, dea, hist: dif.map((v, i) => (v - dea[i]) * 2) };
}
// 筹码分布(估算):把最近120根K线的成交量按价格区间摊开,越久远权重越低
function chips(bars, bins = 40) {
  const seg = bars.slice(-120), lo = Math.min(...seg.map(b => b.l)), hi = Math.max(...seg.map(b => b.h)), step = (hi - lo) / bins || 1, arr = new Array(bins).fill(0);
  seg.forEach((b, i) => {
    const w = Math.pow(.985, seg.length - 1 - i), a = Math.floor((b.l - lo) / step), z = Math.min(bins - 1, Math.floor((b.h - lo) / step)), cnt = z - a + 1;
    for (let k = a; k <= z; k++) arr[k] += b.v * w / cnt;
  });
  return { arr, lo, step };
}

// ===== 顶部:状态、指数 =====
function marketStatus() {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).formatToParts(new Date()).map(x => [x.type, x.value]));
  const m = (+p.hour % 24) * 60 + +p.minute, wk = !['Sat', 'Sun'].includes(p.weekday);
  let s = ['休市', ''];
  if (wk) { if (m >= 240 && m < 570) s = ['盘前', 'pre']; else if (m >= 570 && m < 960) s = ['盘中', 'open']; else if (m >= 960 && m < 1200) s = ['盘后', 'post']; }
  $('#mkt').textContent = '美股' + s[0]; $('#mkt').className = 'pill ' + s[1];
  $('#clock').textContent = `纽约 ${p.hour}:${p.minute}`;
}
function renderIndices() {
  $('#indices').innerHTML = Data.INDICES.map(([s, n]) => {
    const q = Data.quote(s);
    return `<div class="idx"><div class="n">${n}</div><div class="p">${fmt(q.price, q.price < 200 ? 2 : 0)}</div><div class="c ${cls(q.pct)}">${sgn(q.pct)}%</div></div>`;
  }).join('');
}

// ===== 自选股 =====
function renderWatch() {
  $('#watchList').innerHTML = state.watch.map(s => {
    const q = Data.quote(s);
    return `<div class="wrow ${s === state.sel ? 'sel' : ''}" data-s="${s}"><div><div class="s">${s}</div><div class="nm">${q.name}</div></div>
      <div class="px">${fmt(q.price)}</div><div><span class="chg ${cls(q.pct)}">${sgn(q.pct)}%</span><button class="x" data-del="${s}" title="删除">×</button></div></div>`;
  }).join('') || '<div class="muted small" style="padding:10px">还没有自选股,在上面输入代码添加。</div>';
}
$('#watchList').addEventListener('click', e => {
  const del = e.target.dataset.del;
  if (del) { state.watch = state.watch.filter(x => x !== del); store.set('watch', state.watch); if (state.sel === del) state.sel = state.watch[0]; renderWatch(); renderDetail(); return; }
  const row = e.target.closest('.wrow'); if (row) selectStock(row.dataset.s);
});
$('#addForm').addEventListener('submit', async e => {
  e.preventDefault();
  const s = $('#addInput').value.trim().toUpperCase(), msg = $('#addMsg');
  if (!s) return;
  if (state.watch.includes(s)) { msg.textContent = s + ' 已在自选股中'; return; }
  msg.textContent = '查询中…';
  let ok = false; try { ok = await Data.validate(s); } catch { }
  if (!ok) { msg.textContent = Data.mode === 'mock' ? `模拟模式只支持内置股票;启动后台后可添加任意代码。` : `找不到代码 ${s},请检查拼写。`; return; }
  state.watch.push(s); store.set('watch', state.watch); msg.textContent = ''; $('#addInput').value = ''; renderWatch();
});
function selectStock(s) { state.sel = s; state.hover = -1; switchTab('watch'); renderWatch(); renderDetail(); }

// ===== 个股详情 =====
function headHTML(s) {
  const q = Data.quote(s);
  return `<div class="dh"><div><h2>${s} <span class="muted" style="font-size:14px;font-weight:400">${q.name}</span></h2></div>
    <div style="text-align:right"><span class="big ${cls(q.change)}">${fmt(q.price)}</span> <span class="${cls(q.change)}">${sgn(q.change)} (${sgn(q.pct)}%)</span></div></div>
  <div class="stats">
    <div class="stat"><div class="l">今开</div>${fmt(q.open)}</div><div class="stat"><div class="l">最高</div>${fmt(q.high)}</div>
    <div class="stat"><div class="l">最低</div>${fmt(q.low)}</div><div class="stat"><div class="l">昨收</div>${fmt(q.prev)}</div>
    <div class="stat"><div class="l">成交量</div>${Number.isFinite(q.price) ? big(q.volume) : '--'}</div></div>`;
}
async function renderDetail() {
  const s = state.sel, r = state.range; if (!s) { $('#detail').innerHTML = '<div class="muted">请先添加自选股</div>'; return; }
  const I = state.ind;
  $('#detail').innerHTML = `<div id="dhead">${headHTML(s)}</div>
  <div class="ctrl" id="ranges">${['1D', '5D', '1M', '6M', '1Y', '5Y'].map(r => `<button data-r="${r}" class="${r === state.range ? 'on' : ''}">${{ '1D': '1日', '5D': '5日', '1M': '1月', '6M': '半年', '1Y': '1年', '5Y': '5年' }[r]}</button>`).join('')}</div>
  <div class="ctrl" id="inds">
    ${MA_DEF.map((m, i) => `<label style="color:${m[1]}"><input type="checkbox" data-ma="${i}" ${I.ma[i] ? 'checked' : ''}>MA${m[0]}</label>`).join('')}
    ${[['vol', '成交量'], ['rsi', 'RSI'], ['macd', 'MACD'], ['chip', '筹码分布(估算)']].map(([k, n]) => `<label><input type="checkbox" data-k="${k}" ${I[k] ? 'checked' : ''}>${n}</label>`).join('')}
  </div>
  <div class="legend" id="legend"></div>
  <div class="chartwrap" id="cw"><div class="muted" style="padding:40px 0;text-align:center">图表加载中…</div></div>
  <h3>${s} 相关新闻 ${Data.mode === 'mock' ? '<span class="badge">模拟</span>' : ''}</h3>
  <ul class="news" id="stockNews"><li class="muted">加载中…</li></ul>`;
  const stale = () => state.sel !== s || state.range !== r || state.tab !== 'watch';
  Data.loadBars(s, r).then(() => { if (!stale()) drawCharts(); })
    .catch(() => { if (!stale()) $('#cw').innerHTML = '<div class="muted" style="padding:40px 0;text-align:center">图表数据加载失败,稍后会自动重试</div>'; });
  Data.loadNews(s).then(l => { if (!stale()) $('#stockNews').innerHTML = newsHTML(l); })
    .catch(() => { if (!stale()) $('#stockNews').innerHTML = '<li class="muted">新闻加载失败</li>'; });
}
function newsHTML(list) {
  if (!Array.isArray(list)) return `<li class="muted">${list.error}</li>`;
  if (!list.length) return '<li class="muted">暂无新闻</li>';
  return list.map(n => `<li><span class="tag ${n.hot ? 'hot' : ''}">${n.hot ? '重要' : n.src}</span><div>${/^https?:\/\//.test(n.url || '') ? `<a href="${n.url}" target="_blank" rel="noopener noreferrer" style="color:inherit">${esc(n.title)}</a>` : esc(n.title)}<div class="muted small">${esc(n.src)} · ${n.minsAgo < 60 ? n.minsAgo + ' 分钟前' : Math.round(n.minsAgo / 60) + ' 小时前'}</div></div></li>`).join('');
}
const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
$('#detail').addEventListener('click', e => {
  const r = e.target.dataset.r; if (r) { state.range = r; state.hover = -1; renderDetail(); }
});
$('#detail').addEventListener('change', e => {
  const t = e.target, I = state.ind;
  if (t.dataset.ma !== undefined) I.ma[+t.dataset.ma] = t.checked ? 1 : 0;
  if (t.dataset.k) I[t.dataset.k] = t.checked ? 1 : 0;
  store.set('ind', I); drawCharts();
});

// ===== 图表(自己用 Canvas 画,无需外部库)=====
let V = null; // 当前图表数据,供悬停使用
function prepare() {
  const R = Data.bars(state.sel, state.range), src = R.daily ? R.full : R.bars, n = R.daily ? R.n : R.bars.length;
  const c = src.map(b => b.c), off = src.length - n;
  const cut = a => a.slice(off);
  const ma = MA_DEF.map(([k]) => R.daily ? cut(sma(c, k)) : null);
  const m = macd(c);
  return { bars: R.bars, daily: R.daily, ma, rsi: cut(rsi(c)), macd: { dif: cut(m.dif), dea: cut(m.dea), hist: cut(m.hist) }, chip: chips(R.daily ? R.full : R.bars) };
}
function mk(h) {
  const cv = document.createElement('canvas'), dpr = window.devicePixelRatio || 1, w = cv.parentW;
  return { cv, h, dpr };
}
function drawCharts() {
  const cw = $('#cw'); if (!cw || !Data.bars(state.sel, state.range)) return;
  V = prepare(); const I = state.ind;
  const W = cw.clientWidth, chipW = I.chip ? 90 : 0, mainW = W - chipW;
  cw.innerHTML = '';
  const panels = [{ id: 'price', h: 300 }];
  if (I.vol) panels.push({ id: 'vol', h: 70 }); if (I.rsi) panels.push({ id: 'rsi', h: 80 }); if (I.macd) panels.push({ id: 'macd', h: 90 });
  V.panels = panels;
  panels.forEach(p => {
    const row = document.createElement('div'); row.className = 'chartrow sub';
    const cv = document.createElement('canvas'); const dpr = window.devicePixelRatio || 1;
    cv.width = mainW * dpr; cv.height = p.h * dpr; cv.style.width = mainW + 'px'; cv.style.height = p.h + 'px';
    row.appendChild(cv); p.cv = cv; p.ctx = cv.getContext('2d'); p.ctx.scale(dpr, dpr); p.w = mainW;
    if (p.id === 'price' && chipW) {
      const c2 = document.createElement('canvas'); c2.width = chipW * dpr; c2.height = p.h * dpr; c2.style.width = chipW + 'px'; c2.style.height = p.h + 'px';
      row.appendChild(c2); p.chipCtx = c2.getContext('2d'); p.chipCtx.scale(dpr, dpr); p.chipW = chipW;
    }
    cw.appendChild(row);
    cv.addEventListener('mousemove', e => { const r = cv.getBoundingClientRect(), n = V.bars.length; state.hover = Math.max(0, Math.min(n - 1, Math.floor((e.clientX - r.left - 4) / ((mainW - 56) / n)))); paint(); });
    cv.addEventListener('mouseleave', () => { state.hover = -1; paint(); });
  });
  paint();
}
function paint() {
  const n = V.bars.length, I = state.ind;
  V.panels.forEach(p => {
    const x = p.ctx, w = p.w, h = p.h, L = 4, Rr = 52, pw = w - L - Rr, bw = pw / n, X = i => L + (i + .5) * bw;
    x.clearRect(0, 0, w, h); x.font = '11px sans-serif'; x.textBaseline = 'middle';
    const grid = (v, y) => { x.strokeStyle = '#222a35'; x.beginPath(); x.moveTo(L, y); x.lineTo(w - Rr, y); x.stroke(); x.fillStyle = '#8b949e'; x.textAlign = 'left'; x.fillText(v, w - Rr + 4, y); };
    const line = (arr, Y, col, lw = 1.2) => { x.strokeStyle = col; x.lineWidth = lw; x.beginPath(); let st = false; arr.forEach((v, i) => { if (v == null) return; st ? x.lineTo(X(i), Y(v)) : (x.moveTo(X(i), Y(v)), st = true); }); x.stroke(); x.lineWidth = 1; };
    const scale = (lo, hi, pad = 8) => { const r = hi - lo || 1; return v => pad + (1 - (v - lo) / r) * (h - pad * 2); };
    if (p.id === 'price') {
      const vals = V.bars.flatMap(b => [b.h, b.l]); V.ma.forEach((a, k) => { if (a && I.ma[k]) a.forEach(v => v != null && vals.push(v)); });
      const lo = Math.min(...vals), hi = Math.max(...vals), Y = scale(lo, hi);
      for (let k = 0; k < 5; k++) { const v = lo + (hi - lo) * k / 4; grid(fmt(v), Y(v)); }
      if (n <= 130) V.bars.forEach((b, i) => { x.strokeStyle = x.fillStyle = b.c >= b.o ? UP : DOWN; x.beginPath(); x.moveTo(X(i), Y(b.h)); x.lineTo(X(i), Y(b.l)); x.stroke(); x.fillRect(X(i) - Math.max(bw * .3, .5), Math.min(Y(b.o), Y(b.c)), Math.max(bw * .6, 1), Math.max(Math.abs(Y(b.o) - Y(b.c)), 1)); });
      else { line(V.bars.map(b => b.c), Y, '#4c8dff', 1.5); }
      V.ma.forEach((a, k) => a && I.ma[k] && line(a, Y, MA_DEF[k][1]));
      V.lastY = Y;
      if (p.chipCtx) drawChip(p, Y, lo, hi);
    } else if (p.id === 'vol') {
      const mx = Math.max(...V.bars.map(b => b.v)); grid(big(mx), 8); grid('0', h - 8);
      V.bars.forEach((b, i) => { x.fillStyle = b.c >= b.o ? 'rgba(38,194,129,.7)' : 'rgba(239,68,68,.7)'; const hh = b.v / mx * (h - 16); x.fillRect(X(i) - Math.max(bw * .3, .5), h - 8 - hh, Math.max(bw * .6, 1), hh); });
    } else if (p.id === 'rsi') {
      const Y = scale(0, 100); [30, 50, 70].forEach(v => grid(v, Y(v))); line(V.rsi, Y, '#b57bee');
    } else if (p.id === 'macd') {
      const all = [...V.macd.dif, ...V.macd.dea, ...V.macd.hist].filter(v => v != null), m = Math.max(...all.map(Math.abs)) || 1, Y = scale(-m, m);
      grid('0', Y(0));
      V.macd.hist.forEach((v, i) => { x.fillStyle = v >= 0 ? 'rgba(38,194,129,.7)' : 'rgba(239,68,68,.7)'; x.fillRect(X(i) - Math.max(bw * .3, .5), Math.min(Y(0), Y(v)), Math.max(bw * .6, 1), Math.abs(Y(v) - Y(0))); });
      line(V.macd.dif, Y, '#f5c542'); line(V.macd.dea, Y, '#35c5e8');
    }
    // 时间轴(最后一个面板)
    if (p === V.panels[V.panels.length - 1]) { x.fillStyle = '#8b949e'; x.textAlign = 'center'; x.textBaseline = 'alphabetic'; (pw < 480 ? [0, .5, 1] : [0, .25, .5, .75, 1]).forEach(f => { const i = Math.min(n - 1, Math.round((n - 1) * f)); x.fillText(V.bars[i].t, Math.max(36, Math.min(w - Rr - 30, X(i))), h - 0); }); }
    // 十字光标
    if (state.hover >= 0) { x.strokeStyle = 'rgba(255,255,255,.35)'; x.setLineDash([3, 3]); x.beginPath(); x.moveTo(X(state.hover), 0); x.lineTo(X(state.hover), h); x.stroke(); x.setLineDash([]); }
  });
  legend();
}
function drawChip(p, Y, lo, hi) {
  const x = p.chipCtx, W = p.chipW, c = V.chip, mx = Math.max(...c.arr), last = V.bars[V.bars.length - 1].c;
  x.clearRect(0, 0, W, p.h);
  c.arr.forEach((v, k) => {
    const pr = c.lo + (k + .5) * c.step; if (pr < lo || pr > hi) return;
    const y = Y(pr), bh = Math.max(Math.abs(Y(pr) - Y(pr + c.step)), 1), len = v / mx * (W - 8);
    x.fillStyle = pr <= last ? 'rgba(38,194,129,.65)' : 'rgba(239,68,68,.65)'; x.fillRect(W - len, y - bh / 2, len, bh - .5);
  });
  x.fillStyle = '#8b949e'; x.font = '10px sans-serif'; x.textBaseline = 'top'; x.fillText('筹码(估算)', 4, 2);
}
function legend() {
  const i = state.hover >= 0 ? state.hover : V.bars.length - 1, b = V.bars[i], I = state.ind;
  let s = `<span class="muted">${b.t}</span> 开 ${fmt(b.o)} 高 ${fmt(b.h)} 低 ${fmt(b.l)} <b class="${cls(b.c - b.o)}">收 ${fmt(b.c)}</b> 量 ${big(b.v)}`;
  V.ma.forEach((a, k) => { if (a && I.ma[k] && a[i] != null) s += ` <span style="color:${MA_DEF[k][1]}">MA${MA_DEF[k][0]} ${fmt(a[i])}</span>`; });
  if (I.rsi && V.rsi[i] != null) s += ` <span style="color:#b57bee">RSI ${fmt(V.rsi[i], 1)}</span>`;
  if (I.macd && V.macd.dif[i] != null) s += ` <span style="color:#f5c542">DIF ${fmt(V.macd.dif[i])}</span> <span style="color:#35c5e8">DEA ${fmt(V.macd.dea[i])}</span>`;
  if (!V.daily) s += ' <span class="muted">(日内图:均线仅在1月及以上周期显示)</span>';
  $('#legend').innerHTML = s;
}

// ===== 板块 =====
const universe = () => Object.keys(Data.U);
const loading = el => { if (!el.innerHTML.trim()) el.innerHTML = '<div class="muted" style="padding:20px">加载中…</div>'; };
function qrow(s) { const q = Data.quote(s); return `<tr><td><span class="sym" data-go="${s}">${s}</span> <span class="muted small">${esc(q.name)}</span></td><td class="r">${fmt(q.price)}</td><td class="r ${cls(q.pct)}">${sgn(q.pct)}%</td></tr>`; }
async function renderSectors() {
  const el = $('#view-sectors'); loading(el);
  try { await Data.refreshQuotes(universe()); } catch { }
  if (state.tab !== 'sectors') return;
  el.innerHTML = '<div class="grid2">' + Object.entries(Data.SECTORS).map(([n, list]) => {
    const avg = list.reduce((a, s) => a + (Data.quote(s).pct || 0), 0) / list.length;
    return `<div class="card"><div class="dh"><h3 style="margin:0">${n}</h3><span class="${cls(avg)}">板块均值 ${sgn(avg)}%</span></div>
      <table><tbody>${[...list].sort((a, b) => (Data.quote(b).pct || 0) - (Data.quote(a).pct || 0)).map(qrow).join('')}</tbody></table></div>`;
  }).join('') + '</div>';
}
// ===== 财报日历 =====
async function renderEarnings() {
  const el = $('#view-earnings'), days = [...Array(7)].map((_, i) => { const d = new Date(); d.setDate(d.getDate() + i); return d; }).filter(d => d.getDay() % 6);
  const idx = Math.min(state.day, days.length - 1), d = days[idx];
  const tabs = `<div class="daytabs">${days.map((x, i) => `<button data-day="${i}" class="${i === idx ? 'on' : ''}">${x.getMonth() + 1}/${x.getDate()} 周${'日一二三四五六'[x.getDay()]}</button>`).join('')}</div>`;
  el.innerHTML = tabs + '<div class="muted" style="padding:20px">加载中…</div>';
  let E; try { E = await Data.loadEarnings(d); } catch { E = { error: '财报数据加载失败' }; }
  if (state.tab !== 'earnings' || state.day !== idx) return;
  if (E.error) { el.innerHTML = tabs + `<div class="card muted">${E.error}</div>`; return; }
  el.innerHTML = tabs + `<div class="grid2">${['盘前', '盘中', '盘后'].map(k => `<div class="card sess"><h4>${k}发布 · ${E[k].length} 家</h4>
    ${E[k].length ? `<table><thead><tr><th>公司</th><th class="r">预期EPS</th><th class="r">预期营收</th></tr></thead><tbody>${E[k].map(e => `<tr><td><span class="sym" data-go="${esc(e.sym)}">${esc(e.sym)}</span> <span class="muted small">${esc(e.name)}</span></td><td class="r">${e.eps}</td><td class="r">${e.rev}</td></tr>`).join('')}</tbody></table>` : '<div class="muted small">暂无</div>'}</div>`).join('')}</div>
    <div class="muted small">${Data.mode === 'mock' ? '财报数据当前为模拟。' : '数据来自 Finnhub,按预期营收排序,最多显示 45 家。'}</div>`;
}
// ===== 涨跌幅榜 =====
async function renderMovers() {
  const el = $('#view-movers'); loading(el);
  try { await Data.refreshQuotes(universe()); } catch { }
  if (state.tab !== 'movers') return;
  const all = universe().map(Data.quote).filter(q => Number.isFinite(q.price)), top = (a, t) => `<div class="card"><h3 style="margin-top:0">${t}</h3><table><tbody>${a.map(q => qrow(q.sym)).join('')}</tbody></table></div>`;
  const byPct = [...all].sort((a, b) => b.pct - a.pct), byVol = [...all].sort((a, b) => b.volume * b.price - a.volume * a.price);
  el.innerHTML = `<div class="grid2">${top(byPct.slice(0, 10), '涨幅榜')}${top(byPct.slice(-10).reverse(), '跌幅榜')}${top(byVol.slice(0, 10), '成交额榜')}</div>
    <div class="muted small" style="margin-top:8px">当前榜单范围:内置的 ${all.length} 只热门股票(全市场榜单需要付费数据,后续可评估)。</div>`;
}
// ===== 推送提醒 =====
async function renderAlerts() {
  const el = $('#view-alerts');
  el.innerHTML = `<div class="card"><h3 style="margin-top:0">手机推送提醒(第 3 阶段开发)</h3>
    <div class="todo">计划推送三类消息:<br>① 重要实时新闻 ② 你自选股的重要个股新闻 ③ 全球宏观重大新闻(美联储、非农、CPI 等)</div>
    <div class="todo">实现思路:后台程序定时抓取新闻 → 判断是否重要 → 通过手机 App(如 Bark / Telegram)推送给你。网页本身不能 24 小时在后台运行,所以需要后台程序。</div>
    <h3>全球宏观 / 市场快讯 ${Data.mode === 'mock' ? '<span class="badge">模拟</span>' : ''}</h3><ul class="news" id="macroNews"><li class="muted">加载中…</li></ul></div>`;
  let l; try { l = await Data.loadNews(''); } catch { l = { error: '新闻加载失败' }; }
  if (state.tab === 'alerts') $('#macroNews').innerHTML = newsHTML(l);
}
const renderers = { sectors: renderSectors, earnings: renderEarnings, movers: renderMovers, alerts: renderAlerts };
document.addEventListener('click', e => {
  if (e.target.dataset.go) selectStock(e.target.dataset.go);
  if (e.target.dataset.day !== undefined) { state.day = +e.target.dataset.day; renderEarnings(); }
});

// ===== 标签页 / 刷新 =====
function switchTab(t) {
  state.tab = t;
  document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === t));
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('hidden', v.id !== 'view-' + t));
  if (renderers[t]) renderers[t](); else { renderWatch(); renderDetail(); }
}
$('#tabs').addEventListener('click', e => { if (e.target.dataset.tab) switchTab(e.target.dataset.tab); });

const coreSymbols = () => [...Data.INDICES.map(i => i[0]), ...state.watch, state.sel].filter(Boolean);
function setBadge(err) {
  const b = $('#dataMode'); b.textContent = err ? '数据连接异常' : Data.mode === 'live' ? '实时数据' : '模拟数据';
  b.className = 'badge' + (Data.mode === 'live' && !err ? ' live' : '');
}
let left = REFRESH, busy = false;
async function refresh() {
  if (busy) return; busy = true;
  try {
    marketStatus();
    let err = false;
    try { await Data.refreshQuotes([...coreSymbols(), ...(['sectors', 'movers'].includes(state.tab) ? universe() : [])]); } catch { err = true; }
    setBadge(err); renderIndices(); renderWatch();
    if (state.tab === 'watch') {
      const h = $('#dhead'); if (h) h.innerHTML = headHTML(state.sel);   // 只更新报价头部,不打断图表悬停
      const s = state.sel, r = state.range;
      if ((r === '1D' || r === '5D') && state.hover < 0) Data.loadBars(s, r).then(() => { if (state.sel === s && state.range === r && state.hover < 0 && state.tab === 'watch') drawCharts(); }).catch(() => { });
    } else if (renderers[state.tab]) renderers[state.tab]();
  } finally { busy = false; }
}
setInterval(() => { left--; $('#countdown').textContent = Math.max(left, 0); if (left <= 0) { left = REFRESH; refresh(); } }, 1000);
window.addEventListener('resize', () => state.tab === 'watch' && drawCharts());

async function init() {
  if (!location.search.includes('mock')) {
    try { const r = await fetch('/api/status'); if (r.ok && (await r.json()).finnhub !== undefined) Data = LiveData; } catch { }
  }
  document.querySelector('footer').textContent = Data.mode === 'live' ? '仅供学习参考,不构成投资建议。行情来自 Yahoo 财经(非官方接口,可能有延迟),新闻/财报来自 Finnhub。' : '仅供学习参考,不构成投资建议。当前为模拟数据。';
  marketStatus(); let err = false;
  try { await Data.refreshQuotes(coreSymbols()); } catch { err = true; }
  setBadge(err); renderIndices(); renderWatch(); renderDetail(); $('#countdown').textContent = left;
}
init();
