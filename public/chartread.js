// 「这张图在说什么」:把日K线上的趋势、位置、支撑压力、趋势线、成交量、波动,翻译成新手能看懂的大白话。
// 规则:每句话里的数字都由程序按日K线算出,每条都带「依据」(用了哪些数字、怎么算的);数据不够的项目直接不写,不猜。
// 纯函数,不依赖页面,方便离线测试(tools/test_chartread.js)。
(function (root) {
  const TERMS = {
    '均线': '最近一段时间收盘价的平均值连成的线,用来看大方向',
    '多头排列': '短期均线在长期均线上方,价格也在它们上方,通常说明上涨势头占优',
    '空头排列': '短期均线在长期均线下方,价格也在它们下方,通常说明下跌势头占优',
    '支撑位': '价格下跌到这里,过去常有人买入、停止下跌或反弹的价位',
    '压力位': '价格上涨到这里,过去常有人卖出、涨不上去的价位',
    '趋势线': '把几个越来越高的低点(或越来越低的高点)连起来的斜线',
    '量比': '今天的成交量 ÷ 近 10 日平均每天的成交量,大于 1 说明比平时活跃',
    '放量': '成交量明显比平时大',
    '缩量': '成交量明显比平时小',
    'ATR': '平均真实波幅:最近 14 天每天价格上下摆动的平均幅度',
    '52 周高点': '过去一年里出现过的最高价'
  };
  const KEYS = Object.keys(TERMS).sort((a, b) => b.length - a.length);
  const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  // 给名词加悬停解释(只在代码生成的文字里替换,先转义再加标签)
  function termify(text) {
    const re = new RegExp(KEYS.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'g');
    return esc(text).replace(re, m => `<abbr class="term" tabindex="0" title="${esc(TERMS[m])}">${m}</abbr>`);
  }

  const avg = (a, k) => { const s = a.slice(-k); return s.reduce((x, y) => x + y, 0) / s.length; };
  const sgnPct = (v, d = 1) => (v >= 0 ? '+' : '') + (v * 100).toFixed(d) + '%';
  const STR = s => s >= 1.8 ? '强' : s >= 1.2 ? '中' : '弱';
  const WHY = {
    '筹码': '成交密集区',
    '高点': '前高',
    '低点': '前低'
  };
  const whyOf = src => String(src).split('+').map(x => WHY[x]).filter(Boolean).join('+');

  // o: { bars:[{t,o,h,l,c,v}], price, pct(今日涨跌%), volRatio, sr(srCalc 的结果), marketOpen, isIdx }
  function chartRead(o) {
    const bars = (o && o.bars) || [], n = bars.length;
    if (n < 50 || !Number.isFinite(o.price)) return null;
    const px = o.price, c = bars.map(b => b.c); c[n - 1] = px;
    const f = (v, d = px >= 1 ? 2 : 4) => v.toFixed(d), items = [];
    const m20 = avg(c, 20), m50 = avg(c, 50), m200 = n >= 200 ? avg(c, 200) : null;
    const chg20 = px / c[n - 21] - 1;

    // 1 趋势
    {
      const up = px > m20 && m20 > m50, down = px < m20 && m20 < m50;
      let t = up ? '上涨趋势:价格在 20 日均线和 50 日均线上方,而且 20 日线在 50 日线上方(多头排列),说明近期买的人更占优势。'
        : down ? '下跌趋势:价格在 20 日均线和 50 日均线下方,而且 20 日线在 50 日线下方(空头排列),说明近期卖的人更占优势。'
          : '方向不明:价格和均线纠缠在一起,没有形成多头排列或空头排列,可以理解为在震荡。';
      if (m200 != null && (up || down)) t += up ? (px > m200 ? ' 价格也在 200 日线上方,长期趋势同样偏强。' : ' 不过价格还在 200 日线下方,长期趋势还没转强。')
        : (px < m200 ? ' 价格也在 200 日线下方,长期趋势同样偏弱。' : ' 不过价格还在 200 日线上方,长期趋势还没走坏。');
      items.push({
        key: 'trend', title: '趋势', text: t, short: t.split('。')[0] + '。', tone: up ? 'ok' : down ? 'bad' : '',
        basis: [['现价', f(px)], ['20 日均线', f(m20)], ['50 日均线', f(m50)], ['200 日均线', m200 != null ? f(m200) : '数据不足'], ['近 20 日涨跌', sgnPct(chg20)]],
        how: '价格 > 20 日线 > 50 日线 = 多头排列,反过来 = 空头排列,其他算震荡。'
      });
    }

    // 2 位置(近 252 个交易日)
    {
      const seg = bars.slice(-252), hi = Math.max(px, ...seg.map(b => b.h)), lo = Math.min(px, ...seg.map(b => b.l));
      const fromHigh = (hi - px) / hi, fromLow = px / lo - 1, pos = hi > lo ? (px - lo) / (hi - lo) : 0.5;
      const t = fromHigh <= 0.05 ? `接近一年内的高点(只比 52 周高点低 ${(fromHigh * 100).toFixed(1)}%),处在年内高位区。`
        : fromHigh >= 0.30 ? `比 52 周高点低 ${(fromHigh * 100).toFixed(1)}%,离高点还很远;比一年内最低点高 ${(fromLow * 100).toFixed(1)}%。`
          : `在过去一年价格区间的 ${(pos * 100).toFixed(0)}% 位置(0% 是一年内最低点,100% 是最高点)。`;
      items.push({
        key: 'pos', title: '位置', text: t, tone: fromHigh <= 0.05 ? 'ok' : fromHigh >= 0.30 ? 'w' : '',
        basis: [['一年内最高价', f(hi)], ['一年内最低价', f(lo)], ['离最高点', (fromHigh * 100).toFixed(1) + '%'], ['区间位置', (pos * 100).toFixed(0) + '%']],
        how: `区间位置 = (现价 − 最低) ÷ (最高 − 最低),统计${seg.length < 252 ? '上市以来 ' + seg.length : '最近 252'}个交易日。`
      });
    }

    // 3 支撑压力
    const sr = o.sr && o.sr.all;
    if (sr) {
      const ok = l => l.s >= 0.45;
      const sup = sr.filter(l => l.p < px * 0.995 && ok(l)).sort((a, b) => b.p - a.p)[0];
      const res = sr.filter(l => l.p > px * 1.005 && ok(l)).sort((a, b) => a.p - b.p)[0];
      const parts = [];
      parts.push(res ? `最近的压力位约 ${f(res.p)}(比现价高 ${((res.p / px - 1) * 100).toFixed(1)}%,强度${STR(res.s)})` : '上方附近没有明显的压力位');
      parts.push(sup ? `最近的支撑位约 ${f(sup.p)}(比现价低 ${((1 - sup.p / px) * 100).toFixed(1)}%,强度${STR(sup.s)})` : '下方附近没有明显的支撑位');
      let t = parts.join(';') + '。';
      if (res && res.p / px - 1 <= 0.02) t += ` 现价离压力位很近(只差 ${((res.p / px - 1) * 100).toFixed(1)}%),能不能突破是关键。`;
      if (sup && 1 - sup.p / px <= 0.02) t += ` 现价离支撑位很近(只差 ${((1 - sup.p / px) * 100).toFixed(1)}%),如果跌破,说明这个价位没守住。`;
      const basis = [];
      if (res) basis.push(['压力位 ' + f(res.p), `强度${STR(res.s)} · ${whyOf(res.src) || '历史推算'}`]);
      if (sup) basis.push(['支撑位 ' + f(sup.p), `强度${STR(sup.s)} · ${whyOf(sup.src) || '历史推算'}`]);
      items.push({
        key: 'sr', title: '支撑与压力', text: t, short: parts.join(';') + '。', tone: '', basis,
        how: '来自过去一年成交密集区和前高前低,多个来源重合更强。只是参考位置,价格也可能直接穿过。'
      });
    }

    // 4 趋势线
    if (o.sr && o.sr.tl && o.sr.tl.length) {
      const i1 = n - 1, a = Math.max(0, i1 - 250), j = i1 - a;
      const lines = o.sr.tl.map(t => {
        const val = Math.exp(t.yp + t.slope * (j - (t.p - a))), d = px / val - 1;
        return { t, val, d, txt: t.low ? `上升趋势线(把几个越来越高的低点连起来的线)现在约在 ${f(val)},现价在它${d >= 0 ? '上方' : '下方'} ${(Math.abs(d) * 100).toFixed(1)}%;这条线被碰到过 ${t.touches} 次。`
          : `下降趋势线(把几个越来越低的高点连起来的线)现在约在 ${f(val)},现价在它${d >= 0 ? '上方' : '下方'} ${(Math.abs(d) * 100).toFixed(1)}%;这条线被碰到过 ${t.touches} 次。` };
      }).filter(x => Number.isFinite(x.val));
      if (lines.length) items.push({
        key: 'tl', title: '趋势线', text: lines.map(x => x.txt).join(' '), tone: '',
        basis: lines.map(x => [x.t.low ? '上升趋势线' : '下降趋势线', `现值 ${f(x.val)} · 触碰 ${x.t.touches} 次`]),
        how: '连接一年内两个明显的低点(或高点),收盘价没有明显穿破,碰到越多次越可靠。'
      });
    }

    // 5 成交量
    if (!o.isIdx && Number.isFinite(o.volRatio)) {
      const v = o.volRatio, p = Number.isFinite(o.pct) ? o.pct : 0;
      let t = v >= 1.3 ? `放量:今天成交量是平时的 ${v.toFixed(2)} 倍,说明关注度明显升高` + (p >= 0.5 ? ',并且价格上涨,说明有更多资金愿意买入。' : p <= -0.5 ? ',并且价格下跌,说明卖出的压力偏大。' : '。')
        : v <= 0.8 ? `缩量:今天成交量只有平时的 ${v.toFixed(2)} 倍,交易偏冷清,这时的涨跌参考价值相对低一些。`
          : `成交量正常:今天是平时的 ${v.toFixed(2)} 倍。`;
      if (o.marketOpen) t += ' 盘中成交量还没走完,收盘后更准。';
      items.push({
        key: 'vol', title: '成交量', text: t, tone: v >= 1.3 ? 'ok' : v <= 0.8 ? 'w' : '',
        basis: [['量比', v.toFixed(2)], ['今日涨跌', Number.isFinite(o.pct) ? (p >= 0 ? '+' : '') + p.toFixed(2) + '%' : '--']],
        how: '量比 = 今天成交量 ÷ 近 10 日平均。≥ 1.3 放量,≤ 0.8 缩量。'
      });
    }

    // 6 波动(ATR14 / 现价)
    if (n >= 16) {
      const tr = []; for (let i = n - 14; i < n; i++) tr.push(Math.max(bars[i].h - bars[i].l, Math.abs(bars[i].h - bars[i - 1].c), Math.abs(bars[i].l - bars[i - 1].c)));
      const atr = tr.reduce((x, y) => x + y, 0) / tr.length, p = atr / px;
      const cls = p >= 0.03 ? '高' : p >= 0.015 ? '中等' : '低';
      items.push({
        key: 'vola', title: '波动', text: `平时一天大约上下波动 ${(p * 100).toFixed(1)}%,属于波动${cls}${cls === '高' ? ',涨跌都会很快,拿的时候要有心理准备' : ''}。`, tone: cls === '高' ? 'w' : '',
        basis: [['ATR(14 日)', f(atr)], ['占现价', (p * 100).toFixed(1) + '%']],
        how: 'ATR = 近 14 天每天最高最低价差的平均。占现价 ≥ 3% 高,1.5%–3% 中等,更低为低。'
      });
    }

    const pick = k => items.find(i => i.key === k);
    return { items, summary: [pick('trend'), pick('sr') || pick('pos')].filter(Boolean), asof: bars[n - 1].t };
  }

  // 每一项:标题 + 一句话;点「看依据」才展开完整说明、用到的数字和算法
  function itemHTML(i, cls) {
    const more = i.short && i.text.startsWith(i.short) ? i.text.slice(i.short.length).trim() : '', full = more ? `<div style="margin-bottom:6px">${termify(more)}</div>` : '';   // 只补充一句话里没有的内容,不重复
    return `<${cls === 'li' ? 'li' : 'div'} class="${cls === 'li' ? 'cr-' + (i.tone || 'n') : 'cri'}"><b>${esc(i.title)}</b> ${termify(i.short || i.text)}
      <details class="crw"><summary class="muted small">看依据</summary>${full}<div class="crbs">${i.basis.map(([k, v]) => `<span class="crb"><i>${esc(k)}</i><b>${esc(v)}</b></span>`).join('')}</div><div class="muted small crhow">${termify(i.how)}</div></details></${cls === 'li' ? 'li' : 'div'}>`;
  }
  function chartReadHTML(r) {
    if (!r) return '<div class="muted small">日K线数据不足(至少需要 50 个交易日),暂时无法解读。</div>';
    const rest = r.items.filter(i => !r.summary.includes(i));
    return `<h3>这张图在说什么 <span class="muted small">按日 K 线计算,最近数据 ${esc(r.asof)};只是描述现状,不是预测</span></h3>
      <ul class="crsum">${r.summary.map(i => itemHTML(i, 'li')).join('')}</ul>
      ${rest.length ? `<details class="crmore"><summary class="muted">再看 ${rest.length} 项:${rest.map(i => esc(i.title)).join('、')}</summary>${rest.map(i => itemHTML(i, 'div')).join('')}</details>` : ''}`;
  }

  const api = { chartRead, chartReadHTML, termify, TERMS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else Object.assign(root, api);
})(typeof window !== 'undefined' ? window : globalThis);
