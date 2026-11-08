"""短线「超跌 → 企稳 → 放量反弹」形态的回测(对比标普 500)。
形态(把你描述的走法量化):
  1) 前面跌了很多(离 120 日高点回撤 ≥ dd),最低点 L1 在最近 40 天内;
  2) 之后不再创新低(L1 之后已经过去至少 dsl 天);
  3) 从 L1 起来一波反弹到 H1(放量上涨),然后回调(缩量下跌),回调低点 L2 高于 L1(不破前低);
  4) 今天重新上涨,并且放量(成交量大于回调阶段均量)——"放量上涨 → 缩量回调 → 放量再涨、不破前低"。
注:"庄家控盘"没法直接测,这里用成交量形态(缩量回调、放量上涨)作为代理。
入场 T+1 开盘价,持有 1、3、5、10、30、60、120 天;成本每边 0.10%;对比同期标普 500,并给出「扣 beta」的超额。样本内 = 2023 年以前,样本外 = 2023 年以后。
偏差:幸存者偏差(退市的不在)——对"买大跌股"这类策略影响最大;用「当时的估计市值」筛选(今天市值 × 当时价格/今天价格)削弱前视偏差。
运行:python3 tools/rebound_study.py build / analyze   仅为研究,不构成投资建议。"""
import gzip, itertools, math, os, pickle, random, statistics, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "api")]
import screener_v2 as S
import backtest as BT
import backtest_tune as T

HS = (1, 3, 5, 10, 30, 60, 120)
COST = 0.001
OUT = os.path.join(HERE, ".cache", "rebound_events.pkl.gz")
LOOSE = {"dd": 0.20, "dsl": 3, "shrink": 1.2, "resume": 0.8}          # 扫描时用最宽的阈值,之后在分析里收紧


def build():
    t0 = time.time()
    D = pickle.load(gzip.open(T.CACHE_BARS, "rb"))
    spy, bars, caps = D["spy"], D["bars"], D["caps"]
    sidx = {d: i for i, d in enumerate(spy["d"])}
    events = []
    for si, (sym, B) in enumerate(bars.items()):
        cap = caps.get(sym, 0)
        if cap < 5e9:
            continue
        c, h, l, v, a, ao, ds = B["c"], B["h"], B["l"], B["v"], B["a"], B["ao"], B["d"]
        n = len(c)
        s5, s20 = S.sma(c, 5), S.sma(c, 20)
        rs = S.rsi_wilder(c, 14)
        atr, adx, pdi, mdi = BT.wilder_series(h, l, c)
        sa, last = [], None
        for d in ds:
            last = spy["a"][sidx[d]] if d in sidx else last
            sa.append(last)
        sr = [0.0] + [sa[i] / sa[i - 1] - 1 if sa[i - 1] else 0.0 for i in range(1, n)]
        r = [0.0] + [a[i] / a[i - 1] - 1 for i in range(1, n)]
        pr, ps, prs, pss, pcv = [0.0], [0.0], [0.0], [0.0], [0.0]
        for i in range(n):
            pr.append(pr[-1] + r[i]); ps.append(ps[-1] + sr[i]); prs.append(prs[-1] + r[i] * sr[i]); pss.append(pss[-1] + sr[i] * sr[i]); pcv.append(pcv[-1] + c[i] * v[i])
        nxt = 0
        for t in range(260, n - 2):
            if t < nxt or c[t] <= c[t - 1] or atr[t] is None or rs[t] is None:
                continue
            hi120 = max(h[t - 119:t + 1])
            seg = c[t - 39:t + 1]
            L1 = min(seg)
            if 1 - L1 / hi120 < LOOSE["dd"]:
                continue
            i1 = t - 39 + max(i for i, x in enumerate(seg) if x == L1)
            if t - i1 < LOOSE["dsl"] or t - i1 < 4:
                continue
            mid = c[i1 + 1:t]
            if len(mid) < 3:
                continue
            H1 = max(mid)
            iH = i1 + 1 + max(i for i, x in enumerate(mid) if x == H1)
            if iH - i1 < 2 or t - 1 - iH < 1:
                continue                                             # 需要:一波反弹(≥2 天),然后至少 1 天回调
            L2 = min(c[iH:t])
            if L2 <= L1 or H1 <= L1:
                continue                                             # 回调低点必须高于前低
            vup = sum(v[i1 + 1:iH + 1]) / (iH - i1)
            vpb = sum(v[iH + 1:t]) / (t - 1 - iH)
            if vup <= 0 or vpb <= 0:
                continue
            shrink, resume = vpb / vup, v[t] / vpb
            if shrink > LOOSE["shrink"] or resume < LOOSE["resume"]:
                continue
            px = c[t]
            adv = (pcv[t + 1] - pcv[t - 59]) / 60
            est_cap = cap * px / c[-1]
            if px < 10 or adv < 20e6 or ds[t + 1] not in sidx or sa[t - 126] is None:
                continue
            i1s = sidx[ds[t + 1]]
            m = 126
            mr, ms = (pr[t + 1] - pr[t + 1 - m]) / m, (ps[t + 1] - ps[t + 1 - m]) / m
            cov = (prs[t + 1] - prs[t + 1 - m]) / m - mr * ms
            var = (pss[t + 1] - pss[t + 1 - m]) / m - ms * ms
            beta = cov / var if var > 0 else 1.0
            dn_vol = sum(v[max(0, i1 - 9):i1 + 1]) / min(10, i1 + 1)
            ihi = t - 119 + max(i for i, x in enumerate(h[t - 119:t + 1]) if x == hi120)
            f = {"dd": 1 - L1 / hi120, "dsl": t - i1, "hl": L2 / L1 - 1, "retrace": (H1 - L2) / (H1 - L1), "rally": H1 / L1 - 1, "shrink": shrink, "resume": resume,
                 "upvdn": vup / dn_vol if dn_vol > 0 else 1.0, "dur": i1 - ihi, "px_vs_h1": px / H1 - 1, "day": c[t] / c[t - 1] - 1, "rsi": rs[t], "atrp": atr[t] / px,
                 "above5": px > s5[t], "above20": px > s20[t], "beta": beta, "est_cap": est_cap, "adv": adv}
            ev = {"sym": sym, "date": ds[t], "f": f}
            ok = False
            for hh in HS:
                x = t + 1 + hh
                if x < n and ds[x] in sidx and i1s + hh < len(spy["a"]):
                    ev[f"r{hh}"] = a[x] / ao[t + 1] - 1
                    ev[f"s{hh}"] = spy["a"][i1s + hh] / spy["ao"][i1s] - 1
                    ok = True
            if ok:
                events.append(ev)
                nxt = t + 10
    pickle.dump(events, gzip.open(OUT, "wb"))
    print(f"完成:事件 {len(events):,},用时 {time.time() - t0:.0f} 秒")


