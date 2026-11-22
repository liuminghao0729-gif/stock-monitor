// “数据来源与更新时间”面板:列出每类数据的来源、延迟类型,以及后台快照文件的更新日期(过旧会标出)。
// 全部是只读展示,不影响其他功能;任何一项取不到都只显示“暂无”。
(() => {
  const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const DAY = 86400000;
  const age = d => { const t = Date.parse(String(d).slice(0, 10)); return Number.isFinite(t) ? Math.floor((Date.now() - t) / DAY) : null; };
  const j = u => fetch(u + '?t=' + Math.floor(Date.now() / 600000)).then(r => r.ok ? r.json() : null).catch(() => null);

  function snapRow(name, date, maxDays, note) {
    const a = date ? age(date) : null;
    const old = a !== null && a > maxDays;
    return `<tr><td>${esc(name)}</td><td>${date ? esc(String(date).slice(0, 16)) : '暂无'}</td><td class="${old ? 'dsold' : ''}">${a === null ? '--' : a + ' 天前' + (old ? '(偏旧)' : '')}</td><td class="muted small">${esc(note)}</td></tr>`;
  }

  async function open() {
    const mask = document.createElement('div'); mask.className = 'dsmask'; mask.setAttribute('role', 'dialog'); mask.setAttribute('aria-modal', 'true');
    mask.innerHTML = '<div class="dspanel"><button class="dsx" aria-label="关闭">关闭</button><h2>数据来源与更新时间</h2><div class="muted small">加载中…</div></div>';
    document.body.appendChild(mask);
    const close = () => { mask.remove(); document.removeEventListener('keydown', onKey); };
    const onKey = e => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);
    mask.addEventListener('click', e => { if (e.target === mask) close(); });
    mask.querySelector('.dsx').onclick = close;

    const [st, scr, si, etf] = await Promise.all([j('/api/status'), j('/screener.json'), j('/short_interest.json'), j('/etf_holdings.json')]);
    const src = (st && st.sources) || [];
    const etfDates = etf ? Object.values(etf).map(x => x && x.asof).filter(Boolean).sort() : [];
    const dbg = st && st.dbg ? Object.entries(st.dbg) : [];
    mask.querySelector('.dspanel').innerHTML = `<button class="dsx" aria-label="关闭">关闭</button>
      <h2>数据来源与更新时间</h2>
      <div class="muted small">美股行情以交易所时间为准;下面的“快照”是后台定时生成的文件,日期按文件内记录显示。</div>
      <h3>实时数据接口</h3>
      ${src.length ? `<table><thead><tr><th>数据</th><th>来源</th><th>更新与延迟</th><th>备注</th></tr></thead><tbody>${src.map(x => `<tr><td>${esc(x.k)}</td><td>${esc(x.src)}</td><td>${esc(x.delay)}</td><td class="muted small">${esc(x.note)}</td></tr>`).join('')}</tbody></table>` : '<div class="muted small">暂时取不到来源清单(演示模式或后台未响应)。</div>'}
      <h3>后台快照</h3>
      <table><thead><tr><th>快照</th><th>日期</th><th>距今</th><th>说明</th></tr></thead><tbody>
        ${snapRow('每日选股', scr && (scr.dataDate || scr.asof), 4, '交易日收盘后更新;周末和休市日不更新')}
        ${snapRow('做空趋势', si && si.latest, 30, 'FINRA 半月申报,约一周后公布')}
        ${snapRow('ETF 持仓', etfDates[0], 180, 'SEC N-PORT 季度披露,滞后约 2 个月')}
        ${snapRow('公司分析文字', typeof COMPANY_ASOF !== 'undefined' ? COMPANY_ASOF + '-01' : null, 120, '人工撰写的静态内容,订单等数字以最新财报为准')}
      </tbody></table>
      ${dbg.length ? `<h3>最近出错的功能</h3><div class="small">${dbg.map(([k, v]) => `${esc(k)}:${esc(v)}`).join('<br>')}</div>` : ''}
      <div class="muted small" style="margin-top:16px;line-height:1.7">数据来自第三方,可能延迟或有误;模型信号不保证收益,可能亏损,请自行判断风险。</div>`;
    mask.querySelector('.dsx').onclick = close;
  }

  document.addEventListener('click', e => { const a = e.target.closest && e.target.closest('#dsLink'); if (a) { e.preventDefault(); open(); } });
})();
