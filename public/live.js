// 真实数据层:通过本站的 /api 后台取数据(Key 只在后台,网页里没有任何密钥)
const LiveData = (() => {
  const M = MockData, qc = {}, bc = {}, dc = {};
  const api = async p => { const r = await fetch(p); if (!r.ok) throw new Error('API ' + r.status); return r.json(); };
  const blank = sym => ({ sym, name: (M.info[sym] || {}).name || sym, price: NaN, prev: NaN, change: 0, pct: 0, high: NaN, low: NaN, open: NaN, volume: 0 });
  const WHEN = ['盘前', '盘中', '盘后'];
  return {
    mode: 'live', info: M.info, U: M.U, SECTORS: M.SECTORS, INDICES: M.INDICES,
    quote: sym => qc[sym] || blank(sym),
    async refreshQuotes(syms) {
      const list = await api('/api/quotes?symbols=' + encodeURIComponent([...new Set(syms)].join(',')));
      list.forEach(q => { if (M.info[q.sym]) q.name = M.info[q.sym].name; qc[q.sym] = q; });
    },
    bars: (sym, period) => bc[sym + '|' + period],
    async loadBars(sym, period) { bc[sym + '|' + period] = await api(`/api/bars?symbol=${encodeURIComponent(sym)}&period=${period}`); },
    detail: sym => dc[sym],
    async loadDetail(sym) { dc[sym] = await api('/api/detail?symbol=' + encodeURIComponent(sym)); },
    async loadCompany(sym) { return api('/api/company?symbol=' + encodeURIComponent(sym)); },
    async loadHealth(sym) { return api('/api/fin?part=health&symbol=' + encodeURIComponent(sym)); },
    async loadEM(sym) { return api('/api/fin?part=em&symbol=' + encodeURIComponent(sym)); },
    async loadProfile(sym) { return api('/api/company?part=profile&symbol=' + encodeURIComponent(sym)); },
    async loadFin(sym) { return api('/api/fin?symbol=' + encodeURIComponent(sym)); },
    async loadSeg(sym) { return api('/api/fin?part=seg&symbol=' + encodeURIComponent(sym)); },
    async loadSectors() { const r = await api('/api/movers?part=sectors'); if (!r.sectors) throw new Error('x'); return r; },
    async loadSector(name) { const r = await api('/api/movers?part=sector&name=' + encodeURIComponent(name)); if (!r.sectors || !r.sectors.length) throw new Error('x'); return r.sectors[0]; },
    async screen(qs) { const r = await api('/api/movers?' + qs); if (!r.items) throw new Error('x'); return r; },
    async loadMovers() { const r = await api('/api/movers'); if (r.error) throw new Error(r.error); return r; },
    async loadPicks() { const r = await fetch('/screener.json?t=' + Math.floor(Date.now() / 600000)); if (!r.ok) throw new Error('none'); return r.json(); },
    async loadMacro() { const r = await api('/api/macro'); if (r.error) throw new Error(r.error); return r; },
    async loadNews(sym) {
      const r = await api('/api/news?symbol=' + encodeURIComponent(sym || ''));
      if (r.error === 'no_key') return { error: '暂无资讯' };
      return r.items.map(x => ({ title: x.title, src: x.src, url: x.url, minsAgo: Math.max(1, Math.round((Date.now() / 1000 - x.ts) / 60)), hot: false }));
    },
    async loadEarnings(d) {
      const ds = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
      const r = await api('/api/earnings?date=' + ds), out = { 盘前: [], 盘后: [] };
      if (r.error) return { error: '暂无数据' };
      r.items.forEach(x => { if (out[x.when]) out[x.when].push({ sym: x.sym, name: x.name || (M.info[x.sym] || {}).name || '', eps: x.eps == null ? '--' : x.eps.toFixed(2), rev: x.rev ? (x.rev / 1e9).toFixed(1) + 'B' + (x.cur && x.cur !== 'USD' ? ' ' + x.cur : '') : '--', cur: x.cur && x.cur !== 'USD' ? x.cur : '', cap: x.cap }); });
      return out;
    },
    async search(q) { return api('/api/search?q=' + encodeURIComponent(q)); },
    async validate(sym) { await this.refreshQuotes([sym]); return !!qc[sym]; }
  };
})();
