// ===== 形态识别(参考)=====
// 纯几何规则匹配:通道、三角形、楔形、头肩顶/底、双顶/双底、茶杯、圆弧顶/底。
// 这些只是描述"价格走成了什么形状",不是预测;规则有误判和漏判,请当作参考。

// 之字转向:忽略小波动,只保留幅度 ≥ thr 的高低点(交替出现的波段高点 H 与低点 L)
function zigzag(W, thr) {
  const piv = []; let dir = 0, ext = null, hiI = 0, loI = 0;
  for (let i = 1; i < W.length; i++) {
    const b = W[i];
    if (dir === 0) {
      if (b.h > W[hiI].h) hiI = i; if (b.l < W[loI].l) loI = i;
      if (W[hiI].h / W[loI].l - 1 >= thr) {
        if (hiI > loI) { piv.push({ i: loI, p: W[loI].l, t: 'L' }); dir = 1; ext = { i: hiI, p: W[hiI].h }; }
        else { piv.push({ i: hiI, p: W[hiI].h, t: 'H' }); dir = -1; ext = { i: loI, p: W[loI].l }; }
      }
    } else if (dir === 1) {
      if (b.h > ext.p) ext = { i, p: b.h };
      else if (b.l <= ext.p * (1 - thr)) { piv.push({ i: ext.i, p: ext.p, t: 'H' }); dir = -1; ext = { i, p: b.l }; }
    } else {
      if (b.l < ext.p) ext = { i, p: b.l };
      else if (b.h >= ext.p * (1 + thr)) { piv.push({ i: ext.i, p: ext.p, t: 'L' }); dir = 1; ext = { i, p: b.h }; }
    }
  }
  if (ext) piv.push({ i: ext.i, p: ext.p, t: dir === 1 ? 'H' : 'L', tentative: true });   // 当前这一波的端点
  return piv;
}
function fitLine(pts) {   // 最小二乘直线 y = a + b·i
  const n = pts.length; let sx = 0, sy = 0, sxx = 0, sxy = 0;
  pts.forEach(p => { sx += p.i; sy += p.y; sxx += p.i * p.i; sxy += p.i * p.y; });
  const d = n * sxx - sx * sx, b = d ? (n * sxy - sx * sy) / d : 0;
  return { a: (sy - b * sx) / n, b };
}
function fitQuad(xs, ys) {   // 二次曲线 y = a·x² + b·x + c,返回拟合优度 r2
  const n = xs.length; let s1 = 0, s2 = 0, s3 = 0, s4 = 0, t0 = 0, t1 = 0, t2 = 0;
  for (let k = 0; k < n; k++) { const x = xs[k], y = ys[k], x2 = x * x; s1 += x; s2 += x2; s3 += x2 * x; s4 += x2 * x2; t0 += y; t1 += x * y; t2 += x2 * y; }
  const det = m => m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
  const A = [[s4, s3, s2], [s3, s2, s1], [s2, s1, n]], D = det(A); if (!D) return null;
  const T = [t2, t1, t0], col = c => A.map((r, i) => r.map((x, j) => j === c ? T[i] : x));
  const a = det(col(0)) / D, b = det(col(1)) / D, c = det(col(2)) / D, mean = t0 / n; let ssr = 0, sst = 0;
  for (let k = 0; k < n; k++) { const f = a * xs[k] * xs[k] + b * xs[k] + c; ssr += (ys[k] - f) ** 2; sst += (ys[k] - mean) ** 2; }
  return { a, b, c, r2: sst ? 1 - ssr / sst : 0 };
}

