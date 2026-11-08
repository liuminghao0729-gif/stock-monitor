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
  ind: Object.assign({ ma: [1, 1, 1, 1, 0, 0], boll: 0, chip: 1, vol: 1, macd: 1, rsi: 1, sr: 1, trend: 1, pat: 1, sig: 1 }, store.get('ind2', {})),
  hover: -1, tab: 'watch', day: 0, dt: 'chart'
};
if (!(state.period in PERIODS) && !(state.period in MINUTES)) state.period = 'D';
if (!(state.minute in MINUTES)) state.minute = '1m';
state.sel = state.watch[0] || 'AAPL';
if (store.get('indv', 0) < 3) { Object.assign(state.ind, { sr: 1, trend: 1, pat: 1 }); store.set('ind2', state.ind); store.set('indv', 3); }   // 版本 3:支撑压力、趋势线、形态识别默认开启(一次性重置旧设置;之后你在菜单里的开关会被记住)

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
  }).join('') || '<div class="muted small" style="padding:10px">还没有自选股,到「看盘」里搜索添加。</div>';
}
$('#watchList').addEventListener('click', e => {
  const del = e.target.dataset.del;
  if (del) { state.watch = state.watch.filter(x => x !== del); store.set('watch', state.watch); if (state.sel === del) state.sel = state.watch[0]; renderWatch(); renderDetail(); return; }
  const row = e.target.closest('.wrow'); if (row) selectStock(row.dataset.s);
});
// ----- 搜索联想:输入代码或公司名(中文也行),下面列出相关股票/ETF,点一下即加入自选并打开 -----
const ZH_ALIAS = { 甲骨文: 'ORCL', 特斯拉: 'TSLA', 亚马逊: 'AMZN', 谷歌: 'GOOGL', 脸书: 'META', 奈飞: 'NFLX', 台积电: 'TSM', 美光: 'MU', 英特尔: 'INTC', 高通: 'QCOM', 博通: 'AVGO', 伯克希尔: 'BRK-B', 可口可乐: 'KO', 迪士尼: 'DIS', 波音: 'BA', 摩根大通: 'JPM', 沃尔玛: 'WMT', 好市多: 'COST', 阿里巴巴: 'BABA', 拼多多: 'PDD', 英伟达: 'NVDA', 苹果: 'AAPL', 微软: 'MSFT', 超微: 'AMD', 帕兰提尔: 'PLTR', 奥多比: 'ADBE', 星巴克: 'SBUX', 耐克: 'NKE', 麦当劳: 'MCD', 辉瑞: 'PFE', 礼来: 'LLY', 联合健康: 'UNH', 埃克森美孚: 'XOM', 赛富时: 'CRM', 优步: 'UBER', 戴尔: 'DELL', 美国银行: 'BAC', 高盛: 'GS', 百事: 'PEP', 宝洁: 'PG', 强生: 'JNJ', 英特尔公司: 'INTC', 瑞幸: 'LKNCY', 蔚来: 'NIO', 小鹏: 'XPEV', 理想: 'LI', 百度: 'BIDU', 京东: 'JD', 网易: 'NTES', 哔哩哔哩: 'BILI', 苹果公司: 'AAPL' };
const zhName = s => (COMPANIES[s] && COMPANIES[s].n) || Object.keys(ZH_ALIAS).find(k => ZH_ALIAS[k] === s) || '';
let suggSeq = 0, suggItems = [], suggOn = -1, suggTimer = 0;
const hideSugg = () => { $('#sugg').classList.add('hidden'); suggItems = []; suggOn = -1; };
function paintSugg() {
  const box = $('#sugg');
  if (!suggItems.length) { box.classList.add('hidden'); return; }
  box.innerHTML = suggItems.map((x, i) => `<div class="sg ${i === suggOn ? 'on' : ''}" data-i="${i}"><b>${esc(x.sym)}</b><span class="nm">${esc(zhName(x.sym) ? zhName(x.sym) + ' · ' : '')}${esc(x.name)}</span><span>${state.watch.includes(x.sym) ? '<span class="in">已在自选</span>' : `<span class="tg">${x.type === 'ETF' ? 'ETF' : '股票'}</span>`}</span></div>`).join('');
  box.classList.remove('hidden');
}
async function runSearch(q) {
  const my = ++suggSeq; q = q.trim(); if (!q) { hideSugg(); return; }
  const zh = /[\u4e00-\u9fa5]/.test(q); let seeds = [];
  if (zh) { const names = { ...ZH_ALIAS }; Object.keys(COMPANIES).forEach(k => { if (COMPANIES[k].n) names[COMPANIES[k].n] = k; });
    seeds = [...new Set(Object.keys(names).filter(n => n.includes(q) || q.includes(n)).map(n => names[n]))].slice(0, 3); if (!seeds.length) { suggItems = []; paintSugg(); $('#addMsg').textContent = '中文名暂只支持常见公司,可以直接输入英文代码或英文名'; return; } }
  let items = [];
  try { for (const k of (zh ? seeds : [q])) { const r = await Data.search(k); (r.items || []).forEach(x => { if (!items.some(y => y.sym === x.sym)) items.push(x); }); } } catch { }
  if (my !== suggSeq) return;
  if (zh) items = [...seeds.map(s => items.find(x => x.sym === s) || { sym: s, name: s, type: 'EQUITY' }), ...items.filter(x => !seeds.includes(x.sym))];
  suggItems = items.slice(0, 8); suggOn = -1; $('#addMsg').textContent = suggItems.length ? '' : '没有找到,试试英文代码或英文公司名'; paintSugg();
}
async function addPick(s) {
  hideSugg(); $('#addInput').value = ''; $('#addMsg').textContent = '';
  let isNew = !state.watch.includes(s);
  if (isNew) { let ok = false; try { ok = await Data.validate(s); } catch { } if (!ok) { $('#addMsg').textContent = `暂时拿不到 ${s} 的行情`; return; } state.watch.push(s); store.set('watch', state.watch); }
  selectStock(s);
  $('#addMsg').textContent = isNew ? `已把 ${s} 加入「自选股」` : `${s} 已在自选股中`; setTimeout(() => { if ($('#addMsg').textContent.includes(s)) $('#addMsg').textContent = ''; }, 3000);
}
$('#addInput').addEventListener('input', e => { clearTimeout(suggTimer); suggTimer = setTimeout(() => runSearch(e.target.value), 220); });
$('#addInput').addEventListener('keydown', e => {
  if (!suggItems.length) return;
  if (e.key === 'ArrowDown') { e.preventDefault(); suggOn = (suggOn + 1) % suggItems.length; paintSugg(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); suggOn = (suggOn - 1 + suggItems.length) % suggItems.length; paintSugg(); }
  else if (e.key === 'Escape') hideSugg();
});
$('#sugg').addEventListener('mousedown', e => { e.preventDefault(); const r = e.target.closest('.sg'); if (r) addPick(suggItems[+r.dataset.i].sym); });
document.addEventListener('click', e => { if (!e.target.closest('#searchBox')) hideSugg(); });
$('#addForm').addEventListener('submit', async e => {
  e.preventDefault();
  const raw = $('#addInput').value.trim(), s = raw.toUpperCase(); if (!raw) return;
  if (suggOn >= 0) return addPick(suggItems[suggOn].sym);
  const exact = suggItems.find(x => x.sym === s); if (exact) return addPick(exact.sym);
  if (suggItems.length) return addPick(suggItems[0].sym);             // 没选就取第一条最相关的
  if (/^[A-Z.\-]{1,8}$/.test(s)) return addPick(s);                    // 联想没出来时按代码直接试
  $('#addMsg').textContent = '没有找到,试试英文代码或英文公司名';
});
function selectStock(s) {
  state.sel = s; state.hover = -1; if (isIdx(s)) state.dt = 'chart'; hideSugg(); switchTab('watch'); renderWatch(); renderDetail(); renderIndices();
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
function targetHTML(c) {
  const t = c && c.target; if (!t || !t.avg) return '<div class="muted small">暂无数据</div>';
  const q = Data.quote(state.sel), px = q && q.price, lo = t.low, hi = t.high, span = hi - lo;
  const pos = v => span > 0 ? Math.max(0, Math.min(100, (v - lo) / span * 100)) : 50;
  const up = Number.isFinite(px) && px ? (t.avg / px - 1) * 100 : NaN;
  return `<div class="tgt-h"><span>平均目标价 <b>${fmt(t.avg)}</b></span>${Number.isFinite(up) ? `<span class="${cls(up)}">较现价 ${sgn(up)}%</span>` : ''}<span class="muted small">${t.n ? '近一季度 ' + t.n + ' 家机构' : ''}</span></div>
    <div class="tgt-bar"><i style="left:${pos(t.avg)}%" class="avg"></i>${Number.isFinite(px) && px >= lo && px <= hi ? `<i style="left:${pos(px)}%" class="now"></i>` : ''}</div>
    <div class="tgt-n"><span>最低 ${fmt(lo)}</span><span>中位 ${fmt(t.median)}</span><span>最高 ${fmt(hi)}</span></div>`;
}
const GRADE_ACT = { upgrade: ['上调', 'up'], downgrade: ['下调', 'down'], initialize: ['首次覆盖', ''], maintain: ['维持', 'muted'], reiterate: ['重申', 'muted'] };
function gradesHTML(c) {
  const g = c && Array.isArray(c.grades) ? c.grades : []; if (!g.length) return '<div class="muted small">暂无数据</div>';
  return `<table><thead><tr><th>日期</th><th>机构</th><th>评级变化</th><th class="r">动作</th></tr></thead><tbody>${g.map(x => { const a = GRADE_ACT[x.action] || [x.action || '', 'muted'];
    return `<tr><td class="muted small">${esc(x.date || '')}</td><td>${esc(x.firm || '')}</td><td>${x.from && x.from !== x.to ? esc(x.from) + ' → ' : ''}${esc(x.to || '')}</td><td class="r ${a[1]}">${a[0]}</td></tr>`; }).join('')}</tbody></table>`;
}
function backlogHTML(c) {
  const b = c && Array.isArray(c.backlog) ? c.backlog : []; if (!b.length) return '';
  const last = b[b.length - 1], prev = b.length > 1 ? b[b.length - 2] : null, g = prev && prev.val ? (last.val / prev.val - 1) * 100 : NaN;
  return `<div class="backlog"><b>${(last.val / 1e9).toFixed(1)}B 美元</b> <span class="muted small">截至 ${esc(last.end)} · 财报披露的剩余履约义务(已签约、尚未确认收入)</span>${Number.isFinite(g) ? ` <span class="${cls(g)}">较上期 ${sgn(g, 1)}%</span>` : ''}
    <div class="muted small">近几期:${b.map(x => esc(x.end.slice(0, 7)) + ' ' + (x.val / 1e9).toFixed(1) + 'B').join(' → ')}</div></div>`;
}
const bigN = n => !Number.isFinite(n) ? '--' : Math.abs(n) >= 1e12 ? (n / 1e12).toFixed(2) + 'T' : Math.abs(n) >= 1e9 ? (n / 1e9).toFixed(2) + 'B' : Math.abs(n) >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : Math.abs(n) >= 1e3 ? (n / 1e3).toFixed(1) + 'K' : String(n);
const pcN = (n, d = 1) => Number.isFinite(n) ? (n * 100).toFixed(d) + '%' : '--';
function extraHTML(c) {
  const x = c && c.extra; if (!x) return '';
  let h = '';
  if (x.stats) { const t = x.stats, cell = (l, v) => `<div><span class="muted small">${l}</span><b>${v}</b></div>`;
    h += `<div class="csec"><h3>关键指标</h3><div class="kv">${cell('空头占流通股', pcN(t.shortPercentOfFloat, 2))}${cell('空头回补天数', Number.isFinite(t.shortRatio) ? fmt(t.shortRatio, 1) : '--')}${cell('预期市盈率', fmt(t.forwardPE, 1))}${cell('PEG', fmt(t.pegRatio, 2))}${cell('净利率', pcN(t.profitMargins))}${cell('Beta', fmt(t.beta, 2))}${cell('流通股', bigN(t.floatShares))}${cell('预期每股收益', fmt(t.forwardEps, 2))}</div></div>`; }
  if (x.events) { const e = x.events; h += `<div class="csec"><h3>近期事件</h3><div class="kv">${e.earn ? `<div><span class="muted small">下次财报${e.earnEst ? '(预估)' : ''}</span><b>${esc(e.earn)}</b></div>` : ''}${e.exDiv ? `<div><span class="muted small">除息日</span><b>${esc(e.exDiv)}</b></div>` : ''}${e.div ? `<div><span class="muted small">派息日</span><b>${esc(e.div)}</b></div>` : ''}</div></div>`; }
  if (x.trend) h += `<div class="csec"><h3>分析师盈利预测</h3><table><thead><tr><th>期间</th><th class="r">EPS 预期</th><th class="r">区间</th><th class="r">EPS 同比</th><th class="r">营收预期</th><th class="r">机构数</th></tr></thead><tbody>${x.trend.map(t => `<tr><td>${esc(t.label)} <span class="muted small">${esc(t.end || '')}</span></td><td class="r">${fmt(t.eps)}</td><td class="r muted small">${fmt(t.epsLow)} – ${fmt(t.epsHigh)}</td><td class="r ${cls(t.epsGrowth)}">${Number.isFinite(t.epsGrowth) ? sgn(t.epsGrowth * 100, 1) + '%' : '--'}</td><td class="r">${bigN(t.rev)}</td><td class="r muted">${t.n || '--'}</td></tr>`).join('')}</tbody></table></div>`;
  if (x.holders) { const o = x.holders; h += `<div class="csec"><h3>持股结构</h3><div class="kv"><div><span class="muted small">机构持股</span><b>${pcN(o.inst)}</b></div><div><span class="muted small">内部人持股</span><b>${pcN(o.insiders, 2)}</b></div><div><span class="muted small">机构数量</span><b>${o.count ? o.count.toLocaleString('en-US') : '--'}</b></div></div>
    ${o.top.length ? `<table><thead><tr><th>前几大机构</th><th class="r">占比</th><th class="r">季度变化</th></tr></thead><tbody>${o.top.map(i => `<tr><td>${esc(i.org || '')}</td><td class="r">${pcN(i.pct, 2)}</td><td class="r ${cls(i.chg)}">${Number.isFinite(i.chg) ? (i.chg >= 0 ? '+' : '') + (i.chg * 100).toFixed(2) + '%' : '--'}</td></tr>`).join('')}</tbody></table>` : ''}</div>`; }
  if (x.insiders) { const n = x.insiders.net, l = x.insiders.list; h += `<div class="csec"><h3>内部人交易</h3>${n ? `<div class="small" style="margin-bottom:8px">近 ${esc(n.period || '6m').replace('m', ' 个月')}:<span class="up">买入 ${n.buyN || 0} 笔 / ${bigN(n.buy)} 股</span> · <span class="down">卖出 ${n.sellN || 0} 笔 / ${bigN(n.sell)} 股</span></div>` : ''}
    ${l.length ? `<table><thead><tr><th>日期</th><th>人员</th><th>说明</th><th class="r">金额</th></tr></thead><tbody>${l.map(i => `<tr><td class="muted small">${esc(i.date || '')}</td><td>${esc(i.name || '')} <span class="muted small">${esc(i.rel || '')}</span></td><td class="small">${esc(i.text || '')}</td><td class="r">${i.value ? '$' + bigN(i.value) : '--'}</td></tr>`).join('')}</tbody></table>` : ''}</div>`; }
  return h;
}

// ===== 财报趋势(SEC 官方数据):每个指标一张图,可切换季报 / 年报;下方有解读和收入构成 =====
const finCache = {}, segCache = {};
let finMode = 'Q', finAxis = 0;
try { finMode = localStorage.getItem('finMode') === 'Y' ? 'Y' : 'Q'; } catch { }
const FIN_METRICS = [['rev', '营收', 'm'], ['ni', '净利润', 'm'], ['ocf', '经营现金流', 'm'], ['fcf', '自由现金流', 'm'], ['gm', '毛利率', 'p'], ['om', '营业利润率', 'p'], ['nm', '净利率', 'p'], ['eps', '每股收益(摊薄)', 'e'], ['dr', '资产负债率', 'p'], ['cr', '流动比率', 'x'], ['cash', '现金', 'm'], ['debt', '长期债务', 'm']];
const FIN_SHOW = ['rev', 'ni', 'fcf', 'gm'];      // 页面上只画最重要的四项;其余指标放进文字解读
const finFmt = (v, t) => !Number.isFinite(v) ? '--' : t === 'p' ? v.toFixed(1) + '%' : t === 'e' ? fmt(v) : t === 'x' ? v.toFixed(2) : (v < 0 ? '-' : '') + bigN(Math.abs(v));
const finLbl = (r, mode) => mode === 'Y' ? 'FY' + r.end.slice(0, 4) + '·' + r.end.slice(5, 7) + '月' : r.end.slice(2, 7);
function finSeries(f, mode, key) {            // 取最近 4 个季度 / 5 个财年,并附上去年同期(用来算同比)
  const all = mode === 'Y' ? f.years : f.rows, n = mode === 'Y' ? 5 : 4, gap = mode === 'Y' ? 1 : 4, out = [];
  for (let i = Math.max(0, all.length - n); i < all.length; i++) out.push({ r: all[i], v: all[i][key], p: i - gap >= 0 ? all[i - gap][key] : null });
  return out;
}
function finChart(f, mode, [key, name, t]) {
  const ser = finSeries(f, mode, key), vals = ser.map(x => x.v).filter(Number.isFinite); if (!vals.length) return `<div class="fincard"><div class="muted small">${name}</div><div class="muted small">暂无数据</div></div>`;
  const W = 420, H = 170, top = 22, bot = 22, mx = Math.max(...vals, 0), mn = Math.min(...vals, 0), span = (mx - mn) || 1, y0 = top + mx / span * (H - top - bot), gw = W / ser.length, bw = Math.min(46, gw * .5);
  let g = `<line x1="0" x2="${W}" y1="${y0.toFixed(1)}" y2="${y0.toFixed(1)}" stroke="var(--line)"/>`;
  ser.forEach((x, i) => { if (!Number.isFinite(x.v)) return; const bh = Math.max(1.5, Math.abs(x.v) / span * (H - top - bot)), cx = i * gw + gw / 2, y = x.v >= 0 ? y0 - bh : y0, last = i === ser.length - 1;
    g += `<rect x="${(cx - bw / 2).toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" rx="2" fill="${x.v < 0 ? 'var(--down)' : 'var(--accent)'}" opacity="${last ? 1 : .55}"/>
      <text x="${cx.toFixed(1)}" y="${(x.v >= 0 ? y - 4 : y + bh + 11).toFixed(1)}" text-anchor="middle" class="finv">${finFmt(x.v, t)}</text>
      <text x="${cx.toFixed(1)}" y="${H - 5}" text-anchor="middle" class="finx">${esc(finLbl(x.r, mode))}</text>`; });
  const l = ser[ser.length - 1], d = (t === 'p' || t === 'x') ? (Number.isFinite(l.v) && Number.isFinite(l.p) ? l.v - l.p : NaN) : (Number.isFinite(l.v) && Number.isFinite(l.p) && l.p > 0 ? (l.v / l.p - 1) * 100 : NaN);
  const dtxt = Number.isFinite(d) ? `<span class="${cls(d)}">${mode === 'Y' ? '较上年' : '较去年同期'} ${t === 'p' ? sgn(d, 1) + ' 个百分点' : t === 'x' ? sgn(d, 2) : sgn(d, 1) + '%'}</span>` : `<span class="muted">${l.p != null && l.p <= 0 ? '基数为负,不算同比' : '无同比数据'}</span>`;
  return `<div class="fincard"><div class="fch"><b>${name}</b><span class="small">${dtxt}</span></div><svg viewBox="0 0 ${W} ${H}" class="finsvg" role="img">${g}</svg></div>`;
}
const esc_ = x => x;
function finRead(f, mode) {                   // 规则解读:所有结论都由代码按数字算出来,每条先给结论再给依据
  const Y = mode === 'Y', all = Y ? f.years : f.rows, per = Y ? '最近一个财年' : '最近一个季度', vs = Y ? '上一财年' : '去年同期', gap = Y ? 1 : 4;
  const cur = all[all.length - 1], old = all[all.length - 1 - gap];
  const ch = (k) => cur && old && Number.isFinite(cur[k]) && Number.isFinite(old[k]) && old[k] > 0 ? (cur[k] / old[k] - 1) * 100 : NaN;
  const pp = (k) => cur && old && Number.isFinite(cur[k]) && Number.isFinite(old[k]) ? cur[k] - old[k] : NaN;
  const yoys = (k) => { const out = []; for (let i = Math.max(gap, all.length - (Y ? 4 : 4)); i < all.length; i++) { const a = all[i][k], b = all[i - gap] && all[i - gap][k]; if (Number.isFinite(a) && Number.isFinite(b) && b > 0) out.push((a / b - 1) * 100); } return out; };
  const L = [], add = (lv, t) => L.push([lv, t]), Lv = { s: ['强劲', 'up'], m: ['稳健', 'up'], w: ['偏弱', ''], d: ['下滑', 'down'], a: ['留意', ''] };
  const trend = a => a.length >= 3 ? (a[a.length - 1] > a[0] + 3 ? '增速在加快' : a[a.length - 1] < a[0] - 3 ? '增速在放慢' : '增速比较稳定') : '';
  const tx = a => a.map(x => sgn(x, 1) + '%').join(' → ');
  // 1 营收
  const g = ch('rev'), gs = yoys('rev');
  if (Number.isFinite(g)) { const lv = g >= 25 ? Lv.s : g >= 8 ? Lv.m : g >= 0 ? Lv.w : Lv.d;
    add(lv, `【营收】${per}营收 ${finFmt(cur.rev, 'm')},同比 ${sgn(g, 1)}%。${lv[0]}:${g >= 25 ? '增长很快,生意在明显扩张' : g >= 8 ? '稳步增长' : g >= 0 ? '增长偏慢,接近停滞' : '收入在萎缩'}。${gs.length >= 3 ? `近 ${gs.length} 期同比依次为 ${tx(gs)},${trend(gs)}。` : ''}${Y && f.years.length >= 5 && f.years[0].rev > 0 ? `近 ${f.years.length - 1} 年年均增长 ${(((f.years[f.years.length - 1].rev / f.years[0].rev) ** (1 / (f.years.length - 1)) - 1) * 100).toFixed(1)}%。` : ''}`); }
  // 2 净利润与每股收益
  const gn = ch('ni'), ge = ch('eps');
  if (Number.isFinite(gn) && Number.isFinite(g)) { const lv = gn >= g + 5 ? Lv.s : gn >= g - 5 ? Lv.m : gn >= 0 ? Lv.w : Lv.d;
    add(lv, `【净利润】${finFmt(cur.ni, 'm')},同比 ${sgn(gn, 1)}%。${gn >= g + 5 ? '利润涨得比营收快,说明每卖一块钱赚得更多(经营杠杆)' : gn >= g - 5 ? '利润和营收同步增长,盈利能力基本稳定' : '利润增速落后于营收,成本或费用在吞噬利润,要查原因(涨价、加大投入还是一次性费用)'}。${Number.isFinite(ge) ? `每股收益 ${fmt(cur.eps)},同比 ${sgn(ge, 1)}%${ge < gn - 5 ? '(比净利润涨得慢,可能是股本增加摊薄了)' : ge > gn + 5 ? '(比净利润涨得快,回购减少股数起了作用)' : ''}。` : ''}`); }
  else if (cur && cur.ni < 0) add(Lv.d, `【净利润】${per}亏损 ${finFmt(cur.ni, 'm')}。要看亏损在收窄还是扩大、账上现金能撑多久。`);
  // 3 三层利润率
  if (cur && Number.isFinite(cur.gm)) { const d1 = pp('gm'), d2 = pp('om'), d3 = pp('nm'), lv = cur.gm >= 50 ? Lv.s : cur.gm >= 30 ? Lv.m : Lv.w;
    add(lv, `【赚钱效率】每卖 100 元:毛利 ${cur.gm.toFixed(0)} 元${Number.isFinite(d1) ? `(${sgn(d1, 1)} 个百分点)` : ''},扣完运营费用剩营业利润 ${Number.isFinite(cur.om) ? cur.om.toFixed(0) : '--'} 元${Number.isFinite(d2) ? `(${sgn(d2, 1)})` : ''},最终净利润 ${Number.isFinite(cur.nm) ? cur.nm.toFixed(0) : '--'} 元${Number.isFinite(d3) ? `(${sgn(d3, 1)})` : ''}。毛利率高说明产品有定价权${Number.isFinite(d1) && d1 < -2 ? ';毛利率明显下降,留意是否在降价抢份额或成本上升' : Number.isFinite(d1) && d1 > 2 ? ';毛利率明显提升,议价能力在变强' : ''}${Number.isFinite(d1) && Number.isFinite(d2) && d2 < d1 - 2 ? ';营业利润率降得比毛利率多,说明费用(研发、销售)涨得快' : ''}。`); }
  // 4 现金流
  const cg = ch('ocf'), conv = cur && cur.ni > 0 && Number.isFinite(cur.fcf) ? cur.fcf / cur.ni : NaN, cxr = cur && cur.ocf > 0 && Number.isFinite(cur.capex) ? Math.abs(cur.capex) / cur.ocf : NaN;
  if (cur && Number.isFinite(cur.fcf)) { const lv = cur.fcf < 0 ? Lv.d : conv >= 0.9 ? Lv.s : conv >= 0.6 ? Lv.m : Lv.w, one = !Y ? '(单季数字波动大,看全年更准)' : '';
    add(lv, `【现金流】经营现金流 ${finFmt(cur.ocf, 'm')}${Number.isFinite(cg) ? `(同比 ${sgn(cg, 1)}%)` : ''},花在设备厂房上 ${Number.isFinite(cur.capex) ? finFmt(Math.abs(cur.capex), 'm') : '--'},剩下自由现金流 ${finFmt(cur.fcf, 'm')}${one}。${cur.fcf < 0 ? '自由现金流为负:经营赚的钱不够投资花,靠借债或存款撑着,要盯现金和债务。' : Number.isFinite(conv) ? `自由现金流相当于净利润的 ${(conv * 100).toFixed(0)}%,${conv >= 0.9 ? '利润含金量高,赚的是真金白银' : conv >= 0.6 ? '利润大部分变成了现金' : '利润变现能力一般,留意应收款和存货是否堆积'}。` : ''}${Number.isFinite(cxr) && cxr >= 0.5 ? `设备投入占了经营现金流的 ${(cxr * 100).toFixed(0)}%,属于重投入阶段。` : ''}`); }
  // 5 资产负债
  const bs = Y ? f.years[f.years.length - 1] : f.rows[f.rows.length - 1];
  if (bs && Number.isFinite(bs.dr)) { const nd = Number.isFinite(bs.debt) && Number.isFinite(bs.cash) ? bs.debt - bs.cash : NaN, lv = bs.dr < 50 ? Lv.m : bs.dr < 70 ? Lv.a : Lv.w;
    add(lv, `【资产负债】资产负债率 ${bs.dr.toFixed(0)}%(每 100 元资产有 ${bs.dr.toFixed(0)} 元是欠别人的)${Number.isFinite(bs.cr) ? `;流动比率 ${bs.cr.toFixed(2)}(${bs.cr >= 1.5 ? '短期还债很宽裕' : bs.cr >= 1 ? '短期够用' : '小于 1,短期偿债偏紧'})` : ''}${Number.isFinite(nd) ? `;现金 ${finFmt(bs.cash, 'm')} 对长期债务 ${finFmt(bs.debt, 'm')},${nd <= 0 ? '现金比债务多(净现金)' : '净负债 ' + finFmt(nd, 'm')}` : ''}。${bs.dr >= 70 ? '负债率偏高;也可能是大额回购、分红压低了股东权益造成的,要和现金流、现金一起看。' : ''}(截至 ${bs.end})`); }
  // 0 综合
  const sc = L.reduce((a, [lv]) => a + (lv[0] === '强劲' ? 2 : lv[0] === '稳健' ? 1 : lv[0] === '下滑' ? -2 : lv[0] === '偏弱' ? -1 : 0), 0), n = L.length;
  if (n >= 3) { const lv = sc >= n * 1.2 ? Lv.s : sc >= n * 0.5 ? Lv.m : sc >= 0 ? Lv.a : Lv.d; L.unshift([lv, `【一句话】按${Y ? '年度' : '季度'}数据,这家公司的财报整体${lv[0] === '强劲' ? '很强:增长、利润、现金流都在线' : lv[0] === '稳健' ? '稳健:没有明显短板' : lv[0] === '留意' ? '喜忧参半:有强项也有需要留意的地方' : '偏弱:多项指标在走弱'}。(只是对财报数字的客观归纳,不含估值和股价判断)`]); }
  return L;
}
function segHTML(sg) {
  if (!sg) return '<div class="muted small">正在读取收入构成…</div>';
  if (sg.error || !sg.views || !sg.views.length) return `<div class="muted small">${sg.error === 'no_cik' ? '' : '这家公司的年报没有按产品 / 分部 / 地区披露收入,或格式暂不支持。'}</div>`;
  const v = sg.views[Math.min(finAxis, sg.views.length - 1)], n = v.ends.length, tot = v.items.reduce((a, i) => a + i.vals[n - 1], 0);
  const rowH = v.items.map((i, k) => { const cur = i.vals[n - 1], pr = n > 1 ? i.vals[n - 2] : null, g = pr > 0 ? (cur / pr - 1) * 100 : NaN, sh = cur / tot * 100, psh = pr > 0 && n > 1 ? pr / v.items.reduce((a, x) => a + (x.vals[n - 2] || 0), 0) * 100 : NaN;
    return `<div class="segrow"><span class="segn">${esc(i.name)}</span><span class="segbar"><i style="width:${Math.max(1, sh).toFixed(1)}%"></i></span><span class="segs"><b>${sh.toFixed(1)}%</b> ${bigN(cur)}</span><span class="segg ${cls(g)}">${Number.isFinite(g) ? sgn(g, 1) + '%' : '--'}</span></div>`; }).join('');
  const rd = [], big = v.items[0], bsh = big.vals[n - 1] / tot * 100;
  rd.push(`最大的一块是「${esc(big.name)}」,占 ${bsh.toFixed(0)}%${bsh >= 50 ? '(依赖度较高)' : ''}。`);
  const gs = v.items.filter(i => n > 1 && i.vals[n - 2] > 0).map(i => ({ n: i.name, g: (i.vals[n - 1] / i.vals[n - 2] - 1) * 100, sh: i.vals[n - 1] / tot * 100 })).sort((a, b) => b.g - a.g);
  if (gs.length >= 2) { rd.push(`增长最快的是「${esc(gs[0].n)}」(${sgn(gs[0].g, 1)}%)${gs[gs.length - 1].g < 0 ? `;在下滑的是「${esc(gs[gs.length - 1].n)}」(${sgn(gs[gs.length - 1].g, 1)}%)` : ''}。`);
    const dr = gs.filter(x => x.sh >= 5 && x.g >= 20); if (dr.length && dr[0].n !== gs[0].n) rd.push(`「${esc(dr[0].n)}」也在快速增长(${sgn(dr[0].g, 1)}%)。`); }
  return `<div class="segtabs">${sg.views.map((x, k) => `<button data-seg="${k}" class="${k === finAxis ? 'on' : ''}">${esc(x.axis)}</button>`).join('')}</div>
    <div class="seghead muted small"><span>项目</span><span></span><span>占比 / 金额(财年末 ${esc(v.ends[n - 1])})</span><span>同比</span></div>${rowH}
    <p class="small segrd">${rd.join(' ')}</p>${v.overlap ? '<div class="muted small">注意:这几项之间可能有重叠,占比仅供参考。</div>' : ''}
    <div class="muted small">来源:${esc(sg.source)}(<a href="${esc(sg.doc)}" target="_blank" rel="noopener noreferrer">${esc(sg.filed)} 提交</a>)。名称按年报原文;没有中文对照的显示英文。</div>`;
}
function finHTML(f, sg) {
  if (!f) return '<div class="muted small">正在读取 SEC 财报…</div>';
  if (f.error) return `<div class="muted small">${{ no_cik: 'ETF / 指数没有公司财报', no_us_gaap: '这是外国公司,使用国际会计准则(20-F),暂不支持', no_contact: '后台还没设置 SEC_CONTACT', not_stock: '指数没有公司财报', too_short: '上市时间太短,财报不足 4 个季度', mock: '演示模式没有财报数据' }[f.error] || '暂无财报数据'}</div>`;
  const last = f.rows[f.rows.length - 1], ck = f.check, lv = ck && { ok: ['✅', '与 Yahoo 一致'], warn: ['⚠️', '与 Yahoo 有小差异'], bad: ['❌', '与 Yahoo 差异大,请以 SEC 原文为准'] }[ck.level];
  const rd = finRead(f, finMode);
  let h = `<div class="fintoggle"><button data-fm="Q" class="${finMode === 'Q' ? 'on' : ''}">季报(最近 4 季)</button><button data-fm="Y" class="${finMode === 'Y' ? 'on' : ''}">年报(最近 5 年)</button></div>
    <div class="fingrid">${FIN_METRICS.filter(m => FIN_SHOW.includes(m[0])).map(m => finChart(f, finMode, m)).join('')}</div>
    <h4 class="finh">财报解读 <span class="muted small">按${finMode === 'Y' ? '年度' : '季度'}数据,由代码按数字自动判断</span></h4>
    <ul class="finread">${rd.map(([lv_, t]) => `<li><span class="ftag ${lv_[1]}">${lv_[0]}</span>${esc(t)}</li>`).join('')}</ul>
    <h4 class="finh">收入从哪来 <span class="muted small">来自最新年报,看收入结构和增速</span></h4><div id="segbox">${segHTML(sg)}</div>
    <div class="muted small finfoot">来源:${esc(f.source)};最新一期 ${esc(f.asof)}(${esc(last.filed)} 公告)。季度里第四季或现金流数据由全年数减前三季推算。${lv ? `数据核对:${lv[0]} ${lv[1]}(核对 ${ck.n} 项,最大误差 ${ck.worst}%)。` : '数据核对:Yahoo 暂时没有可比数据。'}</div>`;
  return h;
}
function paintFin(s) {
  const box = $('#finbox'); if (!box || state.sel !== s) return;
  box.innerHTML = '<h3>财报趋势</h3>' + finHTML(finCache[s], segCache[s]); pfData(s);
  box.onclick = e => { const m = e.target.closest('[data-fm]'), g = e.target.closest('[data-seg]');
    if (m) { finMode = m.dataset.fm; try { localStorage.setItem('finMode', finMode); } catch { } paintFin(s); }
    if (g) { finAxis = +g.dataset.seg; paintFin(s); } };
}
async function fillFin(s) {
  paintFin(s);
  if (finCache[s] === undefined) {
    let f; try { f = await Data.loadFin(s); } catch { f = { error: 'fail' }; }
    finCache[s] = f; if (state.sel === s && state.dt === 'company') paintFin(s);
  }
  if (finCache[s] && !finCache[s].error && segCache[s] === undefined && Data.loadSeg) {
    let g; try { g = await Data.loadSeg(s); } catch { g = { error: 'fail' }; }
    segCache[s] = g; if (state.sel === s && state.dt === 'company') paintFin(s);
  }
}

function profileHTML(s) {
  const p = typeof PROFILES !== 'undefined' && PROFILES[s]; if (!p) return '';
  return `<div class="csec"><h3>通俗解读 <span class="muted small">${esc(GRADE_TXT[p.grade] || '')} · ${PROFILE_ASOF}</span></h3>
    <p class="intro"><b>${esc(p.one)}</b></p><div id="pfdata"></div>
    <div class="pf"><div><span class="muted small">靠什么赚钱</span>${list(p.money)}</div>
    <div><span class="muted small">强在哪</span><p>${esc(p.strong)}</p></div>
    <div><span class="muted small">产业链位置 / 卡脖子</span><p>${esc(p.choke)}</p></div>
    <div><span class="muted small">订单线索(合同≠收入)</span><p>${esc(p.orders)}</p></div>
    <div><span class="muted small">主要风险</span>${list(p.risk)}</div>
    <div><span class="muted small">接下来盯什么</span><p>${esc(p.watch)}</p></div></div>
    <div class="muted small">${esc(p.note)}定性内容为一般性介绍;上方数字来自 SEC 财报,自动更新。</div></div>`;
}
function pfData(s) {                      // 通俗解读里的「关键数字」:全部来自 SEC 数据,不手写
  const box = $('#pfdata'), f = finCache[s]; if (!box || !f || f.error) return;
  const t = f.ttm, sg = segCache[s], v = sg && sg.views && sg.views[0], n = v ? v.ends.length : 0, tot = v ? v.items.reduce((a, i) => a + i.vals[n - 1], 0) : 0;
  const bs = f.rows[f.rows.length - 1], chip = (l, x, y) => `<div><span class="muted small">${l}</span><b>${x}</b>${Number.isFinite(y) ? `<span class="small ${cls(y)}">${sgn(y, 1)}%</span>` : ''}</div>`;
  box.innerHTML = `<div class="kv pfkv">${chip('近 12 个月营收', finFmt(t.rev, 'm'), t.rev_yoy)}${chip('净利润', finFmt(t.ni, 'm'), t.ni_yoy)}${chip('毛利率', finFmt(t.gm, 'p'))}${chip('自由现金流', finFmt(t.fcf, 'm'), t.fcf_yoy)}${Number.isFinite(bs.dr) ? chip('资产负债率', finFmt(bs.dr, 'p')) : ''}${v ? chip('最大业务', esc(v.items[0].name) + ' ' + (v.items[0].vals[n - 1] / tot * 100).toFixed(0) + '%') : ''}</div>`;
}
const list = a => `<ul class="clist">${(a || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
let ETFH = {}; fetch('etf_holdings.json').then(r => r.json()).then(j => { ETFH = j || {}; }).catch(() => { });
function etfHTML(s, c) {                      // ETF 前 15 大持仓:优先用 SEC 季度披露的完整持仓,没有就用 Yahoo 的前 10 大
  const f = ETFH[s]; let rows, note;
  if (f && f.top && f.top.length) { rows = f.top.slice(0, 15).map(x => ({ name: x.name, sym: x.ticker, pct: x.pct })); note = `来源:SEC N-PORT 基金持仓披露,数据截止 ${esc(f.asof)}(共 ${f.n} 项持仓;这类披露每季度更新一次,滞后约两个月,所以比例和最新有出入)`; }
  else if (c && c.etf && c.etf.length) { rows = c.etf.map(x => ({ name: x.name, sym: x.sym, pct: (x.pct || 0) * 100 })); note = '来源:Yahoo,只有前 10 大'; }
  else return '';
  const tot = rows.reduce((a, x) => a + (x.pct || 0), 0), mx = Math.max(...rows.map(x => x.pct || 0), 1);
  return `<div class="csec"><h3>前 ${rows.length} 大持仓 <span class="muted small">合计占 ${tot.toFixed(1)}%</span></h3><table><thead><tr><th>#</th><th>持仓</th><th class="r">占比</th><th></th></tr></thead><tbody>${rows.map((x, i) => `<tr><td class="muted">${i + 1}</td><td>${x.sym ? `<span class="sym" data-go="${esc(x.sym)}">${esc(x.sym)}</span> ` : ''}<span class="${x.sym ? 'muted small' : ''}">${esc(x.name || '')}</span></td><td class="r">${(x.pct || 0).toFixed(2)}%</td><td style="width:34%"><div style="height:6px;border-radius:3px;background:var(--accent);opacity:.7;width:${((x.pct || 0) / mx * 100).toFixed(0)}%"></div></td></tr>`).join('')}</tbody></table><div class="muted small">${note}</div></div>`;
}
function companyHTML(s, c) {
  const k = COMPANIES[s], p = (c && c.profile) || {}, q = Data.quote(s);
  const meta = [p.finnhubIndustry, p.exchange, p.ipo ? '上市 ' + p.ipo : '', p.country].filter(Boolean).map(esc).join(' · ');
  const web = /^https?:\/\//.test(p.weburl || '') ? ` · <a href="${p.weburl}" target="_blank" rel="noopener noreferrer">官网</a>` : '';
  const peers = (k && k.comp) || (c && c.peers ? c.peers.filter(x => x !== s).slice(0, 8) : []);
  const chips = peers.map(x => /^[A-Z.]{1,6}$/.test(x) ? `<button class="chip" data-go="${x}">${x}</button>` : `<span class="chip plain">${esc(x)}</span>`).join('');
  const note = c && c.error ? '暂无数据' : '';
  let h = `<div class="csec"><h3>${esc(k ? k.n : q.name)} <span class="muted small">${meta}${web}</span></h3>${k ? `<p class="intro">${esc(k.intro)}</p>` : c && c.about ? '' : '<p class="muted">暂无这家公司的详细分析</p>'}</div>`;
  h += profileHTML(s) + etfHTML(s, c);
  if (k) h += `<div class="csec"><h3>主营业务</h3>${list(k.segs)}</div>`;
  else if (c && c.about) h += `<div class="csec"><h3>公司简介 <span class="muted small">${[c.about.sector, c.about.industry, c.about.employees ? c.about.employees.toLocaleString('en-US') + ' 名员工' : ''].filter(Boolean).map(esc).join(' · ')}</span></h3><p class="intro">${esc(c.about.zh || c.about.summary)}</p><div class="muted small">${c.about.zh ? '机器翻译自 Yahoo 的英文简介,仅供参考;' : '英文原文,来自 Yahoo;'}这只股票暂无深度中文分析</div></div>`;
  h += `<div class="csec"><h3>分析师评级</h3>${note && !(c && c.rec) ? `<div class="muted small">${note}</div>` : recHTML(c)}</div>`;
  if (c && c.target) h += `<div class="csec"><h3>分析师目标价</h3>${targetHTML(c)}</div>`;      // 没数据(如 ETF)就不显示这一栏
  if (c && Array.isArray(c.grades) && c.grades.length) h += `<div class="csec"><h3>最近机构评级变动</h3>${gradesHTML(c)}</div>`;
  if (peers.length) h += `<div class="csec"><h3>竞争对手</h3><div class="chips">${chips}</div></div>`;
  if (!isIdx(s)) h += '<div class="csec" id="finbox"></div>';
  h += extraHTML(c);
  if (!k && backlogHTML(c)) h += `<div class="csec"><h3>在手订单</h3>${backlogHTML(c)}</div>`;
  if (k) {
    h += `<div class="csec"><h3>竞争优势</h3>${list(k.adv)}</div>
      <div class="csec"><h3>护城河</h3><div class="tags">${k.moat.tags.map(t => `<span class="mtag">${esc(t)}</span>`).join('')}</div><p>${esc(k.moat.text)}</p></div>
      <div class="csec"><h3>领先领域</h3>${list(k.lead)}</div>
      <div class="csec"><h3>未来订单 / 需求能见度</h3>${backlogHTML(c)}<p>${esc(k.orders)}</p></div>
      <div class="csec"><h3>主要风险</h3>${list(k.risks)}</div>`;
  }
  h += `<div class="csec"><h3>财报对比(近 4 个季度)</h3>${note && !(c && c.earn) ? `<div class="muted small">${note}</div>` : earnHTML(c)}</div>
    <div class="small cfoot">${k ? `分析内容撰写于 ${COMPANY_ASOF},可能已过时,订单等数字以最新财报为准。` : ''}</div>`;
  return h;
}
async function renderCompany() {
  const s = state.sel, box = $('#dcompany'); if (!box) return;
  box.innerHTML = companyHTML(s, null); fillFin(s);
  let c; try { c = await Data.loadCompany(s); } catch { c = { error: 'fail' }; }
  if (state.sel === s && state.dt === 'company' && $('#dcompany')) { $('#dcompany').innerHTML = companyHTML(s, c); fillFin(s); }
}
function loadStats(s) { if (Data.loadDetail) Data.loadDetail(s).then(() => { if (state.sel === s && state.tab === 'watch' && $('#dhead')) $('#dhead').innerHTML = headHTML(s); }).catch(() => { }); }
function newsHTML(list) {
  if (!Array.isArray(list)) return `<li class="muted">${list.error}</li>`;
  if (!list.length) return '<li class="muted">暂无新闻</li>';
  return list.map(n => `<li><span class="tag ${n.hot ? 'hot' : ''}">${n.hot ? '重要' : n.src}</span><div>${/^https?:\/\//.test(n.url || '') ? `<a href="${n.url}" target="_blank" rel="noopener noreferrer" style="color:inherit">${esc(n.title)}</a>` : esc(n.title)}<div class="muted small">${esc(n.src)} · ${n.minsAgo < 60 ? n.minsAgo + ' 分钟前' : Math.round(n.minsAgo / 60) + ' 小时前'}</div></div></li>`).join('');
}
const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ===== 底部工具栏(仿 Moomoo):日K 周K 月K 季K 年K [1分▾]  ...  蜡烛 缩放 指标 =====
const IND_ITEMS = [['ma0', 'MA5', MA_DEF[0][1]], ['ma1', 'MA10', MA_DEF[1][1]], ['ma2', 'MA20', MA_DEF[2][1]], ['ma3', 'MA50', MA_DEF[3][1]], ['ma4', 'MA100', MA_DEF[4][1]], ['ma5', 'MA200', MA_DEF[5][1]], ['boll', 'BOLL(20,2)'], ['chip', '筹码分布(估算)'], ['sr', '支撑 / 压力(参考)'], ['trend', '趋势线(参考)'], ['pat', '形态识别(参考)']];
const SUB_ITEMS = [['vol', '成交量'], ['macd', 'MACD(12,26,9)'], ['rsi', 'RSI(6,12,24)'], ['sig', '信号提示(放量 / 金叉死叉 / 背离)']];
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