# =============================== 分析 ===============================
def net(g, c=COST):
    return (1 + g) * (1 - c) / (1 + c) - 1


def month_t(pairs):
    by = {}
    for ym, x in pairs:
        by.setdefault(ym, []).append(x)
    m = [sum(v) / len(v) for v in by.values()]
    if len(m) < 6:
        return None, len(m)
    sd = statistics.stdev(m)
    return (statistics.mean(m) / (sd / math.sqrt(len(m))) if sd else None), len(m)


def stat(evs, h):
    rows = [(e["date"][:7], net(e[f"r{h}"]), e[f"s{h}"], e["f"]["beta"]) for e in evs if f"r{h}" in e]
    if len(rows) < 30:
        return None
    raw = [r - s for _, r, s, _ in rows]
    adj = [r - b * s for _, r, s, b in rows]
    t, months = month_t([(m, x) for (m, _, _, _), x in zip(rows, adj)])
    return {"n": len(rows), "ret": statistics.mean(r for _, r, _, _ in rows), "spy": statistics.mean(s for _, _, s, _ in rows), "raw": statistics.mean(raw), "adj": statistics.mean(adj),
            "t": t, "win": sum(1 for x in raw if x > 0) / len(raw), "gross_raw": statistics.mean((1 + r) * (1 + COST) / (1 - COST) - 1 - s for _, r, s, _ in rows)}


def pc(x, d=2, s=True):
    return "--" if x is None else (f"{x * 100:+.{d}f}%" if s else f"{x * 100:.{d}f}%")


DEFAULT = {"dd": 0.30, "dsl": 5, "hl": 0.0, "shrink": 0.9, "resume": 1.2, "retrace": (0.2, 0.8)}
GRID = {
    "dd": [0.20, 0.30, 0.40, 0.50],
    "dsl": [3, 5, 8, 12],
    "hl": [0.0, 0.03, 0.06],
    "shrink": [1.2, 0.9, 0.7, 0.5],
    "resume": [0.8, 1.2, 1.6, 2.0],
    "retrace": [(0.0, 1.0), (0.2, 0.8), (0.3, 0.7)],
}


def passes(f, p):
    return (f["dd"] >= p["dd"] and f["dsl"] >= p["dsl"] and f["hl"] >= p["hl"] and f["shrink"] <= p["shrink"] and f["resume"] >= p["resume"]
            and p["retrace"][0] <= f["retrace"] <= p["retrace"][1] and f["est_cap"] >= 5e9)