// 返回最多 3 个得分最高的形态;所有下标都相对于传入的 W
function detectPatterns(W, intra) {
  const nW = W.length; if (nW < 60) return [];
  const avgR = W.reduce((s, b) => s + (b.h - b.l) / b.c, 0) / nW, thr = Math.min(.2, Math.max(intra ? .006 : .035, avgR * 3.5));
  const Z = zigzag(W, thr), m = Z.length, out = [], last = W[nW - 1].c;
  const Zf = zigzag(W, Math.min(.12, Math.max(intra ? .004 : .02, avgR * 2)));   // 更灵敏的转折点,用于通道 / 三角形 / 楔形
  const recent = (endI, span) => nW - 1 - endI <= Math.max(15, span * .5);

  // ---- 头肩顶 / 头肩底 ----
  for (let k = Math.max(0, m - 10); k + 4 < m; k++) for (const top of [true, false]) {
    const p = Z.slice(k, k + 5); if (p.map(q => q.t).join('') !== (top ? 'HLHLH' : 'LHLHL')) continue;
    const [ls, n1, h, n2, rs] = p, a = h.i - ls.i, b = rs.i - h.i; if (a < 5 || b < 5) continue;
    const ratio = a / b; if (ratio < .45 || ratio > 2.2) continue;
    const sh = Math.abs(ls.p - rs.p) / Math.min(ls.p, rs.p); if (sh > .09) continue;
    if (Math.abs(n1.p - n2.p) / Math.min(n1.p, n2.p) > .07) continue;
    const nk = (n1.p + n2.p) / 2, prom = top ? (h.p - nk) / h.p : (nk - h.p) / nk; if (prom < .05) continue;
    if (top ? h.p < Math.max(ls.p, rs.p) * 1.025 : h.p > Math.min(ls.p, rs.p) * .975) continue;
    if (!recent(rs.i, rs.i - ls.i)) continue;
    const neck = i => n1.p + (n2.p - n1.p) * (i - n1.i) / (n2.i - n1.i || 1), broken = top ? last < neck(nW - 1) * .99 : last > neck(nW - 1) * 1.01;
    out.push({ type: top ? 'hs-top' : 'hs-bottom', name: top ? '头肩顶' : '头肩底', bias: top ? 'bear' : 'bull', status: broken ? '已突破颈线' : '形成中',
      score: 2 + (1 - Math.min(1, Math.abs(Math.log(ratio)))) + (1 - Math.min(1, sh / .09)) + prom * 4 + (broken ? 1 : 0), pts: p, neck: { i1: n1.i, p1: n1.p, i2: n2.i, p2: n2.p } });
  }
  // ---- 双顶 / 双底 ----
  for (let k = Math.max(0, m - 7); k + 2 < m; k++) for (const top of [true, false]) {
    const p = Z.slice(k, k + 3); if (p.map(q => q.t).join('') !== (top ? 'HLH' : 'LHL')) continue;
    const [a, v, b] = p, d = Math.abs(a.p - b.p) / Math.min(a.p, b.p), dep = top ? (Math.min(a.p, b.p) - v.p) / Math.min(a.p, b.p) : (v.p - Math.max(a.p, b.p)) / v.p;
    if (d > .035 || dep < .07 || b.i - a.i < 14 || !recent(b.i, b.i - a.i)) continue;
    const broken = top ? last < v.p * .99 : last > v.p * 1.01;
    out.push({ type: top ? 'dbl-top' : 'dbl-bottom', name: top ? '双顶' : '双底', bias: top ? 'bear' : 'bull', status: broken ? '已突破颈线' : '形成中',
      score: 2 + (1 - d / .035) + dep * 5 + (broken ? 1 : 0), pts: p, neckP: v.p });
  }
  // ---- 通道 / 三角形 / 楔形:用波段高点拟合上沿、波段低点拟合下沿 ----
  let best = null;
  for (const w of [50, 80, 120, 170, 230].filter(w => w <= nW)) {
    const s = nW - w, pv = Zf.filter(q => q.i >= s), hi = pv.filter(q => q.t === 'H'), lo = pv.filter(q => q.t === 'L'); if (hi.length < 2 || lo.length < 2 || hi.length + lo.length < 5) continue;
    const u = fitLine(hi.map(q => ({ i: q.i, y: Math.log(q.p) }))), l = fitLine(lo.map(q => ({ i: q.i, y: Math.log(q.p) })));
    const s0 = Math.min(hi[0].i, lo[0].i), e = nW - 1, span = e - s0; if (span < 25) continue;
    const U = i => u.a + u.b * i, L = i => l.a + l.b * i; let inside = 0;
    for (let i = s0; i <= e; i++) { const c = Math.log(W[i].c); if (c <= U(i) + .012 && c >= L(i) - .012) inside++; }
    const frac = inside / (span + 1); if (frac < .9) continue;
    const w0 = U(s0) - L(s0), w1 = U(e) - L(e); if (w0 < .04 || w1 <= 0) continue;
    const r = w1 / w0, ut = u.b * span, lt = l.b * span, av = (ut + lt) / 2; let name = null, bias = 'neutral';
    const parallel = Math.abs(ut - lt) <= Math.max(.05, .45 * Math.abs(av));   // 上下沿大致平行
    if (parallel && r >= .5 && r <= 1.5) {
      if (ut > .02 && lt > .02 && av > .06) { name = '上升通道'; bias = 'bull'; }
      else if (ut < -.02 && lt < -.02 && av < -.06) { name = '下降通道'; bias = 'bear'; }
      else if (Math.abs(ut) < .04 && Math.abs(lt) < .04 && w0 < .35) name = '矩形整理';
    } else if (r < .66 && r > .03) {
      if (Math.abs(ut) < .03 && lt > .05) { name = '上升三角形'; bias = 'bull'; }
      else if (Math.abs(lt) < .03 && ut < -.05) { name = '下降三角形'; bias = 'bear'; }
      else if (ut < -.03 && lt > .03) name = '对称三角形';
      else if (ut > .02 && lt > .02 && lt > ut * 1.3 && r < .55) { name = '上升楔形'; bias = 'bear'; }
      else if (ut < -.02 && lt < -.02 && ut < lt * 1.3 && r < .55) { name = '下降楔形'; bias = 'bull'; }
    }
    if (!name) continue;
    const score = 2 + hi.length + lo.length + frac * 3 + span / 100;
    if (!best || score > best.score) best = { type: 'conv', name, bias, status: '形成中', score, touches: hi.length + lo.length, s0, e, u, l, w1, apex: u.b - l.b < 0 ? e + w1 / (l.b - u.b) : Infinity };
  }
  if (best) out.push(best);
  // ---- 茶杯(带柄) ----
  const Hs = Z.filter(q => q.t === 'H'); let cup = null;
  for (let x = 0; x < Hs.length; x++) for (let y = x + 1; y < Hs.length; y++) {
    const p1 = Hs[x], p3 = Hs[y], dur = p3.i - p1.i; if (dur < 30) continue;
    let pre = 0; for (let i = Math.max(0, p1.i - Math.round(dur * .6)); i < p1.i; i++) pre = Math.max(pre, W[i].h); if (p1.i > 10 && pre > p1.p * 1.01) continue;   // 左沿之前不能有更高的点(否则是 W 形的右半边)
    const rim = (p1.p + p3.p) / 2; if (Math.abs(p1.p - p3.p) / rim > .07) continue;
    let low = null; for (const q of Z) if (q.t === 'L' && q.i > p1.i && q.i < p3.i && (!low || q.p < low.p)) low = q; if (!low) continue;
    if (Z.some(q => q.t === 'L' && q.i < p1.i && p1.i - q.i < dur * 1.3 && Math.abs(q.p - low.p) / low.p < .06)) continue;   // 前面已有同样的低点 → W 形(双底),不是茶杯
    const depth = (rim - low.p) / rim, xpos = (low.i - p1.i) / dur; if (depth < .1 || depth > .5 || xpos < .3 || xpos > .7) continue;
    let mx = 0; for (let i = p1.i; i <= p3.i; i++) mx = Math.max(mx, W[i].h); if (mx > Math.max(p1.p, p3.p) * 1.03) continue;
    if (Z.some(q => q.t === 'H' && q.i > p1.i && q.i < p3.i && (q.p - low.p) / (rim - low.p) > .5)) continue;   // 杯中有明显反弹峰 → W 形
    if (nW - 1 - p3.i > dur * .45) continue;
    const xs = [], ys = []; for (let i = p1.i; i <= p3.i; i++) { xs.push((i - p1.i) / dur); ys.push(Math.log(W[i].c)); }
    const q = fitQuad(xs, ys); if (!q || q.a <= 0 || q.r2 < .65) continue;
    let l2 = null; for (let i = p3.i + 1; i < nW; i++) if (l2 === null || W[i].l < W[l2].l) l2 = i;
    const hd = l2 !== null ? (p3.p - W[l2].l) / p3.p : 0, handle = l2 !== null && hd >= .025 && hd <= .16 && last > W[l2].l;
    const score = 2 + q.r2 * 3 + (1 - Math.abs(p1.p - p3.p) / rim / .07) + depth * 3 + (handle ? 1 : 0);
    if (!cup || score > cup.score) cup = { type: 'cup', name: handle ? '茶杯带柄' : '茶杯(圆弧底)', bias: 'bull', status: last >= rim * .995 ? '接近/突破沿口' : '整理中', score, p1, p3, low, quad: q, dur, l2: handle ? { i: l2, p: W[l2].l } : null };
  }
  if (cup) out.push(cup);
  // ---- 圆弧顶(U 倒过来,上涨动能衰竭)/ 圆弧底 ----
  for (const w of [40, 60, 90, 130, 180].filter(w => w <= nW)) {
    const s = nW - w, xs = [], ys = []; for (let i = s; i < nW; i++) { xs.push((i - s) / (w - 1)); ys.push(Math.log(W[i].c)); }
    const q = fitQuad(xs, ys); if (!q || q.r2 < .85 || q.a === 0) continue;
    const ax = -q.b / (2 * q.a); if (ax < .3 || ax > .85) continue;
    const f = x => q.a * x * x + q.b * x + q.c, ap = f(ax), s0 = f(0), e0 = f(1);
    if (q.a < 0) {
      if (ap - s0 < .08 || ap - e0 < .05 || last > Math.exp(ap) * .985) continue;
      const score = 2 + q.r2 * 3 + (ap - e0) * 5, prev = out.find(o => o.type === 'round-top');
      if (!prev || score > prev.score) { if (prev) out.splice(out.indexOf(prev), 1); out.push({ type: 'round-top', name: '圆弧顶', bias: 'bear', status: '动能转弱', score, s: s, w, quad: q, ax }); }
    } else if (!cup) {
      if (s0 - ap < .08 || e0 - ap < .06) continue;
      const score = 2 + q.r2 * 3 + (e0 - ap) * 5, prev = out.find(o => o.type === 'round-bottom');
      if (!prev || score > prev.score) { if (prev) out.splice(out.indexOf(prev), 1); out.push({ type: 'round-bottom', name: '圆弧底', bias: 'bull', status: '企稳回升', score, s: s, w, quad: q, ax }); }
    }
  }
  // 同一段走势只保留最有代表性的形态:头肩 > 茶杯 > 双顶/底 > 通道、三角 > 圆弧
  detectPatterns.dbg = { Z, Zf, out: out.slice() };
  const prio = { 'hs-top': 5, 'hs-bottom': 5, cup: 4, 'dbl-top': 3, 'dbl-bottom': 3, conv: 2, 'round-top': 1, 'round-bottom': 1 };
  const spanOf = P => P.type.startsWith('hs') ? [P.pts[0].i, P.pts[4].i] : P.type.startsWith('dbl') ? [P.pts[0].i, P.pts[2].i] : P.type === 'conv' ? [P.s0, P.e] : P.type === 'cup' ? [P.p1.i, nW - 1] : [P.s, nW - 1];
  const picked = [];
  const pr = P => (prio[P.type] || 0) + (P.type === 'conv' && P.touches >= 6 ? 1.8 : 0);   // 触碰点多的通道 / 三角形优先于双顶
  for (const P of out.sort((x, y) => pr(y) - pr(x) || y.score - x.score)) {
    const [a, b] = spanOf(P);
    if (picked.some(q => { const [c, d] = spanOf(q), ov = Math.min(b, d) - Math.max(a, c); return ov > .3 * Math.min(b - a, d - c); })) continue;
    picked.push(P);
  }
  return picked.slice(0, 3);
}