// ===== 副图信号:放量、MACD 金叉死叉、RSI / MACD 顶底背离 =====
const SIG = { surge: 2.0, surgeDays: 20, pivotW: 5, gapMin: 8, gapMax: 80 };
function pivotsOf(c, w) {   // 波段高低点:左右各 w 根都不比它更极端(右侧确认后才成立,不使用未来数据)
  const lows = [], highs = [];
  for (let i = w; i < c.length - w; i++) {
    let lo = true, hi = true;
    for (let k = i - w; k <= i + w; k++) { if (c[k] < c[i]) lo = false; if (c[k] > c[i]) hi = false; }
    if (lo && (!lows.length || i - lows[lows.length - 1] > 1)) lows.push(i);
    if (hi && (!highs.length || i - highs[highs.length - 1] > 1)) highs.push(i);
  }
  return { lows, highs };
}
function divergences(c, ind, name, piv, zoneLow, zoneHigh, minDiff) {
  const out = [];
  for (let q = 1; q < piv.lows.length; q++) {   // 底背离:价格创新低,指标没有创新低(且前一个低点处于偏弱区域)
    const a = piv.lows[q - 1], b = piv.lows[q], gap = b - a; if (gap < SIG.gapMin || gap > SIG.gapMax || ind[a] == null || ind[b] == null) continue;
    if (c[b] < c[a] * .999 && ind[b] > ind[a] + minDiff(ind[a]) && zoneLow(ind[a])) out.push({ type: 'bull', a, b, name });
  }
  for (let q = 1; q < piv.highs.length; q++) {   // 顶背离:价格创新高,指标没有创新高
    const a = piv.highs[q - 1], b = piv.highs[q], gap = b - a; if (gap < SIG.gapMin || gap > SIG.gapMax || ind[a] == null || ind[b] == null) continue;
    if (c[b] > c[a] * 1.001 && ind[b] < ind[a] - minDiff(ind[a]) && zoneHigh(ind[a])) out.push({ type: 'bear', a, b, name });
  }
  return out;
}
function signals(B, r12, mc) {
  const n = B.length, c = B.map(b => b.c), surge = new Array(n).fill(false), cross = new Array(n).fill(0);
  const pre = [0]; for (let i = 0; i < n; i++) pre.push(pre[i] + (B[i].v || 0));
  for (let i = SIG.surgeDays; i < n; i++) { const avg = (pre[i] - pre[i - SIG.surgeDays]) / SIG.surgeDays; if (avg > 0 && B[i].v >= SIG.surge * avg) surge[i] = true; }
  for (let i = 35; i < n; i++) {   // 前 35 根 EMA 还没稳定,不判断
    const d0 = mc.dif[i - 1] - mc.dea[i - 1], d1 = mc.dif[i] - mc.dea[i];
    if (d0 <= 0 && d1 > 0) cross[i] = 1; else if (d0 >= 0 && d1 < 0) cross[i] = -1;
  }
  const piv = pivotsOf(c, SIG.pivotW);
  const div = [...divergences(c, mc.dif, 'macd', piv, v => v < 0, v => v > 0, v => Math.abs(v) * .1), ...divergences(c, r12, 'rsi', piv, v => v <= 50, v => v >= 50, () => 1.5)];
  return { surge, cross, div };
}
function prepare() {
  const bars = Data.bars(state.sel, state.period).bars.slice();
  if (!isIntra(state.period) && bars.length) {   // 日K及以上:用最新报价实时更新最后一根
    const q = Data.quote(state.sel);
    if (Number.isFinite(q.price)) { const b = { ...bars[bars.length - 1] }; b.c = q.price; b.h = Math.max(b.h, q.price); b.l = Math.min(b.l, q.price); bars[bars.length - 1] = b; }
  }
  const c = bars.map(b => b.c);
  const rs = [rsi(c, 6), rsi(c, 12), rsi(c, 24)], mc = macd(c);
  return { bars, ma: MA_DEF.map(([k]) => sma(c, k)), boll: boll(c), rsi: rs, macd: mc, sig: signals(bars, rs[1], mc) };
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


// ===== 参考支撑 / 压力位 与 趋势线(纯K线 + 筹码分布推算,仅作参考,不构成预测)=====
function srCalc(B, i1) {
  const a = Math.max(0, i1 - 250), W = B.slice(a, i1 + 1), nW = W.length;
  if (nW < 40) return { lv: [], tl: [] };
  const price = W[nW - 1].c, bins = 80, lo = Math.min(...W.map(b => b.l)), hi = Math.max(...W.map(b => b.h)), step = (hi - lo) / bins || 1, arr = new Array(bins).fill(0);
  W.forEach((b, i) => { const w = Math.pow(.995, nW - 1 - i), x = Math.floor((b.l - lo) / step), z = Math.min(bins - 1, Math.floor((b.h - lo) / step)), c = z - x + 1; for (let k = x; k <= z; k++) arr[k] += b.v * w / c; });
  const sm = arr.map((_, i) => (arr[Math.max(0, i - 1)] + arr[i] + arr[Math.min(bins - 1, i + 1)]) / 3), mx = Math.max(...sm) || 1, cand = [];
  for (let i = 1; i < bins - 1; i++) if (sm[i] > 0 && sm[i] >= sm[i - 1] && sm[i] >= sm[i + 1] && sm[i] > .18 * mx) cand.push({ p: lo + (i + .5) * step, s: sm[i] / mx, src: '筹码' });
  const K = 5, pl = [], ph = [], tl3 = [], th3 = [];   // 波段低点 / 高点:左右各 5 根都不比它更极端(趋势线另用更灵敏的 3 根)
  for (let i = K; i < nW - K; i++) {
    let isL = true, isH = true;
    for (let j = i - K; j <= i + K; j++) { if (W[j].l < W[i].l) isL = false; if (W[j].h > W[i].h) isH = false; }
    if (isL) { pl.push(i); cand.push({ p: W[i].l, s: .5, src: '低点' }); }
    if (isH) { ph.push(i); cand.push({ p: W[i].h, s: .5, src: '高点' }); }
  }
  for (let i = 3; i < nW - 3; i++) {
    let isL = true, isH = true;
    for (let j = i - 3; j <= i + 3; j++) { if (W[j].l < W[i].l) isL = false; if (W[j].h > W[i].h) isH = false; }
    if (isL) tl3.push(i); if (isH) th3.push(i);
  }
  cand.sort((x, y) => x.p - y.p); const m = [];
  for (const c of cand) {   // 1% 以内合并,重复出现 = 更强
    const t = m[m.length - 1];
    if (t && Math.abs(c.p - t.p) / t.p < .01) { t.p = (t.p * t.n + c.p) / (t.n + 1); t.s += c.s; t.n++; if (!t.src.includes(c.src)) t.src += '+' + c.src; } else m.push({ ...c, n: 1 });
  }
  // 趋势线:过两个波段低点(上升支撑线)或两个波段高点(下降压力线),中间不能被价格穿破,触碰点越多越强
  const trend = (piv, low) => {
    const wick = i => Math.log(low ? W[i].l : W[i].h), clo = i => Math.log(W[i].c), ps = piv.slice(-10); let best = null;
    for (let x = 0; x < ps.length; x++) for (let y = x + 1; y < ps.length; y++) {
      const p = ps[x], q = ps[y]; if (q - p < 10) continue;
      const yp = wick(p), yq = wick(q); if (low ? yq <= yp : yq >= yp) continue;   // 上升支撑线 / 下降压力线
      const slope = (yq - yp) / (q - p); let ok = true, touches = 0;
      for (let j = p; j < nW; j++) { const lv = yp + slope * (j - p), d = low ? clo(j) - lv : lv - clo(j); if (d < -.01) { ok = false; break; } }   // 收盘价不能明显穿破
      if (!ok) continue;
      for (const r of ps) if (r !== p && r !== q && Math.abs(wick(r) - (yp + slope * (r - p))) < .012) touches++;
      const score = touches * 2 + (q - p) / 40 + q / nW * 2;
      if (!best || score > best.score) {
        let off = 0; for (let j = p; j < nW; j++) { const lv = yp + slope * (j - p), d = low ? Math.log(W[j].h) - lv : lv - Math.log(W[j].l); if (d > off) off = d; }
        best = { low, p: p + a, q: q + a, yp, slope, touches: touches + 2, score, off };
      }
    }
    return best;
  };
  return { all: m.map(x => ({ ...x, kind: x.p < price ? 'sup' : 'res' })), price, tl: [trend(tl3, true), trend(th3, false)].filter(Boolean) };
}
function drawSR(ctx, { X, Y, top, bot, W, PL, PR, i1, ext, I, lo, hi }) {
  const key = state.sel + '|' + state.period + '|' + V.bars.length + '|' + i1;
  if (!V._sr || V._sr.key !== key) V._sr = { key, val: srCalc(V.bars, i1) };
  const R = V._sr.val, dots = s => s >= 1.8 ? '●●●' : s >= 1.2 ? '●●' : '●', dec = decOf(V.bars[i1].c);
  ctx.font = '11px -apple-system,"PingFang SC",sans-serif'; ctx.textBaseline = 'middle';
  if (I.sr) {
    const pr = R.price, vis = R.all.filter(l => (l.kind === 'sup' ? l.p < pr * .995 : l.p > pr * 1.005) && l.s >= .45 && l.p >= lo && l.p <= hi);
    const top5 = k => vis.filter(l => l.kind === k).sort((a, b) => b.s - a.s).slice(0, 5);   // 每侧最多 5 条:当前可见价格范围内最强的
    const chosen = [...top5('sup'), ...top5('res')], labeled = new Set([...chosen].sort((a, b) => b.s - a.s).slice(0, 3));   // 只给最强的 3 条标文字,避免挤成一团
    let lastY = -99;
    chosen.sort((a, b) => b.p - a.p).forEach(l => {
      const y = Y(l.p); if (y < top || y > bot) return;
      const col = l.kind === 'sup' ? UP : DOWN, al = Math.min(.7, .22 + l.s * .13);
      ctx.save(); ctx.strokeStyle = col; ctx.globalAlpha = al; ctx.setLineDash([6, 4]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(PL, y); ctx.lineTo(W - PR, y); ctx.stroke(); ctx.restore();
      if (labeled.has(l) && Math.abs(y - lastY) > 13) { ctx.font = '10.5px -apple-system,"PingFang SC",sans-serif'; ctx.fillStyle = col; ctx.globalAlpha = .95; ctx.textAlign = 'left'; ctx.fillText(`${l.kind === 'sup' ? '支撑' : '压力'} ${fmt(l.p, dec)} ${dots(l.s)} ${l.src.replace(/筹码/g, '筹').replace(/低点/g, '低').replace(/高点/g, '高')}`, PL + 8, y - 7); ctx.globalAlpha = 1; lastY = y; }
    });
  }
  if (I.trend) R.tl.forEach(t => {
    const at = i => Math.exp(t.yp + t.slope * (i - t.p)), end = i1 + ext, col = t.low ? UP : DOWN;
    ctx.save(); ctx.strokeStyle = col; ctx.lineWidth = 1.4; ctx.globalAlpha = .9; ctx.beginPath(); ctx.moveTo(X(t.p), Y(at(t.p))); ctx.lineTo(X(end), Y(at(end))); ctx.stroke();
    ctx.fillStyle = col; [t.p, t.q].forEach(i => { ctx.beginPath(); ctx.arc(X(i), Y(at(i)), 3, 0, 7); ctx.fill(); });
    ctx.restore();
    const ly = Y(at(i1)); if (ly > top && ly < bot) { ctx.fillStyle = col; ctx.textAlign = 'right'; ctx.fillText(`${t.low ? '上升趋势线' : '下降趋势线'} · ${t.touches}点`, W - PR - 8, ly + (t.low ? 12 : -12)); }
  });
  ctx.setLineDash([]);
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

  const divLines = (list, arr, Y) => list.forEach(d => { if (d.b < i0 - 1 || d.a > i1 + 1) return; ctx.strokeStyle = d.type === 'bull' ? UP : DOWN; ctx.lineWidth = 1.3; ctx.setLineDash([4, 3]); ctx.beginPath(); ctx.moveTo(X(d.a), Y(arr[d.a])); ctx.lineTo(X(d.b), Y(arr[d.b])); ctx.stroke(); ctx.setLineDash([]); ctx.lineWidth = 1; });
  const divLabels = (list, arr, Y, top, bot) => { let lx = -99; list.forEach(d => { if (d.b < i0 || d.b > i1) return; const x = X(d.b), bull = d.type === 'bull'; if (Math.abs(x - lx) < 44) return; lx = x; const y = Math.max(top + 10, Math.min(bot - 8, Y(arr[d.b]) + (bull ? 13 : -13))); ctx.fillStyle = bull ? UP : DOWN; ctx.fillText(bull ? '底背离' : '顶背离', x, y); }); };

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
      if (I.pat && n >= 60) {
        const pk = state.sel + '|' + state.period + '|' + n + '|' + i1;
        if (!V._pat || V._pat.key !== pk) { const a0 = Math.max(0, i1 - 250); V._pat = { key: pk, off: a0, list: detectPatterns(V.bars.slice(a0, i1 + 1), isIntra(state.period)) }; }
        drawPatterns(ctx, { X, Y, top, bot, W, PL, PR, off: V._pat.off, ext: Math.max(2, cnt * .12), list: V._pat.list, up: UP, down: DOWN, accent: C.accent, last: i1 });
      }
      if ((I.sr || I.trend) && n >= 40) drawSR(ctx, { X, Y, top, bot, W, PL, PR, i1, ext: Math.max(2, cnt * .12), I, lo, hi });
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
      let mx = 0; for (let i = i0; i <= i1; i++) mx = Math.max(mx, B[i].v); mx = mx || 1; scale(0, mx * (I.sig ? 1.3 : 1.08)); p.fv = v => big(Math.round(v));
      grid([mx], p.fv); clipPlot(top, bot);
      for (let i = Math.max(0, i0 - 1); i <= Math.min(n - 1, i1 + 1); i++) { const b = B[i], w = Math.min(Math.max(1, Math.floor(bw * .7)), 24); ctx.fillStyle = b.c >= b.o ? 'rgba(126,211,164,.75)' : 'rgba(239,138,120,.75)'; ctx.fillRect(Math.round(X(i) - w / 2), Y(b.v), w, Y(0) - Y(b.v)); }
      ctx.restore(); ctx.font = '11px sans-serif';
      if (I.sig) { ctx.font = '10px -apple-system,"PingFang SC",sans-serif'; ctx.fillStyle = '#e6a23c'; ctx.textAlign = 'center'; let lx = -99;
        for (let i = Math.max(0, i0); i <= Math.min(n - 1, i1); i++) if (V.sig.surge[i]) { const x = X(i); if (x - lx < 30) continue; lx = x; ctx.fillText('放量', x, Math.max(top + 7, Y(B[i].v) - 7)); } ctx.font = '11px sans-serif'; }
      segs(ctx, [['成交量', C.text], [`VOL:${big(B[ref].v)}`, '#e6a23c']], PL + 4, p.y + 11, W - PR - 20, 16);
    } else if (p.id === 'macd') {
      let m = 0; for (let i = i0; i <= i1; i++) [V.macd.dif[i], V.macd.dea[i], V.macd.hist[i]].forEach(v => v != null && (m = Math.max(m, Math.abs(v)))); m = m || 1; scale(-m * 1.1, m * 1.1); p.fv = v => fmt(v, 3);
      grid([-m * .8, 0, m * .8], p.fv); clipPlot(top, bot);
      for (let i = Math.max(0, i0 - 1); i <= Math.min(n - 1, i1 + 1); i++) { const v = V.macd.hist[i], w = Math.min(Math.max(1, Math.floor(bw * .5)), 14); ctx.fillStyle = v >= 0 ? 'rgba(126,211,164,.8)' : 'rgba(239,138,120,.8)'; ctx.fillRect(Math.round(X(i) - w / 2), Math.min(Y(0), Y(v)), w, Math.max(1, Math.abs(Y(v) - Y(0)))); }
      poly(V.macd.dif, Y, '#f5c542'); poly(V.macd.dea, Y, '#35c5e8');
      if (I.sig) divLines(V.sig.div.filter(d => d.name === 'macd'), V.macd.dif, Y);
      ctx.restore(); ctx.font = '11px sans-serif';
      if (I.sig) { ctx.font = '10px -apple-system,"PingFang SC",sans-serif'; ctx.textAlign = 'center'; let lx = -99;
        for (let i = Math.max(0, i0); i <= Math.min(n - 1, i1); i++) { const cr = V.sig.cross[i]; if (!cr) continue; const x = X(i), yv = Math.max(top + 12, Math.min(bot - 12, Y((V.macd.dif[i] + V.macd.dea[i]) / 2))), col = cr > 0 ? UP : DOWN, up = cr > 0;
          ctx.fillStyle = col; ctx.beginPath(); up ? (ctx.moveTo(x, yv + 3), ctx.lineTo(x - 4, yv + 10), ctx.lineTo(x + 4, yv + 10)) : (ctx.moveTo(x, yv - 3), ctx.lineTo(x - 4, yv - 10), ctx.lineTo(x + 4, yv - 10)); ctx.fill();
          if (x - lx >= 34) { lx = x; ctx.fillText(up ? '金叉' : '死叉', x, Math.max(top + 6, Math.min(bot - 4, up ? yv + 19 : yv - 18))); } }
        divLabels(V.sig.div.filter(d => d.name === 'macd'), V.macd.dif, Y, top, bot); ctx.font = '11px sans-serif'; }
      segs(ctx, [['MACD(12,26,9)', C.text], [`DIF:${fmt(V.macd.dif[ref], 3)}`, '#f5c542'], [`DEA:${fmt(V.macd.dea[ref], 3)}`, '#35c5e8'], [`MACD:${fmt(V.macd.hist[ref], 3)}`, V.macd.hist[ref] >= 0 ? UP : DOWN]], PL + 4, p.y + 11, W - PR - 20, 16);
    } else if (p.id === 'rsi') {
      scale(0, 100); p.fv = v => fmt(v, 1); grid([30, 50, 70], v => String(v)); clipPlot(top, bot);
      const rc = ['#ff9a3c', '#4c8dff', '#b57bee']; V.rsi.forEach((a, k) => poly(a, Y, rc[k], 1.1));
      if (I.sig) divLines(V.sig.div.filter(d => d.name === 'rsi'), V.rsi[1], Y);
      ctx.restore(); ctx.font = '11px sans-serif';
      if (I.sig) { ctx.font = '10px -apple-system,"PingFang SC",sans-serif'; ctx.textAlign = 'center'; divLabels(V.sig.div.filter(d => d.name === 'rsi'), V.rsi[1], Y, top, bot); ctx.font = '11px sans-serif'; }
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
  if (Data.loadSectors) {                      // 实时模式:20 个板块,每个板块市值最大的 15 只
    let S = null; try { S = await Data.loadSectors(); } catch { }
    if (state.tab !== 'sectors') return;
    if (S) {
      const ok = S.sectors.filter(x => x.items.length), row = x => `<tr><td><span class="sym" data-go="${esc(x.sym)}">${esc(x.sym)}</span> <span class="muted small">${esc(x.name)}</span></td><td class="r">${fmt(x.price)}</td><td class="r ${cls(x.pct)}">${sgn(x.pct)}%</td><td class="r muted small">${capStr(x.cap)}</td></tr>`;
      el.innerHTML = '<div class="grid2">' + ok.map(sc => { const v = sc.items.filter(x => Number.isFinite(x.pct)), avg = v.reduce((a, x) => a + x.pct, 0) / (v.length || 1);
        return `<div class="card"><div class="dh"><h3 style="margin:0">${esc(sc.name)} <span class="muted small">市值前 ${sc.items.length}</span></h3><span class="${cls(avg)}">均值 ${sgn(avg)}%</span></div><table><tbody>${sc.items.map(row).join('')}</tbody></table></div>`; }).join('') + '</div><div class="muted small" style="padding:10px 4px">每个板块按市值从大到小排列,含在美上市的外国公司(ADR);数据来自 Yahoo,可能有延迟。</div>';
      return;
    }
  }
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
  const logo = sym => `<img class="clogo" src="https://static2.finnhub.io/file/publicdatany/finnhubimage/stock_logo/${encodeURIComponent(sym)}.png" alt="${esc(sym[0])}" loading="lazy" onerror="this.outerHTML='<span class=clogo-fb>'+this.alt+'</span>'">`;
  el.innerHTML = tabs + `<div class="grid2">${['盘前', '盘后'].map(k => `<div class="card sess"><h4>${k}发布 · ${E[k].length} 家 <span class="muted small">市值 > 50 亿美元</span></h4>
    ${E[k].length ? `<table><thead><tr><th>公司</th><th class="r">预期EPS</th><th class="r">预期营收</th></tr></thead><tbody>${E[k].map(e => `<tr><td class="cname">${logo(e.sym)}<div><span class="sym" data-go="${esc(e.sym)}">${esc(e.sym)}</span><span class="muted small cfull">${esc(e.name)}</span></div></td><td class="r">${e.eps}${e.cur ? ' <span class="muted small">' + esc(e.cur) + '</span>' : ''}</td><td class="r">${e.rev}</td></tr>`).join('')}</tbody></table>` : '<div class="muted small">暂无</div>'}</div>`).join('')}</div>`;
}
// ===== 涨跌幅榜 =====
async function renderMovers() {
  const el = $('#view-movers'); loading(el);
  let M = null; if (Data.loadMovers) { try { M = await Data.loadMovers(); } catch { } }
  if (state.tab !== 'movers') return;
  if (M) {   // 全市场榜单(已过滤 5 美元以下的小壳股)
    const mrow = x => `<tr><td><span class="sym" data-go="${esc(x.sym)}">${esc(x.sym)}</span> <span class="muted small">${esc(x.name)}</span></td><td class="r">${fmt(x.price)}</td><td class="r ${cls(x.pct)}">${sgn(x.pct)}%</td><td class="r muted small">${Number.isFinite(x.vol) && Number.isFinite(x.price) ? '成交额 ' + capStr(x.vol * x.price) : ''}</td></tr>`;
    const box = (t, b) => `<div class="card"><h3 style="margin-top:0">${t}</h3>${b.items.length ? `<table><tbody>${b.items.map(mrow).join('')}</tbody></table>` : '<div class="muted small">过滤小壳股后暂无</div>'}</div>`;
    el.innerHTML = `<div class="grid2">${box('涨幅榜 · 前 30', M.gainers)}${box('跌幅榜 · 前 30', M.losers)}${box('成交榜 · 前 30(按成交量)', M.actives)}</div><div class="muted small" style="padding:10px 4px">已过滤市值低于 20 亿美元或股价低于 5 美元的股票;数据来自 Yahoo,可能有延迟。</div>`;
    return;
  }
  try { await Data.refreshQuotes(universe()); } catch { }
  if (state.tab !== 'movers') return;
  const all = universe().map(Data.quote).filter(q => Number.isFinite(q.price)), top = (a, t) => `<div class="card"><h3 style="margin-top:0">${t}</h3><table><tbody>${a.map(q => qrow(q.sym)).join('')}</tbody></table></div>`;
  const byPct = [...all].sort((a, b) => b.pct - a.pct), byVol = [...all].sort((a, b) => b.volume * b.price - a.volume * a.price);
  el.innerHTML = `<div class="grid2">${top(byPct.slice(0, 10), '涨幅榜')}${top(byPct.slice(-10).reverse(), '跌幅榜')}${top(byVol.slice(0, 10), '成交额榜')}</div>`;
}
// ===== 股票推荐(只有一个组合:强趋势龙头,中期)=====
const capStr = n => !n ? '--' : n >= 1e12 ? (n / 1e12).toFixed(2) + 'T' : n >= 1e10 ? (n / 1e9).toFixed(0) + 'B' : n >= 1e9 ? (n / 1e9).toFixed(1) + 'B' : (n / 1e6).toFixed(0) + 'M';
const SESSION = { pre: '盘前', mid: '盘中(K 线未走完,收盘后会更新)', post: '盘后最终' };
const ST_LABEL = { NEW: '新入选', STILL_VALID: '持续在名单' };
const REGIME = { BULL: '牛市(SPY 在 200 日线上,50 日线上升)', BEAR: '熊市(SPY 在 200 日线下,200 日线下降)', NEUTRAL: '中性' };
function pickRow3(r, i) {
  const p = (v, d = 0) => Number.isFinite(v) ? (v * 100).toFixed(d) + '%' : '--', rk = r.ranks || {};
  return `<div class="prow"><div class="ph"><span class="prank">${i}</span><span class="sym" data-go="${esc(r.sym)}">${esc(r.sym)}</span> <span class="muted small">${esc(r.name)}</span><span class="r ${cls(r.day)} pday">${sgn(r.day)}%</span></div>
    <div class="pm"><b>${fmt(r.price)}</b> <span class="muted small">市值 ${capStr(r.cap)} · 入选于 ${esc(r.since)}</span></div>
    <div class="muted small" style="line-height:1.7">离 200 日线 <b>${sgn(r.dist200 * 100, 0)}%</b>(同类前 ${(100 - (rk.dist200 || 0) * 100).toFixed(0)}%) · 3 个月 ${sgn(r.mom63 * 100, 0)}% · 6 个月 ${sgn(r.mom126 * 100, 0)}%<br>日波动 ATR ${p(r.atrp, 1)} · beta ${r.beta} · RSI ${r.rsi} · 离 52 周高点回撤 ${p(r.dd52)}</div>
    <div class="ptags"><span class="ptag ${r.status === 'NEW' ? 'ok' : ''}">${ST_LABEL[r.status] || r.status}</span>${r.beta >= 1.5 ? '<span class="ptag warn">高 beta</span>' : ''}${r.atrp >= 0.05 ? '<span class="ptag warn">日波动大</span>' : ''}${r.rsi >= 75 ? '<span class="ptag warn">RSI 偏热</span>' : ''}</div></div>`;
}
async function renderPicks() {
  const el = $('#view-picks'); loading(el);
  let P = null; if (Data.loadPicks) { try { P = await Data.loadPicks(); } catch { } }
  if (state.tab !== 'picks') return;
  if (!P) { el.innerHTML = '<div class="card muted">暂无推荐数据。运行 python3 tools/picks.py 生成,或等待每日自动更新。</div>'; return; }
  if (P.version !== 3) { el.innerHTML = '<div class="card muted">推荐数据版本过旧,请重新运行 python3 tools/picks.py</div>'; return; }
  const t = P.presets[0], ru = P.rules || { entry: {}, stay: {} };
  const top = k => `前 ${((1 - ru.entry[k]) * 100).toFixed(0)}%`;
  el.innerHTML = `<div class="pnote"><b>每日推荐 · 强趋势龙头(中期)</b><span class="muted small"> ${P.session ? esc(SESSION[P.session] || '') + ' · ' : ''}行情日期 ${esc(P.dataDate)} · 更新于 ${esc(P.asof)} · 合格股票 ${P.universe} 只 · 市场环境:${esc(REGIME[P.regime] || P.regime)}</span></div>
    <div class="card small" style="line-height:1.8"><b>这个组合选什么</b>
      <p style="margin:6px 0">在市值 ≥ 50 亿美元、成交额靠前的一半股票里,同时满足:<b>离 200 日线的距离 ${top('dist200')}</b>、<b>日波动(ATR%)${top('atrp')}</b>、<b>3 个月涨幅 ${top('mom63')}</b>——也就是已经走出强趋势、而且波动较大的领涨龙头。适合的参考持有期是 <b>30 到 120 天</b>,不适合短线。已在名单里的股票,只要仍满足放宽后的条件就继续保留,名单不会天天换。</p>
      <p class="muted" style="margin:0"><b>要先知道:</b>这是高 beta 的趋势押注。回测里组合的 beta 约 1.8,最大回撤约 -37%(标普 -19%),收益集中在少数年份和主题(AI、存储、加密龙头)。不是稳赢,不保证收益,可能亏损,请自行判断风险。</p></div>
    <div class="picks" style="display:grid;grid-template-columns:minmax(300px,520px);gap:18px"><div class="card pcol"><h3 style="margin:0">${esc(t.name)}</h3><div class="muted small" style="margin:4px 0 8px">当前名单 ${t.confirmedTotal} 只${t.confirmedTotal > t.confirmed.length ? `,显示离 200 日线最远的前 ${t.confirmed.length} 只` : ''}</div>
      ${t.confirmed.length ? t.confirmed.map((r, i) => pickRow3(r, i + 1)).join('') : '<div class="muted small" style="padding:8px 0">今天没有股票满足条件。不会为了凑数降低标准。</div>'}
      ${t.others && t.others.length ? `<div class="small" style="margin-top:12px"><b>名单里的其他股票</b> <span class="muted">(共 ${t.others.length} 只)</span><div class="chips" style="margin-top:6px">${t.others.map(x => `<button class="chip" data-go="${esc(x)}">${esc(x)}</button>`).join('')}</div></div>` : ''}
      ${t.invalidated && t.invalidated.length ? `<div class="small" style="margin-top:12px"><b>最近失效(跌出放宽后的条件)</b></div>${t.invalidated.map(x => `<div class="muted small"><span class="sym" data-go="${esc(x.sym)}">${esc(x.sym)}</span> ${esc(x.name)}(${esc(x.date)})</div>`).join('')}` : ''}</div></div>
    <div class="card small" style="line-height:1.8"><b>回测结论(如实披露)</b>
      <p style="margin:6px 0">用约 1200 只股票、10 年日线回测:这类条件在样本内外都有正的超额收益,但<b>不是稳赢</b>。</p>
      <details><summary class="muted">查看依据和限制</summary>
        <ul class="clist">
          <li>每笔交易(60 天,样本外 2023 年起):扣掉 beta 后超额 +4.0%、原始超标普 +7.4%(按月 t=2.0);120 天组合扣 beta 超额 +8.3%。阈值周围的 96% 到 100% 组合样本外都为正,不是单个尖峰。</li>
          <li>但等权组合的 beta 约 1.8 到 1.95:样本外年化 +34% 到 +47%,最大回撤约 -37%,标普是 +20% / -19%。和「同 beta 的杠杆标普」比,30、60 天组合多约 6 到 9 个百分点,<b>120 天组合没有跑赢</b>;夏普都低于杠杆标普。样本内的优势(+30% 对 +10%)比样本外大得多,优势在衰减。</li>
          <li>收益集中:2020 年和 2025 年贡献最大,2021 年、2026 年为负;样本外贡献最大的 10 只(LITE、WDC、MU、STX、PLTR、BE、APP、CIEN、VST、MSTR 等)占正贡献的 60% 到 70%。</li>
          <li>幸存者偏差去不掉(回测股票池里没有退市的公司),这类「强趋势、高波动」的选股方法对它最敏感;用「当时估计市值」筛选后结果几乎不变,说明不只是「今天才变大」的前视偏差。</li>
          <li>我们也测过其他条件(趋势+基本面、强势回调、超跌反转、短线「超跌-企稳-放量反弹」形态、短线 1 到 10 天的各种变量),样本外没有稳定优势,已不再使用。</li>
        </ul>
        <div class="muted">限制:只测了技术条件;样本外 2023 年起基本是牛市;试了很多参数组合,有运气成分。完整报告在代码仓库的 tools/signal_report.md、signal_validation.md、signal_validation2.md。</div>
      </details></div>
    <div class="muted small" style="padding:8px 4px;line-height:1.7">这是模型按事先写好的条件给出的信号,不保证收益,可能亏损,请自行判断风险。市场数据来自 Yahoo 免费接口,可能有延迟或错误。</div>`;
}
// ===== 宏观 =====
function spark(v, w = 120, h = 34) {
  if (!v || v.length < 2) return ''; const lo = Math.min(...v), hi = Math.max(...v), r = hi - lo || 1;
  const pts = v.map((y, i) => (i / (v.length - 1) * w).toFixed(1) + ',' + (h - 3 - (y - lo) / r * (h - 6)).toFixed(1)).join(' ');
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>`;
}
async function renderMacro() {
  const el = $('#view-macro'); loading(el);
  let M = null; if (Data.loadMacro) { try { M = await Data.loadMacro(); } catch { } }
  if (state.tab !== 'macro') return;
  if (!M || !M.items.length) { el.innerHTML = '<div class="card muted">暂无宏观数据</div>'; return; }
  const card = i => { const d = i.prev == null ? NaN : i.value - i.prev;
    return `<div class="card mac"><div class="muted small">${esc(i.name)}</div><div class="mv"><b>${fmt(i.value, i.unit === '千人' ? 0 : 2)}</b><span class="muted small"> ${esc(i.unit)}</span></div>
      <div class="mrow"><span class="${Number.isFinite(d) ? cls(d) : 'muted'} small">${Number.isFinite(d) ? '较上期 ' + sgn(d, i.unit === '千人' ? 0 : 2) : ''}</span><span class="spk">${spark(i.hist)}</span></div><div class="muted small">${esc(i.date)}</div></div>`; };
  el.innerHTML = `<div class="grid3">${M.items.map(card).join('')}</div>
    <div class="card"><h3 style="margin-top:0">未来一个月重要数据发布</h3>${M.calendar.length ? `<table><tbody>${M.calendar.map(x => `<tr><td class="muted">${esc(x.date)}</td><td>${esc(x.name)}</td></tr>`).join('')}</tbody></table>` : '<div class="muted small">暂无</div>'}</div>
    <div class="muted small" style="padding:6px 4px">数据来自美联储圣路易斯分行 FRED,发布日期以官方为准。</div>`;
}
// ===== 推送提醒 =====
async function renderAlerts() {
  const el = $('#view-alerts');
  el.innerHTML = `<div class="card"><h3 style="margin-top:0">市场快讯</h3><ul class="news" id="macroNews"><li class="muted">加载中…</li></ul></div>`;
  let l; try { l = await Data.loadNews(''); } catch { l = { error: '新闻加载失败' }; }
  if (state.tab === 'alerts') $('#macroNews').innerHTML = newsHTML(l);
}
const renderers = { mylist: renderWatch, sectors: renderSectors, earnings: renderEarnings, movers: renderMovers, picks: renderPicks, macro: renderMacro, alerts: renderAlerts };
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