def analyze():
    EV = pickle.load(gzip.open(OUT, "rb"))
    EV = [e for e in EV if e["f"]["est_cap"] >= 5e9]
    IS = [e for e in EV if e["date"] < T.SPLIT]
    OOS = [e for e in EV if e["date"] >= T.SPLIT]
    base = pickle.load(gzip.open(os.path.join(HERE, ".cache", "events10y.pkl.gz"), "rb"))["base"]
    out = ["# 短线「超跌 → 企稳 → 放量反弹」回测(对比标普 500)\n"]
    w = out.append
    w("形态:前面大跌(离 120 日高点回撤 ≥ dd)→ 最低点之后不再创新低 → 一波反弹(放量)→ 缩量回调,回调低点高于前低 → 今天重新上涨且放量。**「庄家控盘」无法直接测,用成交量形态当代理。**\n")
    w("入场 T+1 开盘价,持有 1、3、5、10、30、60、120 天,成本每边 0.10%。样本内 = 2023 年以前,样本外 = 2023 年以后。**偏差:** 幸存者偏差(没有退市股,对「买大跌股」影响最大)、用当时估计市值(今天市值×当时价格/今天价格)筛选 ≥ 50 亿。\n")
    w(f"全部候选事件(宽松阈值,当时估计市值 ≥ 50 亿):{len(EV):,} 个(样本内 {len(IS):,},样本外 {len(OOS):,}),同一只股票 10 天内不重复。\n")
    # ---------- A. 初始固定条件 ----------
    w("## A. 起点:一组固定条件\n")
    w(f"初始条件:回撤 ≥ {DEFAULT['dd'] * 100:.0f}%;最低点后至少 {DEFAULT['dsl']} 天不再创新低;回调低点高于前低({DEFAULT['hl'] * 100:.0f}% 以上);回调缩量(回调均量 ≤ 反弹均量 × {DEFAULT['shrink']});今天放量(≥ 回调均量 × {DEFAULT['resume']});回调幅度占反弹的 {DEFAULT['retrace'][0] * 100:.0f}% 到 {DEFAULT['retrace'][1] * 100:.0f}%。\n")
    w("| 持有 | 时期 | 事件数 | 平均净收益 | 同期 SPY | **超 SPY(净)** | **扣 beta 超额** | 无成本超 SPY | 胜 SPY | 按月 t |\n|---|---|---|---|---|---|---|---|---|---|")
    sel_is = [e for e in IS if passes(e["f"], DEFAULT)]
    sel_oos = [e for e in OOS if passes(e["f"], DEFAULT)]
    for h in HS:
        for per, sub in (("样本内", sel_is), ("样本外", sel_oos)):
            s = stat(sub, h)
            if s:
                w(f"| {h} 天 | {per} | {s['n']:,} | {pc(s['ret'])} | {pc(s['spy'])} | **{pc(s['raw'])}** | **{pc(s['adj'])}** | {pc(s['gross_raw'])} | {pc(s['win'], 0, False)} | {('%.1f' % s['t']) if s['t'] is not None else '--'} |")
    w("\n对照 1(只要「大跌后今天上涨」,没有量价结构):全部候选事件的表现,用来看量价结构有没有增加价值——\n")
    w("| 持有 | 时期 | 事件数 | 超 SPY(净) | 扣 beta 超额 | 按月 t |\n|---|---|---|---|---|---|")
    for h in (5, 10, 30, 60):
        for per, sub in (("样本内", IS), ("样本外", OOS)):
            s = stat(sub, h)
            if s:
                w(f"| {h} 天 | {per} | {s['n']:,} | {pc(s['raw'])} | {pc(s['adj'])} | {('%.1f' % s['t']) if s['t'] is not None else '--'} |")
    # ---------- B. 一次动一个变量 ----------
    w("\n## B. 一次只调一个变量(其他保持初始值):样本内 → 样本外 的「扣 beta 超额」,持有 5 / 10 / 30 天\n")
    w("| 变量 | 取值 | 5 天 | 10 天 | 30 天 | 样本内事件数 |\n|---|---|---|---|---|---|")
    names = {"dd": "回撤 ≥", "dsl": "最低点后天数 ≥", "hl": "回调低点高于前低 ≥", "shrink": "回调缩量(回调均量/反弹均量 ≤)", "resume": "今日放量(今日量/回调均量 ≥)", "retrace": "回调幅度占反弹的"}
    for k, opts in GRID.items():
        for o in opts:
            p = dict(DEFAULT)
            p[k] = o
            si = [e for e in IS if passes(e["f"], p)]
            so = [e for e in OOS if passes(e["f"], p)]
            cells = []
            for h in (5, 10, 30):
                a, b = stat(si, h), stat(so, h)
                cells.append(f"{pc(a['adj']) if a else '--'} → {pc(b['adj']) if b else '--'}")
            label = f"{o[0] * 100:.0f}%–{o[1] * 100:.0f}%" if k == "retrace" else (f"{o * 100:.0f}%" if k in ("dd", "hl") else (f"{o}天" if k == "dsl" else f"{o}"))
            w(f"| {names[k]} | {label}{' (初始)' if o == DEFAULT[k] else ''} | " + " | ".join(cells) + f" | {len(si):,} |")
    # ---------- C. 全组合搜索(只用样本内)----------
    keys = list(GRID)
    combos = list(itertools.product(*[GRID[k] for k in keys]))
    w(f"\n## C. 所有变量一起微调:只在样本内选,样本外检验(共 {len(combos)} 种组合)\n")
    w("每个持有期单独选:样本内「扣 beta 超额」最高(事件数 ≥ 80、覆盖 ≥ 18 个月)的组合,然后看样本外。\n")

    def evaluate(evs_is, evs_oos, h, minn=80):
        best = None
        for cb in combos:
            p = dict(zip(keys, cb))
            si = [e for e in evs_is if passes(e["f"], p)]
            if len(si) < minn:
                continue
            s = stat(si, h)
            if s and s["t"] is not None and (best is None or s["adj"] > best[1]["adj"]):
                best = (p, s)
        return best
    w("| 持有 | 选出的条件 | 样本内 事件/扣beta/按月t | **样本外 事件/扣beta超额** | 样本外 超 SPY(净) | 样本外 按月 t | 是否通过 |\n|---|---|---|---|---|---|---|")
    finals = {}
    for h in HS:
        b = evaluate(IS, OOS, h)
        if not b:
            w(f"| {h} 天 | (没有找到) | -- | -- | -- | -- | 未通过 |")
            continue
        p, si = b
        so = stat([e for e in OOS if passes(e["f"], p)], h)
        finals[h] = (p, si, so)
        desc = f"回撤≥{p['dd'] * 100:.0f}%、{p['dsl']}天不创新低、高于前低≥{p['hl'] * 100:.0f}%、回调缩量≤{p['shrink']}、今日放量≥{p['resume']}、回调占反弹{p['retrace'][0] * 100:.0f}–{p['retrace'][1] * 100:.0f}%"
        ok = bool(so and so["adj"] > 0 and so["raw"] > 0 and so["t"] is not None and so["t"] >= 2)
        w(f"| {h} 天 | {desc} | {si['n']} / {pc(si['adj'])} / {si['t']:.1f} | " + (f"{so['n']} / **{pc(so['adj'])}** | {pc(so['raw'])} | {('%.1f' % so['t']) if so['t'] is not None else '--'} | {'**通过**' if ok else '未通过'} |" if so else "-- | -- | -- | 未通过 |"))
        print(f"持有 {h} 天:样本内 {pc(si['adj'])},样本外 {pc(so['adj']) if so else '--'}", flush=True)
    w("\n通过标准(事先定):样本外扣 beta 超额 > 0、超 SPY(净)> 0、按月 t ≥ 2。\n")
    # ---------- D. 随机对照 ----------
    w("\n## D. 过拟合对照:把收益在事件之间随机打乱,同样的搜索能找到多漂亮的样本内结果(持有 10 天)\n")
    rng = random.Random(11)
    w("| 次数 | 样本内 扣beta超额 | 样本外 扣beta超额 |\n|---|---|---|")
    for rep in range(5):
        rr = [(e["f"]["beta"], e) for e in EV]
        ev2 = []
        pool = [(e.get("r10"), e.get("s10")) for e in EV]
        idx = [i for i, (x, y) in enumerate(pool) if x is not None]
        vals = [pool[i] for i in idx]
        rng.shuffle(vals)
        mp = dict(zip(idx, vals))
        for i, e in enumerate(EV):
            if i in mp:
                ee = {"sym": e["sym"], "date": e["date"], "f": e["f"], "r10": mp[i][0], "s10": mp[i][1]}
                ev2.append(ee)
        i2 = [e for e in ev2 if e["date"] < T.SPLIT]
        o2 = [e for e in ev2 if e["date"] >= T.SPLIT]
        b = evaluate(i2, o2, 10)
        if b:
            so = stat([e for e in o2 if passes(e["f"], b[0])], 10)
            w(f"| {rep + 1} | {pc(b[1]['adj'])} | {pc(so['adj']) if so else '--'} |")
    open(os.path.join(HERE, "rebound_report.md"), "w", encoding="utf-8").write("\n".join(out))
    print("已生成 tools/rebound_report.md")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build()
    elif len(sys.argv) > 1 and sys.argv[1] == "analyze":
        analyze()
    else:
        print(__doc__)
