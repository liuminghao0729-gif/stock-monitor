"""对搜索到的 30/60/120 天组合做严格的验证:分年份、阈值邻域、个股集中度、全体股票、等权组合曲线(含 beta/alpha、最大回撤)。
运行:python3 tools/signal_validate.py → tools/signal_validation.md      仅为研究,不构成投资建议。"""
import gzip, math, os, pickle, statistics, sys, time
from array import array
from itertools import compress

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "api")]
import backtest_tune as T
import factor_study as FS
import signal_search as SS

pc, tt = SS.pc, SS.tt


def portfolio(D, S_, mask, h, bars, spy, sidx, d0, d1):
    """等权组合:每个入选观测从入场日起持有 h 天,每天持仓的平均日收益;空仓为现金。窗口 [d0, d1] 取所有入选观测的入场期,避免尾部空仓。"""
    mb = (mask & S_.vint[h]).to_bytes(D["n"], "big")
    day, npos = {}, {}
    cnt = 0
    for g, a, b in S_.slices_all:
        if not (d0 <= D["dates"][g] <= d1):
            continue
        for j in range(a, b):
            if not mb[j]:
                continue
            o = D["uidx"][j]
            sym = D["syms"][D["stock"][o]]
            B = bars[sym]
            t = D["tidx"][o]
            e = t + 1
            if e + h >= len(B["a"]):
                continue
            cnt += 1
            for k in range(h + 1):
                x = e + k
                r = B["a"][x] / B["ao"][e] - 1 if k == 0 else B["a"][x] / B["a"][x - 1] - 1
                r -= (SS.COST if k == 0 else 0) + (SS.COST if k == h else 0)
                si = sidx.get(B["d"][x])
                if si is not None:
                    day.setdefault(si, []).append(r)
    idx = sorted(i for i in day if d0 <= spy["d"][i] <= d1)
    if len(idx) < 100:
        return None
    # 取"已经满仓"的区间:从第一个入场日后 h 天开始,到最后一个入场日
    start = idx[min(h, len(idx) // 3)]
    idx = [i for i in idx if i >= start]
    r = [sum(day[i]) / len(day[i]) for i in idx]
    s = [spy["a"][i] / spy["a"][i - 1] - 1 for i in idx]
    mr, ms = statistics.mean(r), statistics.mean(s)
    beta = sum((x - mr) * (y - ms) for x, y in zip(r, s)) / len(r) / statistics.pvariance(s)
    eq = seq = peak = 1.0
    mdd = smdd = 0.0
    speak = 1.0
    for x, y in zip(r, s):
        eq *= 1 + x; peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
        seq *= 1 + y; speak = max(speak, seq); smdd = min(smdd, seq / speak - 1)
    yrs = len(r) / 252
    sd, ssd = statistics.pstdev(r), statistics.pstdev(s)
    return {"cagr": eq ** (1 / yrs) - 1, "mdd": mdd, "sharpe": mr / sd * math.sqrt(252), "beta": beta, "alpha": (mr - beta * ms) * 252, "scagr": seq ** (1 / yrs) - 1,
            "smdd": smdd, "ssharpe": ms / ssd * math.sqrt(252), "avg_pos": statistics.mean(len(day[i]) for i in idx), "days": len(idx), "obs": cnt, "span": (spy["d"][idx[0]], spy["d"][idx[-1]])}


def main():
    t0 = time.time()
    D = SS.load()
    S_ = SS.Search(D)
    S_.slices_all = D["slices"]
    Bd = pickle.load(gzip.open(T.CACHE_BARS, "rb"))
    bars, spy = Bd["bars"], Bd["spy"]
    sidx = {d: i for i, d in enumerate(spy["d"])}
    out = ["# 搜索到的组合的严格验证\n"]
    w = out.append
    w("对 30、60、120 天持有期各搜索到的组合(只用样本内选出)做:分年份、阈值邻域(只动一个阈值)、个股集中度、全体股票(含不活跃的一半)、等权组合曲线(含 beta/alpha、最大回撤)。成本每边 0.10%。\n")
    w("**偏差(会让数字偏好看):** 幸存者偏差(没有退市股)、今天的市值筛选;样本外 2023 年起基本是牛市,且是少数赢家股票领涨的行情。\n")
    for h in (30, 60, 120):
        chosen, stages, fin = S_.run(h)
        mask = fin["mask"]
        w(f"\n## 持有 {h} 天:{' 且 '.join(fin['conds'])}\n")
        w(f"样本内 扣beta超额 {pc(fin['is']['adj'])}(按月 t {tt(fin['is']['t'])},{fin['is']['n']:,} 个观测);样本外 扣beta超额 {pc(fin['oos']['adj'])}、原始超额 {pc(fin['oos']['raw'])}(按月 t {tt(fin['oos']['t'])},{fin['oos']['n']:,} 个观测)。\n")
        # ---- 分年份 ----
        w("**分年份(入场年份;每年的平均扣 beta 超额 / 原始超额 / 抽样日数):**\n\n| 年份 | 扣beta超额 | 原始超额 | 抽样日数 | 平均每次入选股票数 |\n|---|---|---|---|---|")
        mb = (mask & S_.vint[h]).to_bytes(D["n"], "big")
        byy = {}
        for g, a, b in D["slices"]:
            m = mb[a:b]
            c = sum(m)
            if c < 8:
                continue
            y = D["dates"][g][:4]
            byy.setdefault(y, []).append((sum(compress(D["adj"][h][a:b], m)) / c, sum(compress(D["ex"][h][a:b], m)) / c, c))
        for y in sorted(byy):
            v = byy[y]
            w(f"| {y} | {pc(statistics.mean(x[0] for x in v))} | {pc(statistics.mean(x[1] for x in v))} | {len(v)} | {statistics.mean(x[2] for x in v):.0f} |")
        # ---- 阈值邻域 ----
        w("\n**阈值邻域(只改一个条件的阈值,其他不变;样本内 → 样本外 扣 beta 超额):**\n")
        w("| 改动的条件 | " + " | ".join(f"{int(x * 100)}%" for x in SS.CUTS) + " |\n|---|---|---|---|---|---|")
        for i, c0 in enumerate(chosen):
            others = S_.full
            for j, z in enumerate(chosen):
                if j != i:
                    others &= z[3]
            cells = []
            for x in SS.CUTS:
                cand = next(c for c in S_.cands if c[0] == c0[0] and c[1] == c0[1] and c[2] == x)
                ri, ro = S_.ev(others & cand[3], h, "is"), S_.ev(others & cand[3], h, "oos")
                cells.append(f"{pc(ri['adj']) if ri else '--'} → {pc(ro['adj']) if ro else '--'}" + (" ◀选定" if x == c0[2] else ""))
            w(f"| {S_.cond_name(c0).split('(')[0]}({'最高' if c0[1] == 'high' else '最低'}) | " + " | ".join(cells) + " |")
        grid = []
        for c1 in [c for c in S_.cands if c[0] == chosen[0][0] and c[1] == chosen[0][1]]:
            for c2 in ([c for c in S_.cands if len(chosen) > 1 and c[0] == chosen[1][0] and c[1] == chosen[1][1]] or [None]):
                for c3 in ([c for c in S_.cands if len(chosen) > 2 and c[0] == chosen[2][0] and c[1] == chosen[2][1]] or [None]):
                    m = c1[3] & (c2[3] if c2 else S_.full) & (c3[3] if c3 else S_.full)
                    ri, ro = S_.ev(m, h, "is"), S_.ev(m, h, "oos")
                    if ri and ro and ri["n"] >= 1500:
                        grid.append((ri["adj"], ro["adj"]))
        if grid:
            pos = sum(1 for _, o in grid if o > 0)
            w(f"\n全部 {len(grid)} 种阈值组合(每个条件在 5 个阈值里取,样本内观测 ≥ 1500)里:样本外扣 beta 超额为正的有 **{pos}** 种({pos / len(grid) * 100:.0f}%);样本外中位数 {pc(statistics.median(o for _, o in grid))},最差 {pc(min(o for _, o in grid))},最好 {pc(max(o for _, o in grid))}。如果只有选定的那一个点是好的、周围都不行,就是尖峰(过拟合);周围大多为正,才说明比较稳。\n")
        # ---- 个股集中度(样本外)----
        contrib, cnt = {}, {}
        for g, a, b in S_.oos_s:
            for j in range(a, b):
                if mb[j]:
                    sym = D["syms"][D["stock"][D["uidx"][j]]]
                    contrib[sym] = contrib.get(sym, 0.0) + D["adj"][h][j]
                    cnt[sym] = cnt.get(sym, 0) + 1
        tot = sum(v for v in contrib.values() if v > 0)
        top = sorted(contrib.items(), key=lambda kv: -kv[1])[:10]
        w(f"**个股集中度(样本外):** 共 {len(contrib)} 只不同的股票入选过;贡献最大的 10 只占全部正贡献的 {sum(v for _, v in top) / tot * 100:.0f}%:" + "、".join(f"{s}({cnt[s]}次)" for s, _ in top) + "\n")
        # ---- 全体股票(含不活跃一半)----
        # 用相同条件在「全体」里重新排名(排名在每个抽样日全体股票内计算)
        ks = [c[0] for c in chosen]
        sel_is, sel_oos = [], []
        for g, idx in D["groups"].items():
            if len(idx) < 150:
                continue
            ranks = [FS.rank_pct([D["F"][k][o] for o in idx]) for k in ks]
            ok = []
            for jj, o in enumerate(idx):
                good = True
                for (k, dr, x, _), rk in zip(chosen, ranks):
                    r_ = rk[jj]
                    good &= (r_ >= 1 - x) if dr == "high" else (r_ <= x)
                    if not good:
                        break
                if good and D["R"][h][o] == D["R"][h][o]:
                    ok.append(o)
            if len(ok) >= 8:
                kb = SS.NAMES.index("beta126")
                adj = statistics.mean(FS.net(D["R"][h][o]) - D["F"][kb][o] * D["SP"][h][o] for o in ok)
                raw = statistics.mean(FS.net(D["R"][h][o]) - D["SP"][h][o] for o in ok)
                (sel_is if D["dates"][g] < T.SPLIT else sel_oos).append((adj, raw))
        if sel_is and sel_oos:
            w(f"**全体股票(含当时成交额靠后的一半,条件按全体排名)——** 样本内 扣beta {pc(statistics.mean(x[0] for x in sel_is))} / 原始 {pc(statistics.mean(x[1] for x in sel_is))};样本外 扣beta {pc(statistics.mean(x[0] for x in sel_oos))} / 原始 {pc(statistics.mean(x[1] for x in sel_oos))}。\n")
        # ---- 组合曲线 ----
        w("**等权组合曲线(每个入选观测持有 h 天,等权、含成本;只统计已满仓的区间)对比买入持有 SPY:**\n\n| 时期 | 区间 | 组合年化 | 组合最大回撤 | 组合夏普 | beta | 年化 alpha | SPY 年化 | SPY 最大回撤 | SPY 夏普 | 平均持仓只数 |\n|---|---|---|---|---|---|---|---|---|---|---|")
        for per, d0, d1 in (("样本内", "2017-01-01", "2022-12-31"), ("样本外", T.SPLIT, spy["d"][-1])):
            p = portfolio(D, S_, mask, h, bars, spy, sidx, d0, d1)
            if p:
                w(f"| {per} | {p['span'][0]} 到 {p['span'][1]} | {pc(p['cagr'])} | {pc(p['mdd'])} | {p['sharpe']:.2f} | {p['beta']:.2f} | {pc(p['alpha'])} | {pc(p['scagr'])} | {pc(p['smdd'])} | {p['ssharpe']:.2f} | {p['avg_pos']:.0f} |")
        print(f"持有 {h} 天验证完成,用时 {time.time() - t0:.0f} 秒", flush=True)
    open(os.path.join(HERE, "signal_validation.md"), "w", encoding="utf-8").write("\n".join(out))
    print("已生成 tools/signal_validation.md")


if __name__ == "__main__":
    main()
