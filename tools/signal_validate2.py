"""进一步去偏差的检验:
 (1) 用「当时的估计市值」代替「今天的市值」筛选(估计市值 = 今天市值 × 当时股价 / 今天股价,假设股本不变)——去掉「今天才成为大公司的小公司」这个前视偏差。
 (2) 把组合和「同 beta 的杠杆标普」对比:如果组合 beta 是 1.8,那就拿 1.8 倍标普(每天再平衡、不计融资成本)做对照。
运行:python3 tools/signal_validate2.py → tools/signal_validation2.md     仅为研究,不构成投资建议。"""
import gzip, math, os, pickle, statistics, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "api")]
import backtest_tune as T
import signal_search as SS
import signal_validate as SV

pc, tt = SS.pc, SS.tt


def lev_stats(r, s, beta):
    eq = seq = 1.0
    peak = speak = 1.0
    mdd = smdd = 0.0
    for x, y in zip(r, s):
        eq *= 1 + x; peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
        z = beta * y
        seq *= max(1 + z, 0.0); speak = max(speak, seq); smdd = min(smdd, seq / speak - 1)
    yrs = len(r) / 252
    return eq ** (1 / yrs) - 1, mdd, seq ** (1 / yrs) - 1, smdd


def portfolio_lev(D, S_, mask, h, bars, spy, sidx, d0, d1):
    mb = (mask & S_.vint[h]).to_bytes(D["n"], "big")
    day = {}
    for g, a, b in D["slices"]:
        if not (d0 <= D["dates"][g] <= d1):
            continue
        for j in range(a, b):
            if not mb[j]:
                continue
            o = D["uidx"][j]
            B = bars[D["syms"][D["stock"][o]]]
            e = D["tidx"][o] + 1
            if e + h >= len(B["a"]):
                continue
            for k in range(h + 1):
                x = e + k
                r = B["a"][x] / B["ao"][e] - 1 if k == 0 else B["a"][x] / B["a"][x - 1] - 1
                r -= (SS.COST if k == 0 else 0) + (SS.COST if k == h else 0)
                si = sidx.get(B["d"][x])
                if si is not None:
                    day.setdefault(si, []).append(r)
    idx = sorted(i for i in day if d0 <= spy["d"][i] <= d1)
    start = idx[min(h, len(idx) // 3)]
    idx = [i for i in idx if i >= start]
    r = [sum(day[i]) / len(day[i]) for i in idx]
    s = [spy["a"][i] / spy["a"][i - 1] - 1 for i in idx]
    mr, ms = statistics.mean(r), statistics.mean(s)
    beta = sum((x - mr) * (y - ms) for x, y in zip(r, s)) / len(r) / statistics.pvariance(s)
    c, m, lc, lm = lev_stats(r, s, beta)
    sc, sm, _, _ = lev_stats(s, s, 1.0)
    sd, lsd = statistics.pstdev(r), statistics.pstdev([beta * y for y in s])
    return {"beta": beta, "cagr": c, "mdd": m, "sharpe": mr / sd * math.sqrt(252), "lev_cagr": lc, "lev_mdd": lm, "lev_sharpe": ms * beta / lsd * math.sqrt(252), "spy_cagr": sc, "spy_mdd": sm, "span": (spy["d"][idx[0]], spy["d"][idx[-1]])}


def main():
    t0 = time.time()
    D = SS.load()
    S_ = SS.Search(D)
    Bd = pickle.load(gzip.open(T.CACHE_BARS, "rb"))
    bars, spy, caps = Bd["bars"], Bd["spy"], Bd["caps"]
    sidx = {d: i for i, d in enumerate(spy["d"])}
    est = {}
    n = D["n"]
    for X in (5e9, 10e9):
        m = bytearray(n)
        for j in range(n):
            o = D["uidx"][j]
            sym = D["syms"][D["stock"][o]]
            B = bars[sym]
            t = D["tidx"][o]
            if caps.get(sym, 0) * B["c"][t] / B["c"][-1] >= X:
                m[j] = 1
        est[X] = int.from_bytes(bytes(m), "big")
    out = ["# 去偏差检验:当时的估计市值筛选 + 同 beta 杠杆标普对照\n"]
    w = out.append
    w("**(1) 估计市值筛选:** 估计市值 = 今天市值 × 当时股价 / 今天股价(假设股本不变,是粗略估计)。只保留「当时估计市值 ≥ 50 亿 / 100 亿美元」的观测,去掉那些「今天才成为大公司的小公司」。\n")
    w("**(2) 杠杆标普对照:** 组合的 beta 如果是 1.8,就拿 1.8 倍的标普(每天再平衡,不计融资成本)对比——看组合的收益是不是只是杠杆。\n")
    for h in (30, 60, 120):
        chosen, stages, fin = S_.run(h)
        mask = fin["mask"]
        w(f"\n## 持有 {h} 天:{' 且 '.join(fin['conds'])}\n")
        w("| 股票池 | 样本内 观测/扣beta/原始/按月t | 样本外 观测/扣beta/原始/按月t |\n|---|---|---|")
        for nm, mm in (("当时成交额前 50%(原搜索股池)", S_.full), ("再要求估计市值 ≥ 50 亿", est[5e9]), ("再要求估计市值 ≥ 100 亿", est[10e9])):
            ri, ro = S_.ev(mask & mm, h, "is"), S_.ev(mask & mm, h, "oos")
            f = lambda r: f"{r['n']:,} / {pc(r['adj'])} / {pc(r['raw'])} / {tt(r['t'])}" if r else "样本不足"
            w(f"| {nm} | {f(ri)} | {f(ro)} |")
        w("\n**等权组合 vs 同 beta 的杠杆标普(含成本):**\n\n| 时期 | 区间 | 组合 beta | 组合年化 | 组合最大回撤 | 组合夏普 | 同beta杠杆标普 年化 | 杠杆标普 最大回撤 | 杠杆标普 夏普 | 1倍标普 年化 | 1倍标普 最大回撤 |\n|---|---|---|---|---|---|---|---|---|---|---|")
        for per, d0, d1 in (("样本内", "2017-01-01", "2022-12-31"), ("样本外", T.SPLIT, spy["d"][-1])):
            for nm, mm in (("原搜索股池", S_.full), ("估计市值≥100亿", est[10e9])):
                if mm is not S_.full and not S_.ev(mask & mm, h, "is" if per == "样本内" else "oos"):
                    continue
                p = portfolio_lev(D, S_, mask & mm, h, bars, spy, sidx, d0, d1)
                w(f"| {per}({nm}) | {p['span'][0]} 到 {p['span'][1]} | {p['beta']:.2f} | {pc(p['cagr'])} | {pc(p['mdd'])} | {p['sharpe']:.2f} | {pc(p['lev_cagr'])} | {pc(p['lev_mdd'])} | {p['lev_sharpe']:.2f} | {pc(p['spy_cagr'])} | {pc(p['spy_mdd'])} |")
        print(f"持有 {h} 天完成 用时 {time.time() - t0:.0f} 秒", flush=True)
    open(os.path.join(HERE, "signal_validation2.md"), "w", encoding="utf-8").write("\n".join(out))
    print("已生成 tools/signal_validation2.md")


if __name__ == "__main__":
    main()
