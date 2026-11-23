// 经济日历的展示逻辑(纯函数,离线测试见 tools/test_econcal.js):把后端返回的经济事件按日期分组,并写成大白话列表。
// 数据源只给日期,发布时间按各机构的固定惯例(美东时间)标注,并换算成浏览器所在时区;每条事件带一句通俗说明。
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
        items: by.get(k).slice().sort((a, b) => ((ET_TIME[a.key] || [99, 0])[0] * 60 + (ET_TIME[a.key] || [99, 0])[1]) - ((ET_TIME[b.key] || [99, 0])[0] * 60 + (ET_TIME[b.key] || [99, 0])[1]) || (b.imp || 0) - (a.imp || 0)) };   // 同一天:发布早的在前,同时间重要的在前
    });
  }
  // 各类事件的惯常发布时间(美东时间,小时与分钟):BLS、BEA、Census 的数据多为 8:30,JOLTS 为 10:00,FOMC 决议和纪要为 14:00。
  // 这是惯例而不是逐条查证的时间,页面上会写明「通常」,以官方公布为准。
  const ET_TIME = { cpi: [8, 30], jobs: [8, 30], gdp: [8, 30], pce: [8, 30], ppi: [8, 30], retail: [8, 30], jolts: [10, 0], fomc: [14, 0], fomc_min: [14, 0] };
  const p2 = n => String(n).padStart(2, '0');
  // 美东某天某时 → {et:'8:30', local:'05:30', day:相对美东日期偏移(-1/0/1), same:本地就是美东}。tz 缺省用浏览器时区。
  function econTime(date, key, tz) {
    const t = ET_TIME[key], d = parse(date); if (!t || !d) return null;
    const y = d.getFullYear(), mo = d.getMonth(), da = d.getDate();
    const etHour = ms => +new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: '2-digit', hourCycle: 'h23' }).format(ms);
    let utc = null; for (const off of [5, 4]) { const ms = Date.UTC(y, mo, da, t[0] + off, t[1]); if (etHour(ms) === t[0]) { utc = ms; break; } }
    if (utc == null) return null;
    const fmt = (zone, o) => new Intl.DateTimeFormat('en-CA', Object.assign({ timeZone: zone }, o)).format(utc);
    const zone = tz || Intl.DateTimeFormat().resolvedOptions().timeZone, o = { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' };
    const loc = fmt(zone, o), ymd = z => fmt(z, { year: 'numeric', month: '2-digit', day: '2-digit' });
    const dayDiff = Math.round((Date.parse(ymd(zone)) - Date.parse(ymd('America/New_York'))) / 864e5);
    return { et: `${t[0]}:${p2(t[1])}`, local: loc, day: dayDiff, same: loc === `${p2(t[0])}:${p2(t[1])}` && dayDiff === 0 };
  }
  const timeLabel = (tm) => !tm ? '' : tm.same ? `美东 ${tm.et}` : `美东 ${tm.et} · 你的时间 ${tm.local}${tm.day > 0 ? '(次日)' : tm.day < 0 ? '(前一天)' : ''}`;
  const IMP = { 3: ['重要', 'e3'], 2: ['一般', 'e2'] };

  function econHTML(data, today, tz) {
    const head = '<h3 style="margin-top:0">未来 30 天重要经济事件 <span class="muted small">时间按惯例标注(美东时间并换算成你的时区),以官方公布为准;日程可能调整</span></h3>';
    if (!data) return head + '<div class="muted small">经济事件暂时加载失败。</div>';
    if (data.mock) return head + '<div class="muted small">演示模式没有经济日历。</div>';
    const g = econGroups(data.items, today);
    const warn = data.fred === false ? '<div class="muted small" style="margin:6px 0">经济数据(CPI、非农、GDP 等)的发布日程暂时取不到,下面只有 FOMC 会议。</div>' : '';
    if (!g.length) return head + warn + '<div class="muted small">未来 30 天没有收录的重要经济事件。</div>';
    const rows = g.map(x => `<div class="egrp"><div class="edate"><b>${x.md}</b> ${x.wk} <span class="muted small">${x.label}</span></div><div class="eitems">${x.items.map(i => {
      const m = IMP[i.imp] || ['', 'e1'];
      return `<div class="eit"><span class="eimp ${m[1]}">${m[0]}</span><b>${esc(i.name)}</b>${timeLabel(econTime(x.date, i.key, tz)) ? ` <span class="etime">${esc(timeLabel(econTime(x.date, i.key, tz)))}</span>` : ''}<div class="muted small">${esc(i.desc || '')}</div></div>`;
    }).join('')}</div></div>`).join('');
    return head + warn + rows + '<div class="muted small" style="margin-top:8px;line-height:1.7">数据来源:经济数据发布日程来自 FRED(圣路易斯联储),FOMC 会议日期来自美联储官网。「重要」指对利率和市场影响通常较大的数据。</div>';
  }

  const api = { econGroups, econHTML, econTime };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else Object.assign(root, api);
})(typeof window !== 'undefined' ? window : globalThis);
