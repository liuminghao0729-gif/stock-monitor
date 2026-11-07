// ===== 工具 =====
const $ = s => document.querySelector(s);
const UP = '#7ed3a4', DOWN = '#ef8a78';           // 美股习惯:涨绿跌红
const REFRESH = 15;                                // 自动刷新间隔(秒)
const MA_DEF = [[5, '#e2c07a'], [10, '#b49ad8'], [20, '#6fc4c9'], [50, '#e29a62'], [100, '#dc8fa8'], [200, '#e9efec']];
let Data = MockData; // 启动时会检查后台,可用则切换为真实数据(网址加 ?mock 可强制用模拟数据)
const fmt = (n, d = 2) => Number.isFinite(n) ? n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }) : '--';
const cls = n => n >= 0 ? 'up' : 'down';
const sgn = (n, d = 2) => Number.isFinite(n) ? (n >= 0 ? '+' : '') + fmt(n, d) : '--';
const big = n => n >= 1e9 ? fmt(n / 1e9) + 'B' : n >= 1e6 ? fmt(n / 1e6) + 'M' : n >= 1e3 ? fmt(n / 1e3) + 'K' : String(n);
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { } }
};


// ===== 周期与状态 =====
const PERIODS = { D: '日K', W: '周K', M: '月K', Q: '季K', Y: '年K' };
const MINUTES = { '1m': '1分', '5m': '5分', '15m': '15分', '1h': '1小时', '4h': '4小时' };
const DEF_COUNT = { D: 120, W: 104, M: 120, Q: 80, Y: 40, '1m': 240, '5m': 160, '15m': 130, '1h': 120, '4h': 100 };
const isIntra = p => p in MINUTES;
const C = { line: 'rgba(255,255,255,.13)', grid: 'rgba(255,255,255,.07)', text: '#a3a8a6', accent: '#cfa76c', tag: 'rgba(52,54,56,.96)' };

const state = {
  watch: store.get('watch', ['AAPL', 'NVDA', 'VOO', 'QQQ']),
  sel: null,
  period: store.get('period', 'D'), minute: store.get('minute', '1m'), type: store.get('ctype', 'candle'),
  ind: store.get('ind2', { ma: [1, 1, 1, 1, 0, 0], boll: 0, chip: 1, vol: 1, macd: 1, rsi: 1 }),
  hover: -1, tab: 'watch', day: 0, dt: 'chart'
};
if (!(state.period in PERIODS) && !(state.period in MINUTES)) state.period = 'D';
if (!(state.minute in MINUTES)) state.minute = '1m';
state.sel = state.watch[0] || 'AAPL';

