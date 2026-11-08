// 模拟数据层。第2阶段会换成真实 API,界面代码(app.js)不用改,只要保持这些函数名不变。
const MockData = (() => {
  function rng(seed) { let s = seed >>> 0; return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296; }
  function hash(str) { let h = 7; for (const c of str) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h; }
  const gauss = r => { let u = 0; for (let i = 0; i < 6; i++) u += r(); return (u - 3) / 0.7071; };

  // [代码, 名称, 现价, 日波动率]
  const U = {
    AAPL: ['苹果', 228, .016], NVDA: ['英伟达', 142, .028], VOO: ['标普500 ETF', 540, .008], QQQ: ['纳指100 ETF', 510, .011],
    MSFT: ['微软', 425, .015], GOOGL: ['谷歌', 178, .018], META: ['Meta', 590, .022], AMZN: ['亚马逊', 200, .019], TSLA: ['特斯拉', 260, .035],
    MU: ['美光', 105, .03], WDC: ['西部数据', 68, .03], STX: ['希捷', 98, .025], SNDK: ['闪迪', 835, .035],
    AMD: ['AMD', 150, .03], AVGO: ['博通', 170, .026], TSM: ['台积电', 190, .022], INTC: ['英特尔', 24, .03], QCOM: ['高通', 165, .02],
    SMCI: ['超微电脑', 38, .05], VRT: ['维谛', 115, .033], ANET: ['Arista', 390, .025], ORCL: ['甲骨文', 175, .022], DELL: ['戴尔', 125, .026],
    COST: ['开市客', 920, .012], WMT: ['沃尔玛', 90, .01], MCD: ['麦当劳', 290, .01], NKE: ['耐克', 78, .02], SBUX: ['星巴克', 95, .018],
    LMT: ['洛克希德', 560, .012], RTX: ['雷神', 125, .012], NOC: ['诺格', 480, .012], GD: ['通用动力', 295, .011],
    JPM: ['摩根大通', 235, .013], XOM: ['埃克森', 115, .013], LLY: ['礼来', 800, .02], NFLX: ['奈飞', 750, .022]
  };
  const SECTORS = {
    '存储': ['MU', 'WDC', 'STX', 'SNDK'],
    '半导体': ['NVDA', 'AMD', 'AVGO', 'TSM', 'INTC', 'QCOM'],
    'AI 基建': ['SMCI', 'VRT', 'ANET', 'ORCL', 'DELL'],
    '科技巨头': ['AAPL', 'MSFT', 'GOOGL', 'META', 'AMZN'],
    '消费': ['COST', 'WMT', 'MCD', 'NKE', 'SBUX'],
    '军工': ['LMT', 'RTX', 'NOC', 'GD']
  };
  const INDICES = [ // [代码, 名称, 点位, 波动]
    ['SPX', '标普500', 6850, .008], ['IXIC', '纳斯达克', 22800, .011], ['DJI', '道琼斯', 44800, .007],
    ['GOLD', '黄金', 3950, .01], ['TLT', 'TLT 长债ETF', 88, .006], ['VIX', 'VIX 恐慌指数', 17, .05],
    ['US10Y', '10年美债收益率', 4.15, .015], ['DXY', '美元指数', 99, .004], ['WTI', 'WTI 原油', 61, .018], ['BTC', '比特币', 102000, .025]
  ];
  const info = {}; INDICES.forEach(i => info[i[0]] = { name: i[1], base: i[2], vol: i[3], index: true });
  Object.entries(U).forEach(([s, v]) => info[s] = { name: v[0], base: v[1], vol: v[2] });

  const N = 1300;
  function weekdays(n) {
    const out = [], d = new Date(); d.setHours(12, 0, 0, 0);
    while (out.length < n) { if (d.getDay() % 6) out.unshift(new Date(d)); d.setDate(d.getDate() - 1); }
    return out;
  }
  const dates = weekdays(N);
  const fmtD = d => d.toISOString().slice(0, 10);
  const cache = {};
  function daily(sym) {
    if (cache[sym]) return cache[sym];
    const m = info[sym], r = rng(hash(sym)), px = [100];
    for (let i = 1; i < N; i++) px.push(px[i - 1] * (1 + gauss(r) * m.vol + 0.0003));
    const k = m.base / px[N - 1];
    const bars = px.map((c0, i) => {
      const c = c0 * k, o = i ? px[i - 1] * k : c, hi = Math.max(o, c) * (1 + r() * m.vol * .6), lo = Math.min(o, c) * (1 - r() * m.vol * .6);
      return { t: fmtD(dates[i]), o, h: hi, l: lo, c, v: Math.round((1 + r()) * 3e7 * (m.base > 300 ? .2 : 1) * (1 + Math.abs(c - o) / o * 30)) };
    });
    return (cache[sym] = bars);
  }
  // 日内:基于最近几天的日线造分钟线
  function intraday(sym, days, per, stepMin) {
    const d = daily(sym), r = rng(hash(sym + 'i' + per)), out = [], k0 = Math.sqrt(13 / per);
    for (let k = d.length - days; k < d.length; k++) {
      const b = d[k]; let p = b.o;
      for (let j = 0; j < per; j++) {
        const target = b.o + (b.c - b.o) * (j + 1) / per, o = p;
        const c = j === per - 1 ? b.c : target + gauss(r) * (b.h - b.l) * .12 * k0;
        const mins = 9 * 60 + 30 + j * stepMin;
        out.push({ t: b.t + ' ' + String(mins / 60 | 0).padStart(2, '0') + ':' + String(mins % 60).padStart(2, '0'),
          o, c, h: Math.min(b.h, Math.max(o, c) * (1 + r() * .002 * k0)), l: Math.max(b.l, Math.min(o, c) * (1 - r() * .002 * k0)), v: Math.round(b.v / per * (.5 + r())) });
        p = c;
      }
    }
    return out;
  }
  function agg(bars, keyFn) {
    const out = []; let key = null;
    for (const b of bars) {
      const k = keyFn(b);
      if (k !== key) { out.push({ ...b }); key = k; }
      else { const c = out[out.length - 1]; c.h = Math.max(c.h, b.h); c.l = Math.min(c.l, b.l); c.c = b.c; c.v += b.v; }
    }
    return out;
  }
  const weekKey = b => { const d = new Date(b.t + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() - (d.getUTCDay() + 6) % 7); return d.toISOString().slice(0, 10); };
  const bcache = {};
  function periodBars(sym, p) {
    const key = sym + '|' + p; if (bcache[key]) return bcache[key];
    const d = daily(sym); let out;
    if (p === 'D') out = d;
    else if (p === 'W') out = agg(d, weekKey);
    else if (p === 'M') out = agg(d, b => b.t.slice(0, 7));
    else if (p === 'Q') out = agg(d, b => b.t.slice(0, 4) + 'Q' + (Math.floor((+b.t.slice(5, 7) - 1) / 3)));
    else if (p === 'Y') out = agg(d, b => b.t.slice(0, 4));
    else if (p === '1m') out = intraday(sym, 5, 390, 1);
    else if (p === '5m') out = intraday(sym, 40, 78, 5);
    else if (p === '15m') out = intraday(sym, 40, 26, 15);
    else if (p === '1h') out = intraday(sym, 250, 7, 60);
    else out = agg(periodBars(sym, '1h'), b => b.t.slice(0, 10) + (b.t.slice(11) < '13:30' ? 'A' : 'B'));   // 4h
    return (bcache[key] = out);
  }
  const live = {}; // 模拟实时跳动
  function tick() { Object.keys(info).forEach(s => { const r = Math.random(); live[s] = (live[s] || 0) + (r - .5) * info[s].vol * .06; }); }

  return {
    mode: 'mock',
    info, U, SECTORS, INDICES,
    quote(sym) {
      const d = daily(sym), last = d[d.length - 1], prev = d[d.length - 2], adj = 1 + (live[sym] || 0);
      const price = last.c * adj;
      return { sym, name: info[sym].name, price, prev: prev.c, change: price - prev.c, pct: (price / prev.c - 1) * 100,
        high: Math.max(last.h, price), low: Math.min(last.l, price), open: last.o, volume: last.v, index: !!info[sym].index };
    },
    // 返回 {bars:[{t,o,h,l,c,v}...]},period: D W M Q Y 1m 5m 15m 1h 4h
    bars(sym, period) { return { bars: periodBars(sym, period) }; },
    news(sym) {
      const r = rng(hash(sym || 'all') + new Date().getHours());
      const T = sym ? [
        `${sym} 盘中异动,成交量明显放大`, `分析师上调 ${sym} 目标价,看好下半年业绩`, `${sym} 管理层在行业会议上谈及新产品进展`,
        `机构披露 ${sym} 最新持仓变动`, `${sym} 期权市场出现大额成交`, `${sym} 供应链消息:订单能见度提升`
      ] : [
        '美联储官员讲话偏鸽,市场押注年内再度降息', '非农就业数据超预期,美债收益率走高', 'OPEC+ 讨论调整产量,原油震荡',
        'AI 资本开支继续上修,半导体板块领涨', '黄金再创阶段新高,避险情绪升温', '中美贸易谈判传出新进展', '财报季进入高峰,盘前多家公司发布业绩'
      ];
      return T.map((t, i) => ({ title: t, src: ['路透', '彭博', '华尔街日报', 'CNBC', 'MarketWatch'][i % 5], minsAgo: 8 + i * 37 + (r() * 20 | 0), hot: i < 2 })).slice(0, sym ? 6 : 7);
    },
    earnings(dayOffset) {
      const syms = Object.keys(U).filter(s => !['VOO', 'QQQ'].includes(s)), r = rng(1000 + dayOffset), out = { 盘前: [], 盘中: [], 盘后: [] };
      syms.forEach(s => { if (r() < .22) { const k = r(); out[k < .4 ? '盘前' : k < .45 ? '盘中' : '盘后'].push({ sym: s, name: info[s].name, eps: (r() * 3 + .3).toFixed(2), rev: (r() * 40 + 2).toFixed(1) + 'B' }); } });
      return out;
    },
    tick,
    // 与真实数据层保持相同的异步接口
    async refreshQuotes() { tick(); },
    async loadBars() { },
    detail(sym) {
      const d = daily(sym), l = d[d.length - 1], y = d.slice(-252), q = this.quote(sym), avg = (l.h + l.l + l.c) / 3;
      return { wk52h: Math.max(...y.map(b => b.h)), wk52l: Math.min(...y.map(b => b.l)), ath: Math.max(...d.map(b => b.h)), atl: Math.min(...d.map(b => b.l)),
        amp: (q.high - q.low) / q.prev * 100, avg, turnover: avg * l.v, volume: l.v };
    },
    async loadDetail() { },
    async loadCompany() { return { error: 'mock' }; },
    async loadFin() { return { error: 'mock' }; },
    async loadNews(sym) { return this.news(sym); },
    async loadEarnings(d) { return this.earnings(Math.round((d - new Date()) / 864e5)); },
    async search(q) { q = q.toUpperCase(); return { items: Object.keys(info).filter(s => s.includes(q) || String(info[s].name || '').toUpperCase().includes(q)).slice(0, 8).map(s => ({ sym: s, name: info[s].name || s, type: 'EQUITY', ex: '' })) }; },
    async validate(sym) { return !!info[sym]; }
  };
})();
