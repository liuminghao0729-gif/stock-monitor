// 「这家公司怎么样」:把财报和估值翻译成四个问题的大白话答案:赚不赚钱、成长快不快、财务安不安全、贵不贵。
// 规则:每个数字都来自已有的数据(SEC 财报、体检模型、Yahoo 估值指标)并由程序计算;缺数据的项目不写或写「数据不足」,不猜。
// 分档(如净利率 ≥20% 算强)是常见经验线,会在「看依据」里写明,不同行业差别很大。纯函数,离线测试见 tools/test_fundread.js。
(function (root) {
  const TERMS = {
    '毛利率': '每卖 100 元,扣掉直接成本后剩多少',
    '营业利润率': '每卖 100 元,扣掉所有日常经营开支后剩多少',
    '净利率': '每卖 100 元,最后落到股东口袋里的利润有多少',
    '同比': '和去年同一时期比',
    '自由现金流': '经营赚回来的现金,扣掉维持和扩大生意必须花的钱之后,真正能自由支配的部分',
    '市盈率': '股价 ÷ 每股盈利,可以理解为按现在的盈利,多少年能赚回股价',
    'PEG': '市盈率 ÷ 预期盈利增速,用来判断高市盈率有没有增长撑着',
    '现金流折现': '把公司未来能赚的现金,按风险折算成今天值多少钱的估值方法',
    'Altman Z 分数': '一个评估破产风险的经典指标,分数越高越安全',
    'Piotroski F 分数': '用 9 条是/否检验给公司财务质量打分,满分 9',
    '净债务': '债务减去手头现金,为正说明欠的比有的多'
  };
  const KEYS = Object.keys(TERMS).sort((a, b) => b.length - a.length);
  const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function termify(text) {
    const re = new RegExp(KEYS.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'g');
    return esc(text).replace(re, m => `<abbr class="term" tabindex="0" title="${esc(TERMS[m])}">${m}</abbr>`);
  }
  const num = v => typeof v === 'number' && Number.isFinite(v);
  const usd = v => { if (!num(v)) return '--'; const a = Math.abs(v), s = v < 0 ? '-' : ''; return s + (a >= 1e12 ? (a / 1e12).toFixed(2) + ' 万亿美元' : a >= 1e8 ? (a / 1e8).toFixed(a >= 1e10 ? 0 : 1) + ' 亿美元' : (a / 1e4).toFixed(0) + ' 万美元'); };
  const pc = (v, d = 1) => (v >= 0 ? '+' : '') + v.toFixed(d) + '%';

  // o: { fin:{ttm,rows,years}, health:{checkup,fscore,zscore,dcf,price}|null, stats:{forwardPE,pegRatio}|null, price }
  function fundRead(o) {
    const f = o && o.fin; if (!f || f.error || !f.ttm || !num(f.ttm.rev)) return null;
    const t = f.ttm, items = [], H = o.health || null, S = o.stats || null;
    const nowMs = num(o.now) ? o.now : Date.now(), endMs = Date.parse(t.end);
    if (!Number.isFinite(endMs) || (nowMs - endMs) / 864e5 > 200) return { stale: true, asof: t.end || '未知', items: [] };      // 财报数据停在很久以前(例如部分银行的 SEC 标签变了),不能当「最近 12 个月」用
    const price = num(o.price) ? o.price : (H && num(H.price) ? H.price : null);

    // 1 赚不赚钱
    if (num(t.nm) && num(t.ni)) {
      const loss = t.ni <= 0 || t.nm <= 0, gmWord = !num(t.gm) ? '' : t.gm >= 60 ? '产品定价权很强' : t.gm >= 40 ? '较高' : t.gm >= 20 ? '中等' : '偏低,通常竞争激烈或成本占比高';
      const verdict = loss ? '亏损' : t.nm >= 20 ? '赚钱能力强' : t.nm >= 8 ? '赚钱' : '利润很薄';
      const short = loss ? `最近 12 个月亏损,每收入 100 元亏约 ${Math.abs(t.nm).toFixed(1)} 元。` : `每收入 100 元,留下约 ${t.nm.toFixed(1)} 元净利润。`;
      const text = `最近 12 个月(到 ${t.end})收入 ${usd(t.rev)},净利润 ${usd(t.ni)}。` + (num(t.gm) ? `毛利率 ${t.gm.toFixed(1)}%${gmWord ? '(' + gmWord + ')' : ''}` : '') + (num(t.om) ? `,营业利润率 ${t.om.toFixed(1)}%` : '') + `,净利率 ${t.nm.toFixed(1)}%。`;
      const gmShort = !num(t.gm) ? '' : t.gm >= 60 ? '定价权很强' : t.gm >= 40 ? '较高' : t.gm >= 20 ? '中等' : '偏低';
      items.push({
        key: 'profit', q: '赚不赚钱', verdict, tone: loss ? 'bad' : t.nm >= 8 ? 'ok' : 'w', short, text,
        chips: [['净利率', t.nm.toFixed(1) + '%', ''], ['毛利率', num(t.gm) ? t.gm.toFixed(1) + '%' : '数据不足', gmShort], ['营业利润率', num(t.om) ? t.om.toFixed(1) + '%' : '数据不足', '']],
        lines: [`最近 12 个月(到 ${t.end}):收入 ${usd(t.rev)},净利润 ${usd(t.ni)}`],
        explain: '净利率 = 净利润 ÷ 收入;毛利率越高,说明产品越难被替代。',
        rules: ['净利率 ≥20% 强 · 8%–20% 一般 · <8% 偏薄(经验线,各行业差别大)']
      });
    }

    // 2 成长快不快
    if (num(t.rev_yoy)) {
      const ry = t.rev_yoy, ny = num(t.ni_yoy) ? t.ni_yoy : null, ey = num(t.eps_yoy) ? t.eps_yoy : null;
      const qs = (f.rows || []).filter(r => num(r.rev_yoy)).slice(-4);
      const verdict = ry >= 25 ? '高速增长' : ry >= 10 ? '稳健增长' : ry >= 0 ? '增长缓慢' : '收入下滑';
      const short = `最近 12 个月收入同比${ry >= 0 ? '增长' : '下降'} ${Math.abs(ry).toFixed(1)}%。`;
      let text = short;
      if (qs.length >= 2) {
        const a = qs[qs.length - 1].rev_yoy, b = qs[qs.length - 2].rev_yoy, d = a - b;
        text += ` 最近 ${qs.length} 个季度收入同比分别是 ${qs.map(r => pc(r.rev_yoy)).join('、')},最近一季比上一季${d >= 2 ? '增速在加快' : d <= -2 ? '增速在放缓' : '增速基本稳定'}。`;
      }
      if (ny != null && t.ni > 0) text += ny > ry + 3 ? ` 净利润同比 ${pc(ny)},快于收入增速,说明赚钱效率在提升。` : ny < ry - 3 ? ` 净利润同比 ${pc(ny)},慢于收入增速,说明成本压力在增加。` : ` 净利润同比 ${pc(ny)},和收入增速接近。`;
      const trendLine = qs.length >= 2 ? (() => { const d = qs[qs.length - 1].rev_yoy - qs[qs.length - 2].rev_yoy; return `最近 ${qs.length} 季收入同比:${qs.map(r => pc(r.rev_yoy)).join(' → ')}(最近一季${d >= 2 ? '加快' : d <= -2 ? '放缓' : '基本稳定'})` + (qs.some(r => r.est) ? ' · 部分季度含推算' : ''); })() : null;
      const cmpLine = ny != null && t.ni > 0 ? (ny > ry + 3 ? '净利润增速快于收入,赚钱效率在提升' : ny < ry - 3 ? '净利润增速慢于收入,成本压力在增加' : '净利润增速和收入接近') : null;
      items.push({
        key: 'growth', q: '成长快不快', verdict, tone: ry >= 10 ? 'ok' : ry >= 0 ? 'w' : 'bad', short, text,
        chips: [['收入同比', pc(ry), ''], ['净利润同比', ny != null ? pc(ny) : '数据不足', ''], ['每股盈利同比', ey != null ? pc(ey) : '数据不足', '']],
        lines: [trendLine, cmpLine].filter(Boolean),
        explain: '同比 = 和去年同期比;最近 12 个月 = 最近 4 个季度合计。',
        rules: ['收入同比 ≥25% 高速 · 10%–25% 稳健 · 0–10% 缓慢 · <0 下滑']
      });
    }

    // 3 财务安不安全
    {
      const fcf = num(t.fcf) ? t.fcf : null, z = H && H.zscore && !H.zscore.error && num(H.zscore.z) ? H.zscore : null, fs = H && H.fscore && H.fscore.level ? H.fscore : null;
      const net = H && Array.isArray(H.checkup) ? H.checkup.find(x => x.name === '净现金 / 净债务') : null;
      if (fcf != null || z) {
        const bad = (z && z.zone === '危险区') || (fcf != null && fcf < 0 && z && z.zone === '灰色区'), warn = (z && z.zone === '灰色区') || (fcf != null && fcf < 0);
        const verdict = bad ? '风险较高' : warn ? '需要留意' : '偏稳';
        const parts = [];
        if (fcf != null) parts.push(fcf > 0 ? `最近 12 个月自由现金流为正(${usd(fcf)}),主业自己能造血。` : `最近 12 个月自由现金流为负(${usd(fcf)}),主业在消耗现金。`);
        const short = parts[0] || `破产风险指标(Altman Z 分数)${z.z},处在${z.zone}。`;
        if (net && net.val && net.val !== '数据不足') parts.push(`${net.name}:${net.val}。`);
        if (z) parts.push(`破产风险指标(Altman Z 分数)是 ${z.z},处在${z.zone}。`);
        if (fs) parts.push(`财务质量评分(Piotroski F 分数)${fs.score}/${fs.of},评价「${fs.level}」。`);
        items.push({
          key: 'safety', q: '财务安不安全', verdict, tone: bad ? 'bad' : warn ? 'w' : 'ok', short, text: parts.join(' '),
          chips: [['自由现金流', fcf != null ? usd(fcf) : '数据不足', fcf == null ? '' : fcf > 0 ? '为正' : '为负'], ['Z 分数', z ? String(z.z) : '数据不足', z ? z.zone : '银行保险不适用'], ['F 分数', fs ? `${fs.score}/${fs.of}` : '数据不足', fs ? fs.level : '']],
          lines: net && net.val && net.val !== '数据不足' ? [`${net.name}:${net.val}`] : [],
          explain: '自由现金流 = 经营现金流 − 资本开支;为正说明主业能自己造血。',
          rules: ['Z 分数 >2.6 安全 · 1.1–2.6 灰色 · <1.1 危险;F 分数 ≥7 强', 'Z 危险,或现金流为负且灰色 → 风险较高;一项不好 → 需留意']
        });
      }
    }

    // 4 贵不贵
    {
      const eps = num(t.eps) ? t.eps : null, pe = price != null && eps != null && eps > 0 ? price / eps : null;
      const lossNow = eps != null && eps <= 0;
      const fpe = !lossNow && S && num(S.forwardPE) && S.forwardPE > 0 ? S.forwardPE : null, peg = !lossNow && S && num(S.pegRatio) && S.pegRatio > 0 ? S.pegRatio : null;      // 亏损公司的预期市盈率和 PEG 没有意义,不参与判断
      const d = H && H.dcf && !H.dcf.error && Array.isArray(H.dcf.scenarios) ? H.dcf : null, mid = d && d.scenarios.find(x => x.name === '中性'), lo = d && d.scenarios.find(x => x.name === '保守'), hi = d && d.scenarios.find(x => x.name === '乐观');
      const ratio = price != null && mid && mid.value > 0 ? price / mid.value : null;
      if (pe != null || eps != null && eps <= 0 || peg != null || ratio != null) {
        const sigs = []; if (peg != null) sigs.push(peg > 2 ? 'high' : peg < 1 ? 'low' : 'mid'); if (ratio != null) sigs.push(ratio > 1.5 ? 'high' : ratio < 0.8 ? 'low' : 'mid');
        const verdict = !sigs.length ? '数据不足' : sigs.every(x => x === 'high') ? '偏高' : sigs.every(x => x === 'low') ? '偏低' : sigs.every(x => x === 'mid') ? '中等' : '看法不一致';
        const peTxt = eps != null && eps <= 0 ? '市盈率无意义(最近 12 个月没有盈利)' : pe != null ? `市盈率 ${pe.toFixed(1)} 倍` : '';
        const short = (sigs.length ? `估值${verdict}` : '估值判断依据不足') + (peTxt ? `:${peTxt}` : '') + (peg != null ? `,PEG ${peg.toFixed(2)}` : '') + '。';
        const parts = [];
        const yEps = S && num(S.trailingEps) ? S.trailingEps : null, gap = pe != null && yEps != null && yEps > 0 && Math.abs(eps - yEps) / yEps > 0.25;
        if (pe != null) parts.push(`市盈率 ${pe.toFixed(1)} 倍:按最近 12 个月的盈利,约要 ${pe.toFixed(0)} 年才能赚回现在的股价;数字越高,说明市场对未来增长的期待越高。` + (gap ? ` 注意:SEC 财报口径的每股盈利是 ${eps.toFixed(2)},Yahoo 给的是 ${yEps.toFixed(2)},相差较大(通常是财报更新时间不同),这个市盈率只作粗略参考。` : ''));
        else if (eps != null && eps <= 0) parts.push('最近 12 个月每股盈利不是正数,市盈率没有意义,不能用它判断贵不贵。');
        if (fpe != null) parts.push(`按分析师预期的下一年盈利算,预期市盈率是 ${fpe.toFixed(1)} 倍。`);
        if (peg != null) parts.push(`PEG 是 ${peg.toFixed(2)}(市盈率 ÷ 预期盈利增速;常见经验:1 左右算合理,2 以上偏高,低于 1 偏低)。`);
        if (mid) parts.push(`按我们的简化现金流折现模型,保守 / 中性 / 乐观三种情景估算每股约 ${lo ? lo.value : '--'} / ${mid.value} / ${hi ? hi.value : '--'} 美元,现价是中性情景的 ${ratio.toFixed(1)} 倍。这个模型对假设很敏感,只作参考。`);
        if (sigs.length) parts.push(`按 PEG 和现金流折现这两个角度:${verdict === '看法不一致' ? '结论不一致,不好下结论' : '综合看估值' + verdict}。`);
        const gapLine = gap ? `每股盈利 SEC ${eps.toFixed(2)} / Yahoo ${yEps.toFixed(2)},相差较大,仅作参考` : null;
        items.push({
          key: 'value', q: '贵不贵', verdict, tone: verdict === '偏高' ? 'w' : verdict === '偏低' ? 'ok' : '', short, text: parts.join(' '),
          chips: [['市盈率', pe != null ? pe.toFixed(1) + ' 倍' : eps != null && eps <= 0 ? '无意义' : '数据不足', eps != null && eps <= 0 ? '亏损' : ''], ['PEG', peg != null ? peg.toFixed(2) : '数据不足', ''], ['现价÷折现值', ratio != null ? ratio.toFixed(1) + ' 倍' : '数据不足', mid ? '中性情景' : '']],
          lines: [fpe != null ? `预期市盈率(下一年)${fpe.toFixed(1)} 倍` : null, mid ? `折现估值每股 ${lo ? lo.value : '--'} / ${mid.value} / ${hi ? hi.value : '--'} 美元(保守/中性/乐观)` : null, gapLine].filter(Boolean),
          explain: '市盈率 = 股价 ÷ 每股盈利,约等于多少年能赚回股价;越高说明期待越高。',
          rules: ['PEG >2 偏高 · <1 偏低;现价÷折现值 >1.5 偏高 · <0.8 偏低', '两角度一致才下结论;折现为简化模型(假设见「体检」)']
        });
      }
    }
    return items.length ? { items, asof: t.end } : null;
  }

  function fundReadHTML(r) {
    if (!r) return '';
    if (r.stale) return `<h3>这家公司怎么样</h3><div class="muted small" style="line-height:1.8">这家公司在 SEC 的财报数据最新只到 ${esc(r.asof)},已经太旧,所以这里不做解读,避免用过时的数字误导你。</div>`;
    const chip = (c, k) => `<div class="fchip${k ? ' fk' : ''}"><span class="muted small">${termify(c[0])}</span><b>${esc(c[1])}</b>${c[2] ? `<span class="fsub small">${esc(c[2])}</span>` : ''}</div>`;
    const row = i => `<li><b>${esc(i.q)}</b> <span class="vtag vt-${i.tone || 'n'}">${esc(i.verdict)}</span> ${termify(i.short)}
      <details class="crw"><summary class="muted small">看依据</summary><div class="frd">
        <div class="fchips">${i.chips.map((c, k) => chip(c, k === 0)).join('')}</div>
        ${i.lines.map(l => `<div class="fline small">${termify(l)}</div>`).join('')}
        <div class="fexp muted small">${termify(i.explain)}</div>
        ${i.rules.map(x => `<div class="frule small"><span class="muted">判断线</span> ${termify(x)}</div>`).join('')}
      </div></details></li>`;
    return `<h3>这家公司怎么样 <span class="muted small">按最近财报计算,报告期 ${esc(r.asof)};只描述现状,不是预测</span></h3><ul class="frsum">${r.items.map(row).join('')}</ul>`;
  }

  const api = { fundRead, fundReadHTML, termify, TERMS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else Object.assign(root, api);
})(typeof window !== 'undefined' ? window : globalThis);