// ===== 指标计算(对整段历史计算一次,缩放拖动时只切片显示)=====
function sma(a, n) { const o = new Array(a.length).fill(null); let s = 0; for (let i = 0; i < a.length; i++) { s += a[i]; if (i >= n) s -= a[i - n]; if (i >= n - 1) o[i] = s / n; } return o; }
function ema(a, n) { const k = 2 / (n + 1), o = []; a.forEach((v, i) => o.push(i ? v * k + o[i - 1] * (1 - k) : v)); return o; }
function boll(c, n = 20, k = 2) {
  const mid = sma(c, n), up = [], lo = [];
  for (let i = 0; i < c.length; i++) {
    if (mid[i] == null) { up.push(null); lo.push(null); continue; }
    let v = 0; for (let j = i - n + 1; j <= i; j++) v += (c[j] - mid[i]) ** 2;
    const sd = Math.sqrt(v / n); up.push(mid[i] + k * sd); lo.push(mid[i] - k * sd);
  }
  return { mid, up, lo };
}
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
// 筹码分布(估算):把当前窗口内K线的成交量按价格区间摊开,越久远权重越低
function chips(bars, i0, i1, bins = 48) {
  const a = Math.max(i0, i1 - 500), seg = bars.slice(a, i1 + 1); if (!seg.length) return null;
  const lo = Math.min(...seg.map(b => b.l)), hi = Math.max(...seg.map(b => b.h)), step = (hi - lo) / bins || 1, arr = new Array(bins).fill(0);
  seg.forEach((b, i) => {
    const w = Math.pow(.985, seg.length - 1 - i), x = Math.floor((b.l - lo) / step), z = Math.min(bins - 1, Math.floor((b.h - lo) / step)), cnt = z - x + 1;
    for (let k = x; k <= z; k++) arr[k] += b.v * w / cnt;
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
const isIdx = s => Data.INDICES.some(i => i[0] === s);
function renderIndices() {
  $('#indices').innerHTML = Data.INDICES.map(([s, n]) => {
    const q = Data.quote(s);
    return `<div class="idx ${s === state.sel ? 'on' : ''}" data-go="${s}" title="查看${n}图表"><div class="n">${n}</div><div class="p">${fmt(q.price, q.price < 200 ? 2 : 0)}</div><div class="c ${cls(q.pct)}">${sgn(q.pct)}%</div></div>`;
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
function selectStock(s) {
  state.sel = s; state.hover = -1; if (isIdx(s)) state.dt = 'chart'; switchTab('watch'); renderWatch(); renderDetail(); renderIndices();
  if (isIdx(s) && window.innerWidth < 860) setTimeout(() => $('#detail').scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
  Data.refreshQuotes([s]).then(() => { if (state.sel === s) { const h = $('#dhead'); if (h) h.innerHTML = headHTML(s); renderWatch(); } }).catch(() => { });   // 竞争对手等不在自选里的代码
}


// ===== 个股详情 =====
const cn = (n, u = '') => !Number.isFinite(n) ? '--' : n >= 1e8 ? fmt(n / 1e8) + '亿' + u : n >= 1e4 ? fmt(n / 1e4) + '万' + u : fmt(n, 0) + u;
function headHTML(s) {
  const q = Data.quote(s), d = (Data.detail && Data.detail(s)) || {}, dec = Number.isFinite(q.price) ? decOf(q.price) : 2, P = v => Number.isFinite(v) ? fmt(v, dec) : '--';
  const pct = v => Number.isFinite(v) ? fmt(v) + '%' : '--', num = v => Number.isFinite(v) ? fmt(v) : '--';
  const vs = v => !Number.isFinite(v) || !Number.isFinite(q.prev) ? '' : v >= q.prev ? 'up' : 'down';
  const rows = [   // 三列,排列参照 Moomoo
    [['成交额', cn(d.turnover)], ['成交量', cn(q.volume, '股')], ['换手率', pct(d.turnoverRate)], ['52周最高', P(d.wk52h)], ['52周最低', P(d.wk52l)], ['股息率', pct(d.divYield)]],
    [['最高', P(q.high), vs(q.high)], ['最低', P(q.low), vs(q.low)], ['市值', cn(d.mcap)], ['总股本', cn(d.shares)], ['振幅', pct(d.amp)], ['市盈率(TTM)', num(d.pe)]],
    [['今开', P(q.open), vs(q.open)], ['昨收', P(q.prev)], ['平均价', P(d.avg)], ['量比', num(d.volRatio)], ['历史最高', P(d.ath)], ['历史最低', P(d.atl)]]
  ];
  const idx = isIdx(s);
  if (idx) rows.splice(0, 3,   // 指数:没有市值、换手率等,只显示行情类数据
    [['52周最高', P(d.wk52h)], ['52周最低', P(d.wk52l)], ['振幅', pct(d.amp)]],
    [['最高', P(q.high), vs(q.high)], ['最低', P(q.low), vs(q.low)], ['今开', P(q.open), vs(q.open)]],
    [['昨收', P(q.prev)], ['历史最高', P(d.ath)], ['历史最低', P(d.atl)]]);
  const arrow = q.change >= 0 ? '↑' : '↓', open = store.get('statsOpen', true), show = idx ? 3 : open ? 6 : 2;
  return `<div class="dh"><div><h2>${s} <span class="muted" style="font-size:14px;font-weight:400">${esc(q.name)}</span></h2></div>${state.watch.includes(s) || idx ? '' : '<button class="tb on" data-act="addwatch">＋ 加入自选</button>'}</div>
  <div class="px-big ${cls(q.change)}"><span class="big">${P(q.price)}</span><span class="arr">${Number.isFinite(q.price) ? arrow : ''}</span></div>
  <div class="${cls(q.change)} px-sub">${sgn(q.change, dec)} &nbsp; ${sgn(q.pct)}%</div>
  <div class="sgrid">${rows.map(col => `<div class="scol">${col.slice(0, show).map(([l, v, c]) => `<div class="srow"><span class="l">${l}</span><span class="v ${c || ''}">${v}</span></div>`).join('')}</div>`).join('')}</div>
  ${idx ? '' : `<button class="sfold" data-act="stats" title="${open ? '收起' : '展开'}">${open ? '︿' : '﹀'}</button>`}`;
}
async function renderDetail() {
  const s = state.sel; if (!s) { $('#detail').innerHTML = '<div class="muted">请先添加自选股</div>'; return; }
  V = null;
  $('#detail').innerHTML = `<div id="dhead">${headHTML(s)}</div>
  <div class="dtabs" id="dtabs"><button data-dt="chart">图表</button>${isIdx(s) ? '' : '<button data-dt="company">公司</button>'}</div>
  <div id="dchart">
    <div class="legend" id="legend"></div>
    <div class="chartwrap" id="cw"><canvas id="cv"></canvas><div id="cload" class="cload">图表加载中…</div></div>
    <div class="tbar" id="tb"></div>
    <h3>${isIdx(s) ? '市场新闻' : s + ' 相关新闻'}</h3>
    <ul class="news" id="stockNews"><li class="muted">加载中…</li></ul>
  </div>
  <div id="dcompany" class="hidden"></div>`;
  bindChart(); renderToolbar(); loadChart(true); loadStats(s); showDT(state.dt);
  { const q = Data.quote(s); countUp($('.px-big .big'), q.price, Number.isFinite(q.price) ? decOf(q.price) : 2); }
  const stale = () => state.sel !== s || state.tab !== 'watch';
  Data.loadNews(isIdx(s) ? '' : s).then(l => { if (!stale()) $('#stockNews').innerHTML = newsHTML(l); })
    .catch(() => { if (!stale()) $('#stockNews').innerHTML = '<li class="muted">新闻加载失败</li>'; });
}
function showDT(dt) {
  state.dt = dt;
  document.querySelectorAll('#dtabs button').forEach(b => b.classList.toggle('on', b.dataset.dt === dt));
  $('#dchart').classList.toggle('hidden', dt !== 'chart'); $('#dcompany').classList.toggle('hidden', dt !== 'company');
  if (dt === 'chart') drawCharts(); else renderCompany();
}
const REC_COLORS = ['#1f9d6b', '#26c281', '#8b949e', '#f08a4b', '#ef4444'], REC_NAMES = ['强烈买入', '买入', '持有', '卖出', '强烈卖出'];
function recHTML(c) {
  const r = c && Array.isArray(c.rec) && c.rec[0]; if (!r) return '<div class="muted small">暂无数据</div>';
  const v = [r.strongBuy, r.buy, r.hold, r.sell, r.strongSell].map(x => x || 0), tot = v.reduce((a, b) => a + b, 0); if (!tot) return '<div class="muted small">暂无数据</div>';
  const score = (5 * v[0] + 4 * v[1] + 3 * v[2] + 2 * v[3] + v[4]) / tot, label = score >= 4.5 ? '强力推荐' : score >= 3.5 ? '买入' : score >= 2.5 ? '持有' : score >= 1.5 ? '卖出' : '强力卖出';
  return `<div class="rec-h"><b>${tot} 位分析师综合评级</b> <span class="${score >= 3.5 ? 'up' : score >= 2.5 ? '' : 'down'}">${label}</span> <span class="muted small">更新:${esc(r.period || '')}</span></div>
    <div class="recbar">${v.map((n, i) => n ? `<span style="flex:${n};background:${REC_COLORS[i]}" title="${REC_NAMES[i]} ${n}">${n}</span>` : '').join('')}</div>
    <div class="reclegend">${REC_NAMES.map((nm, i) => `<span><i style="background:${REC_COLORS[i]}"></i>${nm} ${v[i]}</span>`).join('')}</div>`;
}
function earnHTML(c) {
  const e = c && Array.isArray(c.earn) ? c.earn.filter(x => x && x.actual != null) : []; if (!e.length) return '<div class="muted small">暂无数据</div>';
  return `<table><thead><tr><th>季度</th><th class="r">预期EPS</th><th class="r">实际EPS</th><th class="r">超预期</th></tr></thead><tbody>${e.map(x => { const sp = x.surprisePercent; return `<tr><td>${esc(x.period || '')}</td><td class="r">${x.estimate == null ? '--' : fmt(x.estimate)}</td><td class="r">${fmt(x.actual)}</td><td class="r ${sp >= 0 ? 'up' : 'down'}">${Number.isFinite(sp) ? sgn(sp) + '%' : '--'}</td></tr>`; }).join('')}</tbody></table>`;
}
const list = a => `<ul class="clist">${(a || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
function companyHTML(s, c) {
  const k = COMPANIES[s], p = (c && c.profile) || {}, q = Data.quote(s);
  const meta = [p.finnhubIndustry, p.exchange, p.ipo ? '上市 ' + p.ipo : '', p.country].filter(Boolean).map(esc).join(' · ');
  const web = /^https?:\/\//.test(p.weburl || '') ? ` · <a href="${p.weburl}" target="_blank" rel="noopener noreferrer">官网</a>` : '';
  const peers = (k && k.comp) || (c && c.peers ? c.peers.filter(x => x !== s).slice(0, 8) : []);
  const chips = peers.map(x => /^[A-Z.]{1,6}$/.test(x) ? `<button class="chip" data-go="${x}">${x}</button>` : `<span class="chip plain">${esc(x)}</span>`).join('');
  const note = c && c.error ? '暂无数据' : '';
  let h = `<div class="csec"><h3>${esc(k ? k.n : q.name)} <span class="muted small">${meta}${web}</span></h3>${k ? `<p class="intro">${esc(k.intro)}</p>` : '<p class="muted">暂无这家公司的详细分析</p>'}</div>`;
  if (k) h += `<div class="csec"><h3>主营业务</h3>${list(k.segs)}</div>`;
  h += `<div class="csec"><h3>分析师评级</h3>${note && !(c && c.rec) ? `<div class="muted small">${note}</div>` : recHTML(c)}</div>`;
  if (peers.length) h += `<div class="csec"><h3>竞争对手</h3><div class="chips">${chips}</div></div>`;
  if (k) {
    h += `<div class="csec"><h3>竞争优势</h3>${list(k.adv)}</div>
      <div class="csec"><h3>护城河</h3><div class="tags">${k.moat.tags.map(t => `<span class="mtag">${esc(t)}</span>`).join('')}</div><p>${esc(k.moat.text)}</p></div>
      <div class="csec"><h3>领先领域</h3>${list(k.lead)}</div>
      <div class="csec"><h3>未来订单 / 需求能见度</h3><p>${esc(k.orders)}</p></div>
      <div class="csec"><h3>主要风险</h3>${list(k.risks)}</div>`;
  }
  h += `<div class="csec"><h3>财报对比(近 4 个季度)</h3>${note && !(c && c.earn) ? `<div class="muted small">${note}</div>` : earnHTML(c)}</div>
    <div class="small cfoot">${k ? `分析内容撰写于 ${COMPANY_ASOF},可能已过时,订单等数字以最新财报为准。` : ''}</div>`;
  return h;
}
async function renderCompany() {
  const s = state.sel, box = $('#dcompany'); if (!box) return;
  box.innerHTML = companyHTML(s, null);
  let c; try { c = await Data.loadCompany(s); } catch { c = { error: 'fail' }; }
  if (state.sel === s && state.dt === 'company' && $('#dcompany')) $('#dcompany').innerHTML = companyHTML(s, c);
}
function loadStats(s) { if (Data.loadDetail) Data.loadDetail(s).then(() => { if (state.sel === s && state.tab === 'watch' && $('#dhead')) $('#dhead').innerHTML = headHTML(s); }).catch(() => { }); }
function newsHTML(list) {
  if (!Array.isArray(list)) return `<li class="muted">${list.error}</li>`;
  if (!list.length) return '<li class="muted">暂无新闻</li>';
  return list.map(n => `<li><span class="tag ${n.hot ? 'hot' : ''}">${n.hot ? '重要' : n.src}</span><div>${/^https?:\/\//.test(n.url || '') ? `<a href="${n.url}" target="_blank" rel="noopener noreferrer" style="color:inherit">${esc(n.title)}</a>` : esc(n.title)}<div class="muted small">${esc(n.src)} · ${n.minsAgo < 60 ? n.minsAgo + ' 分钟前' : Math.round(n.minsAgo / 60) + ' 小时前'}</div></div></li>`).join('');
}
const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ===== 底部工具栏(仿 Moomoo):日K 周K 月K 季K 年K [1分▾]  ...  蜡烛 缩放 指标 =====
const IND_ITEMS = [['ma0', 'MA5', MA_DEF[0][1]], ['ma1', 'MA10', MA_DEF[1][1]], ['ma2', 'MA20', MA_DEF[2][1]], ['ma3', 'MA50', MA_DEF[3][1]], ['ma4', 'MA100', MA_DEF[4][1]], ['ma5', 'MA200', MA_DEF[5][1]], ['boll', 'BOLL(20,2)'], ['chip', '筹码分布(估算)']];
const SUB_ITEMS = [['vol', '成交量'], ['macd', 'MACD(12,26,9)'], ['rsi', 'RSI(6,12,24)']];
const isMA = k => /^ma\d$/.test(k);     // 均线键名 ma0..ma5(注意 macd 不是均线)
const indOn = k => isMA(k) ? state.ind.ma[+k.slice(2)] : state.ind[k];
function renderToolbar() {
  const p = state.period, chk = ([k, n, c]) => `<label ${c ? `style="color:${c}"` : ''}><input type="checkbox" data-ind="${k}" ${indOn(k) ? 'checked' : ''}>${n}</label>`;
  $('#tb').innerHTML = `<div class="tl">${Object.entries(PERIODS).map(([k, n]) => `<button class="tb ${p === k ? 'on' : ''}" data-p="${k}">${n}</button>`).join('')}
    <span class="pwrap"><button class="tb ${isIntra(p) ? 'on' : ''}" data-act="minmenu">${MINUTES[state.minute]} ▾</button>
      <div class="pop hidden" id="popMin">${Object.entries(MINUTES).map(([k, n]) => `<button data-p="${k}" class="${p === k ? 'on' : ''}">${n}</button>`).join('')}</div></span></div>
    <div class="tr"><button class="tb" data-act="type" title="切换蜡烛图 / 折线图">${state.type === 'candle' ? '蜡烛图' : '折线图'}</button>
      <button class="tb ic" data-act="zout" title="缩小">−</button><button class="tb ic" data-act="zin" title="放大">＋</button><button class="tb ic" data-act="reset" title="复位到最新">⟲</button>
      <span class="pwrap"><button class="tb" data-act="indmenu">指标</button>
        <div class="pop right hidden" id="popInd"><div class="pt">主图</div>${IND_ITEMS.map(chk).join('')}<div class="pt">副图</div>${SUB_ITEMS.map(chk).join('')}</div></span></div>`;
}
function syncChecks() { document.querySelectorAll('#popInd input[data-ind]').forEach(i => i.checked = !!indOn(i.dataset.ind)); }
function closePops() { document.querySelectorAll('.pop').forEach(p => p.classList.add('hidden')); }
function setPeriod(p) {
  closePops(); if (p === state.period) return;
  state.period = p; store.set('period', p);
  if (isIntra(p)) { state.minute = p; store.set('minute', p); }
  state.hover = -1; renderToolbar(); loadChart(true);
}
$('#detail').addEventListener('click', e => {
  const dt = e.target.closest('[data-dt]'); if (dt) return showDT(dt.dataset.dt);
  const t = e.target.closest('[data-p],[data-act]'); if (!t) return;
  if (t.dataset.act === 'addwatch') { if (!state.watch.includes(state.sel)) { state.watch.push(state.sel); store.set('watch', state.watch); } $('#dhead').innerHTML = headHTML(state.sel); renderWatch(); return; }
  if (t.dataset.p) return setPeriod(t.dataset.p);
  const a = t.dataset.act, pop = t.parentElement.querySelector('.pop');
  if (a === 'minmenu' || a === 'indmenu') { const was = pop.classList.contains('hidden'); closePops(); pop.classList.toggle('hidden', !was); e.stopPropagation(); return; }
  if (a === 'stats') { store.set('statsOpen', !store.get('statsOpen', true)); $('#dhead').innerHTML = headHTML(state.sel); return; }
  closePops(); if (!V) return;
  if (a === 'type') { state.type = state.type === 'candle' ? 'line' : 'candle'; store.set('ctype', state.type); renderToolbar(); }
  else if (a === 'zin') zoomAt(1 / 1.3, V.L.W / 2);
  else if (a === 'zout') zoomAt(1.3, V.L.W / 2);
  else if (a === 'reset') resetView();
  paint();
});
$('#detail').addEventListener('change', e => {
  const k = e.target.dataset.ind; if (!k) return;
  if (isMA(k)) state.ind.ma[+k.slice(2)] = e.target.checked ? 1 : 0; else state.ind[k] = e.target.checked ? 1 : 0;
  store.set('ind2', state.ind); if (V) { layout(); paint(); }
});
document.addEventListener('click', e => { if (!e.target.closest('.pwrap')) closePops(); });

// ===== 图表:数据、视图(缩放/拖动)、布局 =====
let V = null;                                    // 当前图表数据与布局
const view = { start: 0, count: 100 };           // 可见窗口:第 start 根K线开始,共 count 根(可为小数,左右允许留白)
const ptr = { map: new Map(), drag: null, pinch: null, my: -1, moved: false };
const PL = 4, PR = 58;                           // 绘图区左右边距(右侧放价格轴)

function prepare() {
  const bars = Data.bars(state.sel, state.period).bars.slice();
  if (!isIntra(state.period) && bars.length) {   // 日K及以上:用最新报价实时更新最后一根
    const q = Data.quote(state.sel);
    if (Number.isFinite(q.price)) { const b = { ...bars[bars.length - 1] }; b.c = q.price; b.h = Math.max(b.h, q.price); b.l = Math.min(b.l, q.price); bars[bars.length - 1] = b; }
  }
  const c = bars.map(b => b.c);
  return { bars, ma: MA_DEF.map(([k]) => sma(c, k)), boll: boll(c), rsi: [rsi(c, 6), rsi(c, 12), rsi(c, 24)], macd: macd(c) };
}
async function loadChart(reset) {
  const s = state.sel, p = state.period, ld = $('#cload'), same = () => state.sel === s && state.period === p && state.tab === 'watch';
  if (ld) { ld.style.display = 'block'; ld.textContent = '图表加载中…'; }
  try { await Data.loadBars(s, p); } catch { if (same() && ld) ld.textContent = '图表数据加载失败,稍后会自动重试'; return; }
  if (!same()) return;
  const R = Data.bars(s, p);
  if (!R || !R.bars.length) { if (ld) ld.textContent = '暂无数据'; V = null; return; }
  V = prepare(); if (reset) resetView(); ld.style.display = 'none'; layout(); if (reset) animateReveal(); else paint();
}
const calm = () => window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
function animateReveal() {   // 曲线从左到右"画"出来
  const tok = V; if (!tok) return; if (calm()) { paint(); return; }
  const t0 = performance.now(), dur = 900; tok.reveal = 0; paint();
  (function f(t) { if (V !== tok) return; const k = Math.min(1, (t - t0) / dur); tok.reveal = 1 - Math.pow(1 - k, 3); paint(); if (k < 1) requestAnimationFrame(f); })(t0);
}
let lastShown = null;
function countUp(el, to, dec) {   // 价格数字滚动到新价格
  if (!el || !Number.isFinite(to)) return; const from = Number.isFinite(lastShown) ? lastShown : to; lastShown = to;
  if (calm() || from === to) return; const t0 = performance.now(), dur = 650;
  (function f(t) { const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3); el.textContent = fmt(from + (to - from) * e, dec); if (k < 1 && el.isConnected) requestAnimationFrame(f); })(t0);
}
function resetView() {
  const n = V.bars.length, c0 = Math.min(DEF_COUNT[state.period], n), pad = Math.max(2, Math.round(c0 * .05));
  view.count = c0 + pad; view.start = n - c0; clampView();
}
function clampView() {
  const n = V.bars.length; view.count = Math.max(12, Math.min(Math.max(30, n * 1.15), view.count));
  view.start = Math.max(-view.count * .25, Math.min(n - view.count * .65, view.start));
}
const plotW = () => V.L.W - PL - PR;
function zoomAt(f, mx) {
  const pw = plotW(), a = view.start + (mx - PL) / pw * view.count, n = V.bars.length;
  view.count = Math.max(12, Math.min(Math.max(30, n * 1.15), view.count * f));
  view.start = a - (mx - PL) / pw * view.count; clampView();
}
const idxAt = x => Math.max(0, Math.min(V.bars.length - 1, Math.round(view.start + (x - PL) / (plotW() / view.count) - .5)));
// 数据刷新后保持用户当前看的位置:停在最新处就继续跟随最新,否则按时间对齐
function rebase(oldB, newB) {
  if (!oldB.length || !newB.length) return;
  if (view.start + view.count >= oldB.length - .5) { view.start += newB.length - oldB.length; return; }
  const k = Math.max(0, Math.min(oldB.length - 1, Math.round(view.start))), idx = newB.findIndex(b => b.t === oldB[k].t);
  if (idx >= 0) view.start += idx - k;
}
function refreshChart() {
  if (!V) return; const L = V.L; V = prepare(); V.L = L; clampView(); paint();
}
function drawCharts() { if (V) { layout(); paint(); } }   // 窗口大小变化时重排

function layout() {
  const cv = $('#cv'); if (!cv || !V) return;
  const W = cv.parentElement.clientWidth, dpr = window.devicePixelRatio || 1, mob = W < 520, I = state.ind, anyMA = I.ma.some(x => x);
  const maN = I.ma.filter(x => x).length, lines = (anyMA ? (mob ? Math.ceil(maN / 3) : 1) : 0) + (I.boll ? (mob ? 2 : 1) : 0), panels = [{ id: 'price', h: mob ? 260 : 340, head: 6 + lines * 16 }];
  V.hasVol = V.bars.some(b => b.v > 0);
  [['vol', I.vol && V.hasVol], ['macd', I.macd], ['rsi', I.rsi]].forEach(([id, on]) => on && panels.push({ id, h: mob ? 80 : 96, head: 20 }));
  let y = 0; panels.forEach(p => { p.y = y; y += p.h; });
  const H = y + 22;
  cv.width = W * dpr; cv.height = H * dpr; cv.style.width = W + 'px'; cv.style.height = H + 'px';
  V.L = { W, H, panels, dpr };
}
const decOf = v => v < 1 ? 4 : v < 20 ? 3 : 2;
const fmtT = t => { const p = state.period; return isIntra(p) ? t.slice(5) : (p === 'M' || p === 'Q') ? t.slice(0, 7) : p === 'Y' ? t.slice(0, 4) : t; };
function segs(ctx, parts, x, y, maxW, lh) {
  let cx = x, cy = y, lines = 1; ctx.textAlign = 'left';
  for (const [t, c] of parts) {
    const w = ctx.measureText(t).width + 9;
    if (cx + w > maxW && cx > x) { cx = x; cy += lh; lines++; }
    ctx.fillStyle = c; ctx.fillText(t, cx, cy); cx += w;
  }
  return lines;
}

function paint() {
  const cv = $('#cv'); if (!cv || !V || !V.L) return;
  const { W, H, panels, dpr } = V.L, ctx = cv.getContext('2d'), I = state.ind, B = V.bars, n = B.length;
  const pw = W - PL - PR, cnt = view.count, bw = pw / cnt, st = view.start, X = i => PL + (i - st + .5) * bw;
  const i0 = Math.max(0, Math.floor(st)), i1 = Math.min(n - 1, Math.ceil(st + cnt) - 1);
  const hv = state.hover >= 0 ? Math.min(n - 1, state.hover) : -1, ref = hv >= 0 ? hv : Math.max(0, i1);
  const axisX = W - PR + 5;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const revealing = V.reveal != null && V.reveal < 1; if (revealing) { ctx.save(); ctx.beginPath(); ctx.rect(0, 0, W * V.reveal, H); ctx.clip(); }
  ctx.font = '11px -apple-system,"PingFang SC",sans-serif'; ctx.textBaseline = 'middle';
  V.hits = [];
  const dash = (x0, y0, x1, y1, col, d = [3, 4]) => { ctx.strokeStyle = col; ctx.setLineDash(d); ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke(); ctx.setLineDash([]); };
  const clipPlot = (top, bot) => { ctx.save(); ctx.beginPath(); ctx.rect(PL, top, pw, bot - top); ctx.clip(); };
  const poly = (arr, Y, col, lw = 1.2) => {
    ctx.strokeStyle = col; ctx.lineWidth = lw; ctx.beginPath(); let on = false;
    for (let i = Math.max(0, i0 - 1); i <= Math.min(n - 1, i1 + 1); i++) { const v = arr[i]; if (v == null) { on = false; continue; } on ? ctx.lineTo(X(i), Y(v)) : (ctx.moveTo(X(i), Y(v)), on = true); }
    ctx.stroke(); ctx.lineWidth = 1;
  };
  const axisLabel = (txt, y, bg, fg = '#fff') => { ctx.font = '11px sans-serif'; const w = ctx.measureText(txt).width + 8; ctx.fillStyle = bg; ctx.fillRect(W - PR + 1, y - 8, w, 16); ctx.fillStyle = fg; ctx.textAlign = 'left'; ctx.fillText(txt, W - PR + 5, y); };

  panels.forEach(p => {
    const top = p.y + p.head, bot = p.y + p.h - 4;
    ctx.strokeStyle = C.line; ctx.beginPath(); ctx.moveTo(0, p.y + .5); ctx.lineTo(W, p.y + .5); ctx.stroke();
    let Y, lo, hi;
    const scale = (l, h) => { lo = l; hi = h; Y = v => top + (1 - (v - lo) / (hi - lo || 1)) * (bot - top); p.inv = y => lo + (1 - (y - top) / (bot - top)) * (hi - lo); };
    const grid = (vals, f) => vals.forEach(v => { const y = Y(v); dash(PL, y, W - PR, y, C.grid); ctx.fillStyle = C.text; ctx.textAlign = 'left'; ctx.fillText(f(v), axisX, y); });

    if (p.id === 'price') {
      let l = Infinity, h = -Infinity; for (let i = i0; i <= i1; i++) { l = Math.min(l, B[i].l); h = Math.max(h, B[i].h); }
      if (!isFinite(l)) { l = 0; h = 1; } const pad = (h - l) * .08 || h * .01 || 1; scale(l >= 0 ? Math.max(0, l - pad) : l - pad, h + pad);   // 价格不会为负
      const dec = decOf(B[ref].c); p.dec = dec; p.fv = v => fmt(v, dec);
      grid([0, 1, 2, 3, 4].map(k => lo + (hi - lo) * k / 4), p.fv);
      const last = B[n - 1].c, prev = n > 1 ? B[n - 2].c : B[n - 1].o;
      clipPlot(top, bot);
      if (I.chip && V.hasVol) {   // 筹码分布(估算),叠加在绘图区右侧
        const c = chips(B, i0, i1); if (c) {
          const mx = Math.max(...c.arr), maxLen = Math.min(110, pw * .28), ref0 = B[i1].c;
          c.arr.forEach((v, k) => { const pr = c.lo + (k + .5) * c.step, y = Y(pr), bh = Math.max(Math.abs(Y(pr + c.step) - y), 1), len = v / mx * maxLen;
            ctx.fillStyle = pr <= ref0 ? 'rgba(126,211,164,.30)' : 'rgba(239,138,120,.30)'; ctx.fillRect(W - PR - len, y - bh / 2, len, bh - .5); });
          ctx.fillStyle = C.text; ctx.textAlign = 'right'; ctx.fillText('筹码分布', W - PR - 4, top + 8);
        }
      }
      if (state.type === 'candle' && bw >= 2.2) {
        const w = Math.min(Math.max(1, Math.floor(bw * .7)), 24);
        for (let i = Math.max(0, i0 - 1); i <= Math.min(n - 1, i1 + 1); i++) {
          const b = B[i], x = X(i), col = b.c >= b.o ? UP : DOWN; ctx.strokeStyle = ctx.fillStyle = col;
          ctx.beginPath(); ctx.moveTo(x, Y(b.h)); ctx.lineTo(x, Y(b.l)); ctx.stroke();
          ctx.fillRect(Math.round(x - w / 2), Math.min(Y(b.o), Y(b.c)), w, Math.max(1, Math.abs(Y(b.o) - Y(b.c))));
        }
      } else if (state.type === 'candle' && bw >= .6) {
        for (let i = Math.max(0, i0 - 1); i <= Math.min(n - 1, i1 + 1); i++) { const b = B[i], x = X(i); ctx.strokeStyle = b.c >= b.o ? UP : DOWN; ctx.beginPath(); ctx.moveTo(x, Y(b.h)); ctx.lineTo(x, Y(b.l)); ctx.stroke(); }
      } else {
        poly(B.map(b => b.c), Y, C.accent, 1.6);
      }
      V.ma.forEach((a, k) => I.ma[k] && poly(a, Y, MA_DEF[k][1]));
      if (I.boll) { poly(V.boll.mid, Y, '#f5c542'); poly(V.boll.up, Y, '#ff6fa8'); poly(V.boll.lo, Y, '#35c5e8'); }
      // 窗口内最高/最低价标注
      let ih = i0, il = i0; for (let i = i0; i <= i1; i++) { if (B[i].h > B[ih].h) ih = i; if (B[i].l < B[il].l) il = i; }
      ctx.font = '11px sans-serif'; ctx.fillStyle = '#c9d1d9';
      [[ih, B[ih].h, -9], [il, B[il].l, 10]].forEach(([i, v, dy]) => { const x = X(i), right = x < W / 2; ctx.textAlign = right ? 'left' : 'right'; ctx.fillText((right ? '← ' : '') + p.fv(v) + (right ? '' : ' →'), x + (right ? 5 : -5), Y(v) + dy); });
      ctx.restore();
      // 现价虚线 + 价格标签
      const ly = Math.max(top, Math.min(bot, Y(last))); dash(PL, ly, W - PR, ly, last >= prev ? UP : DOWN, [4, 3]); axisLabel(p.fv(last), ly, last >= prev ? UP : DOWN);
      // 左上角:均线 / BOLL 数值
      ctx.font = '11px sans-serif'; let yy = p.y + 11;
      const maParts = []; V.ma.forEach((a, k) => { if (I.ma[k] && a[ref] != null) maParts.push([`MA${MA_DEF[k][0]}:${p.fv(a[ref])}`, MA_DEF[k][1]]); });
      if (maParts.length) yy += 16 * segs(ctx, maParts, PL + 4, yy, W - PR, 16);
      if (I.boll && V.boll.mid[ref] != null) segs(ctx, [['BOLL', C.text], [`MID:${p.fv(V.boll.mid[ref])}`, '#f5c542'], [`UPPER:${p.fv(V.boll.up[ref])}`, '#ff6fa8'], [`LOWER:${p.fv(V.boll.lo[ref])}`, '#35c5e8']], PL + 4, yy, W - PR, 16);
    } else if (p.id === 'vol') {
      let mx = 0; for (let i = i0; i <= i1; i++) mx = Math.max(mx, B[i].v); mx = mx || 1; scale(0, mx * 1.08); p.fv = v => big(Math.round(v));
      grid([mx], p.fv); clipPlot(top, bot);
      for (let i = Math.max(0, i0 - 1); i <= Math.min(n - 1, i1 + 1); i++) { const b = B[i], w = Math.min(Math.max(1, Math.floor(bw * .7)), 24); ctx.fillStyle = b.c >= b.o ? 'rgba(126,211,164,.75)' : 'rgba(239,138,120,.75)'; ctx.fillRect(Math.round(X(i) - w / 2), Y(b.v), w, Y(0) - Y(b.v)); }
      ctx.restore(); ctx.font = '11px sans-serif';
      segs(ctx, [['成交量', C.text], [`VOL:${big(B[ref].v)}`, '#e6a23c']], PL + 4, p.y + 11, W - PR - 20, 16);
    } else if (p.id === 'macd') {
      let m = 0; for (let i = i0; i <= i1; i++) [V.macd.dif[i], V.macd.dea[i], V.macd.hist[i]].forEach(v => v != null && (m = Math.max(m, Math.abs(v)))); m = m || 1; scale(-m * 1.1, m * 1.1); p.fv = v => fmt(v, 3);
      grid([-m * .8, 0, m * .8], p.fv); clipPlot(top, bot);
      for (let i = Math.max(0, i0 - 1); i <= Math.min(n - 1, i1 + 1); i++) { const v = V.macd.hist[i], w = Math.min(Math.max(1, Math.floor(bw * .5)), 14); ctx.fillStyle = v >= 0 ? 'rgba(126,211,164,.8)' : 'rgba(239,138,120,.8)'; ctx.fillRect(Math.round(X(i) - w / 2), Math.min(Y(0), Y(v)), w, Math.max(1, Math.abs(Y(v) - Y(0)))); }
      poly(V.macd.dif, Y, '#f5c542'); poly(V.macd.dea, Y, '#35c5e8'); ctx.restore(); ctx.font = '11px sans-serif';
      segs(ctx, [['MACD(12,26,9)', C.text], [`DIF:${fmt(V.macd.dif[ref], 3)}`, '#f5c542'], [`DEA:${fmt(V.macd.dea[ref], 3)}`, '#35c5e8'], [`MACD:${fmt(V.macd.hist[ref], 3)}`, V.macd.hist[ref] >= 0 ? UP : DOWN]], PL + 4, p.y + 11, W - PR - 20, 16);
    } else if (p.id === 'rsi') {
      scale(0, 100); p.fv = v => fmt(v, 1); grid([30, 50, 70], v => String(v)); clipPlot(top, bot);
      const rc = ['#ff9a3c', '#4c8dff', '#b57bee']; V.rsi.forEach((a, k) => poly(a, Y, rc[k], 1.1)); ctx.restore(); ctx.font = '11px sans-serif';
      segs(ctx, [['RSI', C.text], ...[6, 12, 24].map((nn, k) => [`RSI${nn}:${V.rsi[k][ref] == null ? '--' : fmt(V.rsi[k][ref], 1)}`, rc[k]])], PL + 4, p.y + 11, W - PR - 20, 16);
    }
    if (p.id !== 'price') {   // 副图右上角 × 关闭按钮
      const cx = W - PR - 12, cy = p.y + 10; ctx.fillStyle = C.text; ctx.textAlign = 'center'; ctx.font = '14px sans-serif'; ctx.fillText('×', cx, cy); ctx.font = '11px sans-serif';
      V.hits.push({ x0: cx - 10, x1: cx + 10, y0: p.y, y1: p.y + 20, id: p.id });
    }
  });

  // 底部时间轴
  const ay = H - 11, nt = Math.max(2, Math.floor(pw / 125)); ctx.fillStyle = C.text; ctx.textAlign = 'center';
  for (let k = 0; k < nt; k++) { const i = Math.max(0, Math.min(n - 1, Math.round(st + (k + .5) / nt * cnt - .5))), x = Math.max(40, Math.min(W - PR - 40, X(i))); ctx.fillText(fmtT(B[i].t), x, ay); }

  // 十字光标 + 轴上数值标签
  if (hv >= 0) {
    const x = X(hv); dash(x, 0, x, H - 22, 'rgba(239,244,241,.4)');
    const p = panels.find(q => ptr.my >= q.y + q.head && ptr.my <= q.y + q.h);
    if (p && ptr.my >= 0) { dash(PL, ptr.my, W - PR, ptr.my, 'rgba(239,244,241,.4)'); axisLabel(p.fv(p.inv(ptr.my)), ptr.my, C.tag); }
    const tt = B[hv].t; ctx.font = '11px sans-serif'; const w = ctx.measureText(tt).width + 12, bx = Math.max(0, Math.min(W - PR - w, x - w / 2));
    ctx.fillStyle = C.tag; ctx.fillRect(bx, H - 21, w, 18); ctx.fillStyle = '#fff'; ctx.textAlign = 'center'; ctx.fillText(tt, bx + w / 2, H - 11);
  }
  if (revealing) ctx.restore();
  // 顶部 OHLC 图例
  const b = B[ref], pc = ref > 0 ? B[ref - 1].c : b.o, chg = b.c - pc, d = decOf(b.c);
  $('#legend').innerHTML = `<span class="muted">${b.t}</span> 开 ${fmt(b.o, d)} 高 ${fmt(b.h, d)} 低 ${fmt(b.l, d)} <b class="${cls(chg)}">收 ${fmt(b.c, d)}</b> <span class="${cls(chg)}">${sgn(chg, d)} (${sgn(pc ? chg / pc * 100 : 0)}%)</span> 量 ${big(b.v)}`;
}

// ===== 图表交互:滚轮缩放、拖动、双指缩放、点按 =====
function bindChart() {
  const cv = $('#cv'); cv.style.touchAction = 'pan-y'; cv.style.cursor = 'crosshair';
  const pos = e => { const r = cv.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
  const startDrag = q => { ptr.drag = { x: q.x, start: view.start }; };
  cv.addEventListener('pointerdown', e => {
    if (!V) return; try { cv.setPointerCapture(e.pointerId); } catch { } const q = pos(e); ptr.map.set(e.pointerId, q); ptr.moved = false;
    if (ptr.map.size === 1) startDrag(q);
    else if (ptr.map.size === 2) { const [a, b] = [...ptr.map.values()]; ptr.pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) }; ptr.drag = null; }
  });
  cv.addEventListener('pointermove', e => {
    if (!V) return; const q = pos(e), had = ptr.map.has(e.pointerId); if (had) ptr.map.set(e.pointerId, q);
    if (ptr.pinch && ptr.map.size === 2) {
      const [a, b] = [...ptr.map.values()], d = Math.hypot(a.x - b.x, a.y - b.y); if (d > 5) { zoomAt(ptr.pinch.d / d, (a.x + b.x) / 2); ptr.pinch.d = d; } ptr.moved = true; state.hover = -1; paint();
    } else if (ptr.drag && had && (e.pointerType !== 'mouse' || (e.buttons & 1))) {
      const dx = q.x - ptr.drag.x; if (Math.abs(dx) > 3) ptr.moved = true;
      if (ptr.moved) { cv.style.cursor = 'grabbing'; state.hover = -1; view.start = ptr.drag.start - dx / (plotW() / view.count); clampView(); paint(); }
    } else if (e.pointerType === 'mouse') { ptr.my = q.y; state.hover = idxAt(q.x); paint(); }
  });
  const up = e => {
    if (!V) return; ptr.map.delete(e.pointerId); cv.style.cursor = 'crosshair';
    if (ptr.map.size < 2) ptr.pinch = null;
    if (ptr.map.size === 1) { startDrag([...ptr.map.values()][0]); ptr.moved = true; return; }
    if (ptr.map.size === 0) {
      const q = pos(e);
      if (e.type === 'pointerup' && !ptr.moved) {
        const hit = (V.hits || []).find(h => q.x >= h.x0 && q.x <= h.x1 && q.y >= h.y0 && q.y <= h.y1);
        if (hit) { state.ind[hit.id] = 0; store.set('ind2', state.ind); syncChecks(); layout(); state.hover = -1; paint(); }
        else if (e.pointerType !== 'mouse') { state.hover = state.hover >= 0 && Math.abs(state.hover - idxAt(q.x)) < 1 ? -1 : idxAt(q.x); ptr.my = q.y; paint(); }
      }
      ptr.drag = null;
    }
  };
  cv.addEventListener('pointerup', up); cv.addEventListener('pointercancel', up);
  cv.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse' && !ptr.drag) { state.hover = -1; ptr.my = -1; if (V) paint(); } });
  cv.addEventListener('wheel', e => {
    if (!V) return; e.preventDefault(); const q = pos(e);
    if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) { view.start += e.deltaX / (plotW() / view.count); clampView(); }
    else zoomAt(Math.exp(e.deltaY * (e.ctrlKey ? .01 : .0015)), q.x);
    paint();
  }, { passive: false });
  cv.addEventListener('dblclick', () => { if (V) { resetView(); paint(); } });
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
    ${E[k].length ? `<table><thead><tr><th>公司</th><th class="r">预期EPS</th><th class="r">预期营收</th></tr></thead><tbody>${E[k].map(e => `<tr><td><span class="sym" data-go="${esc(e.sym)}">${esc(e.sym)}</span> <span class="muted small">${esc(e.name)}</span></td><td class="r">${e.eps}</td><td class="r">${e.rev}</td></tr>`).join('')}</tbody></table>` : '<div class="muted small">暂无</div>'}</div>`).join('')}</div>`;
}
// ===== 涨跌幅榜 =====
async function renderMovers() {
  const el = $('#view-movers'); loading(el);
  try { await Data.refreshQuotes(universe()); } catch { }
  if (state.tab !== 'movers') return;
  const all = universe().map(Data.quote).filter(q => Number.isFinite(q.price)), top = (a, t) => `<div class="card"><h3 style="margin-top:0">${t}</h3><table><tbody>${a.map(q => qrow(q.sym)).join('')}</tbody></table></div>`;
  const byPct = [...all].sort((a, b) => b.pct - a.pct), byVol = [...all].sort((a, b) => b.volume * b.price - a.volume * a.price);
  el.innerHTML = `<div class="grid2">${top(byPct.slice(0, 10), '涨幅榜')}${top(byPct.slice(-10).reverse(), '跌幅榜')}${top(byVol.slice(0, 10), '成交额榜')}</div>`;
}
// ===== 推送提醒 =====
async function renderAlerts() {
  const el = $('#view-alerts');
  el.innerHTML = `<div class="card"><h3 style="margin-top:0">市场快讯</h3><ul class="news" id="macroNews"><li class="muted">加载中…</li></ul></div>`;
  let l; try { l = await Data.loadNews(''); } catch { l = { error: '新闻加载失败' }; }
  if (state.tab === 'alerts') $('#macroNews').innerHTML = newsHTML(l);
}
const renderers = { sectors: renderSectors, earnings: renderEarnings, movers: renderMovers, alerts: renderAlerts };
document.addEventListener('click', e => {
  const go = e.target.closest('[data-go]'); if (go) selectStock(go.dataset.go);
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
      loadStats(state.sel);
      const s = state.sel, p = state.period, calm = () => state.sel === s && state.period === p && state.tab === 'watch' && state.hover < 0 && !ptr.drag && V;
      if (calm()) {
        if (isIntra(p)) {   // 分钟周期:重新取最新K线,并保持你当前看的位置
          const old = V.bars;
          Data.loadBars(s, p).then(() => { if (calm()) { rebase(old, Data.bars(s, p).bars); refreshChart(); } }).catch(() => { });
        } else refreshChart();   // 日K及以上:用最新报价更新最后一根
      }
    } else if (renderers[state.tab]) renderers[state.tab]();
  } finally { busy = false; }
}
setInterval(() => { left--; $('#countdown').textContent = Math.max(left, 0); if (left <= 0) { left = REFRESH; refresh(); } }, 1000);
window.addEventListener('resize', () => state.tab === 'watch' && drawCharts());

async function init() {
  if (!location.search.includes('mock')) {
    try { const r = await fetch('/api/status'); if (r.ok && (await r.json()).finnhub !== undefined) Data = LiveData; } catch { }
  }
  marketStatus(); let err = false;
  try { await Data.refreshQuotes(coreSymbols()); } catch { err = true; }
  setBadge(err); renderIndices(); renderWatch(); renderDetail(); $('#countdown').textContent = left;
}
init();