// ===== 绘制 =====
function drawPatterns(ctx, env) {
  const { X, Y, top, bot, W, PL, PR, off, ext, list, up, down, accent } = env, nLast = env.last;
  const col = b => b === 'bull' ? up : b === 'bear' ? down : accent, biasTxt = { bull: '偏多', bear: '偏空', neutral: '中性' };
  const px = i => X(i + off), labels = [];
  const seg = (i1, p1, i2, p2) => { ctx.beginPath(); ctx.moveTo(px(i1), Y(p1)); ctx.lineTo(px(i2), Y(p2)); ctx.stroke(); };
  const dot = (i, p, r = 3) => { ctx.beginPath(); ctx.arc(px(i), Y(p), r, 0, 7); ctx.fill(); };
  const text = (t, x, y, c, size = 11) => { ctx.font = `${size}px -apple-system,"PingFang SC",sans-serif`; ctx.fillStyle = c; ctx.textAlign = 'center'; ctx.fillText(t, x, y); };
  list.forEach(P => {
    const c = col(P.bias); ctx.save(); ctx.strokeStyle = c; ctx.fillStyle = c; ctx.lineWidth = 1.5; ctx.globalAlpha = .9; ctx.setLineDash([]);
    let lx = 0, ly = 0;   // 标签位置
    if (P.type === 'hs-top' || P.type === 'hs-bottom') {
      const topP = P.type === 'hs-top', pts = P.pts;
      ctx.globalAlpha = .6; ctx.beginPath(); pts.forEach((q, k) => k ? ctx.lineTo(px(q.i), Y(q.p)) : ctx.moveTo(px(q.i), Y(q.p))); ctx.stroke(); ctx.globalAlpha = .95;
      pts.forEach(q => dot(q.i, q.p)); ['左肩', '', '头', '', '右肩'].forEach((t, k) => t && text(t, px(pts[k].i), Y(pts[k].p) + (topP ? -9 : 15), c));
      const n = P.neck, np = i => n.p1 + (n.p2 - n.p1) * (i - n.i1) / (n.i2 - n.i1 || 1), end = off + 0, ei = nLast + ext - off;
      ctx.setLineDash([6, 4]); seg(n.i1, n.p1, ei, np(ei)); lx = px(pts[2].i); ly = Y(pts[2].p) + (topP ? -26 : 30);
    } else if (P.type === 'dbl-top' || P.type === 'dbl-bottom') {
      const topP = P.type === 'dbl-top', pts = P.pts;
      ctx.globalAlpha = .6; ctx.beginPath(); pts.forEach((q, k) => k ? ctx.lineTo(px(q.i), Y(q.p)) : ctx.moveTo(px(q.i), Y(q.p))); ctx.stroke(); ctx.globalAlpha = .95;
      pts.forEach(q => dot(q.i, q.p)); ctx.setLineDash([6, 4]); seg(pts[0].i, P.neckP, nLast + ext - off, P.neckP);
      lx = px(pts[2].i); ly = Y(pts[2].p) + (topP ? -14 : 18);
    } else if (P.type === 'conv') {
      const U = i => Math.exp(P.u.a + P.u.b * i), L = i => Math.exp(P.l.a + P.l.b * i), e2 = Math.min(P.e + ext, isFinite(P.apex) ? P.apex : 1e9);
      ctx.globalAlpha = .07; ctx.beginPath(); ctx.moveTo(px(P.s0), Y(U(P.s0))); ctx.lineTo(px(e2), Y(U(e2))); ctx.lineTo(px(e2), Y(L(e2))); ctx.lineTo(px(P.s0), Y(L(P.s0))); ctx.closePath(); ctx.fill();
      ctx.globalAlpha = .9; seg(P.s0, U(P.s0), e2, U(e2)); seg(P.s0, L(P.s0), e2, L(e2));
      lx = px(Math.min(P.e, P.s0 + (P.e - P.s0) * .5)); ly = Y(U(P.s0 + (P.e - P.s0) * .5)) - 12;
    } else if (P.type === 'cup') {
      const q = P.quad, f = x => Math.exp(q.a * x * x + q.b * x + q.c);
      ctx.beginPath(); for (let k = 0; k <= 40; k++) { const x = k / 40, i = P.p1.i + x * P.dur; k ? ctx.lineTo(px(i), Y(f(x))) : ctx.moveTo(px(i), Y(f(x))); } ctx.stroke();
      ctx.setLineDash([5, 4]); ctx.globalAlpha = .6; seg(P.p1.i, P.p1.p, P.p3.i, P.p3.p); ctx.globalAlpha = .95; ctx.setLineDash([]);
      dot(P.p1.i, P.p1.p); dot(P.p3.i, P.p3.p); if (P.l2) { dot(P.l2.i, P.l2.p, 3.5); text('柄', px(P.l2.i), Y(P.l2.p) + 15, c); }
      lx = px(P.p1.i + P.dur / 2); ly = Y(P.low.p) + 28;
    } else if (P.type === 'round-top' || P.type === 'round-bottom') {
      const q = P.quad, f = x => Math.exp(q.a * x * x + q.b * x + q.c);
      ctx.beginPath(); for (let k = 0; k <= 40; k++) { const x = k / 40, i = P.s + x * (P.w - 1); k ? ctx.lineTo(px(i), Y(f(x))) : ctx.moveTo(px(i), Y(f(x))); } ctx.stroke();
      const ai = P.s + P.ax * (P.w - 1); dot(ai, f(P.ax)); lx = px(ai); ly = Y(f(P.ax)) + (P.type === 'round-top' ? -14 : 20);
    }
    ctx.restore();
    // 标签:半透明深色底,避免和 K 线混在一起
    const t = `${P.name} · ${biasTxt[P.bias]} · ${P.status}`; ctx.font = '12px -apple-system,"PingFang SC",sans-serif';
    const w = ctx.measureText(t).width + 14; let x = Math.max(PL + w / 2 + 4, Math.min(W - PR - w / 2 - 4, lx)), y = Math.max(top + 14, Math.min(bot - 10, ly));
    for (let tries = 0; tries < 6 && labels.some(r => Math.abs(r.y - y) < 18 && Math.abs(r.x - x) < (r.w + w) / 2); tries++) y += 20;
    labels.push({ x, y, w }); ctx.save(); ctx.fillStyle = 'rgba(0,0,0,.72)'; ctx.fillRect(x - w / 2, y - 10, w, 20); ctx.strokeStyle = c; ctx.globalAlpha = .6; ctx.lineWidth = 1; ctx.strokeRect(x - w / 2 + .5, y - 9.5, w - 1, 19); ctx.restore();
    text(t, x, y + 1, c, 12);
  });
}
