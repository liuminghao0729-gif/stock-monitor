"""三个选股组合在不同持有期(1、3、5、10、30、60、120 个交易日)的回测,并和标普 500(SPY)对比。
沿用 10 年日线的信号事件(tools/backtest_tune.py scan 生成的缓存)。只测技术条件(现有 V2.0 技术条件)。
入场:信号 T 日收盘后确认 → T+1 日开盘价买入;"持有 h 天"= 到 T+1+h 日收盘卖出(所以持有 1 天实际跨 T+1 和 T+2 两个交易日)。复权价。
SPY 对比:同样的买入日、卖出日,买入持有 SPY 的收益。基准:同一批股票随便哪天入场(每 5 天抽样)。
成本:给出 无成本 / 每边 0.05% / 每边 0.10% 三种,因为短持有期时成本影响很大。
已知偏差:幸存者偏差、今天的市值筛选、基本面未测。仅为研究,不构成投资建议。
运行:python3 tools/backtest_horizons.py   → tools/horizon_report.md"""
import gzip, math, os, pickle, statistics, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "api")]
import backtest_tune as T

HS = (1, 3, 5, 10, 30, 60, 120)
COSTS = {"无成本": 0.0, "每边0.05%": 0.0005, "每边0.10%": 0.001}
FAM = {"growth": "激进成长", "pullback": "强势回调", "reversal": "超跌反转"}


def load():
    E = pickle.load(gzip.open(T.CACHE_EV, "rb"))
    D = pickle.load(gzip.open(T.CACHE_BARS, "rb"))
    return E, D


def gross_ret(e, h, sidx, spy):
    """毛收益(无成本)和同期 SPY 收益;数据不够返回 None。"""
    if h == 120:
        if "r120" not in e:
            return None
        c = T.COST
        return (1 + e["r120"]) * (1 + c) / (1 - c) - 1, e["s120"]
    p = e["path"]
    if len(p) < h + 1:
        return None
    r = 1.0
    for x in p[:h + 1]:
        r *= 1 + x
    i = sidx.get(e["date"])
    if i is None or i + 1 + h >= len(spy["a"]):
        return None
    return r - 1, spy["a"][i + 1 + h] / spy["ao"][i + 1] - 1


def net(g, c):
    return (1 + g) * (1 - c) / (1 + c) - 1


def cluster_t(pairs):
    """pairs: [(date, excess)] → 按月聚类 t 值。"""
    by = {}
    for d, x in pairs:
        by.setdefault(d[:7], []).append(x)
    m = [sum(v) / len(v) for v in by.values()]
    if len(m) < 3:
        return None
    sd = statistics.stdev(m)
    return statistics.mean(m) / (sd / math.sqrt(len(m))) if sd else None


def stats(evs, h, sidx, spy):
    rows = []
    for e in evs:
        g = gross_ret(e, h, sidx, spy)
        if g:
            rows.append((e["date"], g[0], g[1]))
    if len(rows) < 30:
        return None
    out = {"n": len(rows), "spy": statistics.mean(r[2] for r in rows), "gross": statistics.mean(r[1] for r in rows)}
    for nm, c in COSTS.items():
        ex = [(r[0], net(r[1], c) - r[2]) for r in rows]
        out[nm] = {"ret": statistics.mean(net(r[1], c) for r in rows), "excess": statistics.mean(x for _, x in ex), "beat": sum(1 for _, x in ex if x > 0) / len(ex), "t": cluster_t(ex)}
    return out


def baseline(D):
    """同一批股票、同样流动性条件下,每 5 天抽样入场的平均收益和同期 SPY,按持有期。"""
    spy = D["spy"]
    sidx = {d: i for i, d in enumerate(spy["d"])}
    acc = {h: [0.0, 0.0, 0] for h in HS}
    for sym, B in D["bars"].items():
        c, v, a, ao, ds = B["c"], B["v"], B["a"], B["ao"], B["d"]
        n = len(c)
        pre = [0.0]
        for i in range(n):
            pre.append(pre[-1] + c[i] * v[i])
        for t in range(260, n - 125, 5):
            if c[t] < 10 or (pre[t + 1] - pre[t - 59]) / 60 < 20e6 or ds[t + 1] not in sidx:
                continue
            i = sidx[ds[t + 1]]
            for h in HS:
                x = t + 1 + h
                if x < n and i + h < len(spy["a"]) and ds[x] in sidx:
                    acc[h][0] += a[x] / ao[t + 1] - 1
                    acc[h][1] += spy["a"][i + h] / spy["ao"][i] - 1
                    acc[h][2] += 1
    return {h: (v[0] / v[2], v[1] / v[2], v[2]) for h, v in acc.items() if v[2]}


