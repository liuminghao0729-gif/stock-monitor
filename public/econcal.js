// 经济日历的展示逻辑(纯函数,离线测试见 tools/test_econcal.js):把后端返回的经济事件按日期分组,并写成大白话列表。
// 数据只有「日期」没有具体发布时间,所以页面不写时间;每条事件带一句通俗说明。
(function (root) {
  const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const parse = s => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s || '')); return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null; };
  const WK = '日一二三四五六';

  // 按日期分组;label = 今天 / 明天 / N 天后;past 的(早于今天)不显示
  function econGroups(items, today) {
    const t0 = parse(today), by = new Map();
    if (!t0 || !Array.isArray(items)) return [];
    for (const it of items) {
      const d = parse(it && it.date); if (!d || d < t0) continue;
      if (!by.has(it.date)) by.set(it.date, []);
      by.get(it.date).push(it);
    }
    return [...by.keys()].sort().map(k => {
      const d = parse(k), n = Math.round((d - t0) / 864e5);
      return { date: k, md: `${d.getMonth() + 1}/${d.getDate()}`, wk: '周' + WK[d.getDay()], label: n === 0 ? '今天' : n === 1 ? '明天' : `${n} 天后`, days: n,
        items: by.get(k).slice().sort((a, b) => (b.imp || 0) - (a.imp || 0)) };
    });
  }
  const IMP = { 3: ['重要', 'e3'], 2: ['一般', 'e2'] };

  function econHTML(data, today) {
    const head = '<h3 style="margin-top:0">未来 30 天重要经济事件 <span class="muted small">只有日期,没有具体发布时间,以官方公布为准;日程可能调整</span></h3>';
    if (!data) return head + '<div class="muted small">经济事件暂时加载失败。</div>';
    if (data.mock) return head + '<div class="muted small">演示模式没有经济日历。</div>';
    const g = econGroups(data.items, today);
    const warn = data.fred === false ? '<div class="muted small" style="margin:6px 0">经济数据(CPI、非农、GDP 等)的发布日程暂时取不到,下面只有 FOMC 会议。</div>' : '';
    if (!g.length) return head + warn + '<div class="muted small">未来 30 天没有收录的重要经济事件。</div>';
    const rows = g.map(x => `<div class="egrp"><div class="edate"><b>${x.md}</b> ${x.wk} <span class="muted small">${x.label}</span></div><div class="eitems">${x.items.map(i => {
      const m = IMP[i.imp] || ['', 'e1'];
      return `<div class="eit"><span class="eimp ${m[1]}">${m[0]}</span><b>${esc(i.name)}</b><div class="muted small">${esc(i.desc || '')}</div></div>`;
    }).join('')}</div></div>`).join('');
    return head + warn + rows + '<div class="muted small" style="margin-top:8px;line-height:1.7">数据来源:经济数据发布日程来自 FRED(圣路易斯联储),FOMC 会议日期来自美联储官网。「重要」指对利率和市场影响通常较大的数据。</div>';
  }

  const api = { econGroups, econHTML };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else Object.assign(root, api);
})(typeof window !== 'undefined' ? window : globalThis);