def series(evs, d0, d1, hold, sidx, spy, c):
    """等权组合:每天持仓的所有交易日收益取平均,空仓为现金;返回 (组合日收益, SPY 日收益)。"""
    day = {}
    for e in evs:
        i0 = sidx.get(e["date"])
        p = e["path"]
        if i0 is None or len(p) < hold + 1:
            continue
        for k in range(hold + 1):
            r = p[k] - (c if k == 0 else 0) - (c if k == hold else 0)
            day.setdefault(i0 + 1 + k, []).append(r)
    idx = [i for i in range(len(spy["d"])) if d0 <= spy["d"][i] <= d1]
    return [(sum(day[i]) / len(day[i])) if i in day else 0.0 for i in idx], [spy["a"][i] / spy["a"][i - 1] - 1 for i in idx]


def port(r, s):
    mr, ms = statistics.mean(r), statistics.mean(s)
    beta = sum((a - mr) * (b - ms) for a, b in zip(r, s)) / len(r) / statistics.pvariance(s)
    eq = peak = 1.0
    mdd = 0.0
    for x in r:
        eq *= 1 + x
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    yrs = len(r) / 252
    sd = statistics.pstdev(r)
    return {"cagr": eq ** (1 / yrs) - 1, "mdd": mdd, "sharpe": mr / sd * math.sqrt(252) if sd else None, "beta": beta, "alpha": (mr - beta * ms) * 252}


def pc(x, s=True, d=2):
    return "--" if x is None else (f"{x * 100:+.{d}f}%" if s else f"{x * 100:.0f}%")


def main():
    E, D = load()
    spy = D["spy"]
    sidx = {d: i for i, d in enumerate(spy["d"])}
    print("计算随机入场基准…")
    base = baseline(D)
    out = ["# 三个选股组合在不同持有期的回测,以及和标普 500 的对比\n"]
    w = out.append
    w(f"数据:10 年日线({spy['d'][0]} 到 {spy['d'][-1]}),约 1200 只股票的技术信号;样本内 = 2023 年以前,样本外 = 2023 年以后。入场 T+1 开盘价,持有 h 天 = 到 T+1+h 日收盘。\n")
    w("**偏差(会让数字偏好看):** 幸存者偏差、用今天的市值筛选、基本面没测。**成本对短持有期影响极大**,所以给出三种成本假设。\n")
    w("## 1. 基准:随便哪天买这批股票,对比同期标普 500\n\n| 持有 | 随机入场平均收益 | 同期 SPY | 差 | 样本 |\n|---|---|---|---|---|")
    for h in HS:
        b = base[h]
        w(f"| {h} 天 | {pc(b[0])} | {pc(b[1])} | {pc(b[0] - b[1])} | {b[2]:,} |")
    results = {}
    for fam, nm in FAM.items():
        evs = [e for e in E["events"][fam] if T.ORIG[fam](e["f"])]
        results[fam] = evs
        w(f"\n## 2.{list(FAM).index(fam) + 1} {nm}(现有 V2.0 技术条件,共 {len(evs):,} 个事件)\n")
        w("**每笔交易的平均收益 vs 同期标普 500。** 超额 = 该组合收益 - 同期 SPY 收益;「胜 SPY」= 单笔跑赢同期 SPY 的比例;t 值按月聚类(同月信号高度相关)。\n")
        w("| 持有 | 时期 | 事件数 | 平均毛收益 | 同期 SPY | 超额(无成本) | 超额(每边0.05%) | **超额(每边0.10%)** | 胜SPY(每边0.10%) | 按月 t |\n|---|---|---|---|---|---|---|---|---|---|")
        for h in HS:
            for per, sub in (("全部", evs), ("样本内", [e for e in evs if e["date"] < T.SPLIT]), ("样本外", [e for e in evs if e["date"] >= T.SPLIT])):
                s = stats(sub, h, sidx, spy)
                if s:
                    c = s["每边0.10%"]
                    w(f"| {h} 天 | {per} | {s['n']:,} | {pc(s['gross'])} | {pc(s['spy'])} | {pc(s['无成本']['excess'])} | {pc(s['每边0.05%']['excess'])} | **{pc(c['excess'])}** | {pc(c['beat'], False)} | {('%.2f' % c['t']) if c['t'] is not None else '--'} |")
        w("\n**组合层面(样本外 2023 年起;每笔按该持有期,等权持有,空仓为现金,每边 0.10% 成本)对比买入持有 SPY:**\n")
        w("| 持有 | 组合年化 | 组合最大回撤 | 夏普 | beta | 年化 alpha | SPY 年化 | SPY 最大回撤 | SPY 夏普 |\n|---|---|---|---|---|---|---|---|---|")
        sub = [e for e in evs if e["date"] >= T.SPLIT]
        for h in (1, 3, 5, 10, 30, 60):
            r, sr = series(sub, T.SPLIT, spy["d"][-1], h, sidx, spy, 0.001)
            p, q = port(r, sr), port(sr, sr)
            w(f"| {h} 天 | {pc(p['cagr'])} | {pc(p['mdd'])} | {p['sharpe']:.2f} | {p['beta']:.2f} | {pc(p['alpha'])} | {pc(q['cagr'])} | {pc(q['mdd'])} | {q['sharpe']:.2f} |")
    open(os.path.join(HERE, "horizon_report.md"), "w", encoding="utf-8").write("\n".join(out))
    print("已生成 tools/horizon_report.md")


if __name__ == "__main__":
    main()
