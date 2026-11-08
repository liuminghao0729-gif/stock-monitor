"""横向变量探索:不再用"满足条件才入选",而是每隔 5 个交易日,把所有合格股票按某个变量(因子)排序,
看排在最前面的 20% 之后的收益是否比标普 500 好、是否比最后 20% 好(rank IC、五分位收益)。
然后只用样本内(2023 年以前)挑出最有效的变量并组合,再在样本外(2023 年以后)检验。
变量全部是只用当天及以前价格/成交量算出的技术变量(基本面没有历史时点数据,没法测)。
入场 T+1 开盘价,持有 h 天 = 到 T+1+h 日收盘;成本每边 0.10%(也给无成本)。
已知偏差:幸存者偏差、今天的市值筛选、样本外基本是牛市、试了很多变量(22 个变量 × 4 个持有期)。
运行:python3 tools/factor_study.py build   生成数据集(几分钟);python3 tools/factor_study.py analyze  分析并写 tools/factor_report.md
仅为研究,不构成投资建议。"""
import gzip, math, os, pickle, statistics, sys, time
from array import array

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "api")]
import screener_v2 as S
import backtest as BT
import backtest_tune as T

HS = (1, 3, 5, 10, 30, 60, 120)
IC_H = (5, 30, 60, 120)
STEP = 5
COST = 0.001
DATA = os.path.join(HERE, ".cache", "factors10y.pkl.gz")
FACTORS = [  # (代码, 中文说明)
    ("mom21", "1 个月涨幅"), ("mom63", "3 个月涨幅"), ("mom126", "6 个月涨幅"), ("mom12_1", "12 个月涨幅(去掉最近 1 个月)"),
    ("rs63", "3 个月相对 SPY 强度"), ("rs126", "6 个月相对 SPY 强度"), ("near_high", "离 52 周高点(越接近越大)"), ("range_pos", "52 周区间位置"),
    ("dist50", "离 50 日线的距离"), ("dist200", "离 200 日线的距离"), ("slope50", "50 日线 20 天斜率"), ("trend_r2", "60 日趋势拟合度(带方向)"),
    ("adx_dir", "ADX(带方向)"), ("rsi14", "RSI14"), ("ret5", "5 日涨幅"), ("dd20", "离 20 日高点回撤"),
    ("vol60", "60 日波动率"), ("atrp", "ATR%"), ("beta126", "126 日 beta"), ("dvol", "成交额(对数)"), ("vr20", "量比(当日/20日均量)"), ("updn20", "20 日上涨日成交量占比"),
    ("pctb", "布林带位置 %B(0=下轨,1=上轨)"), ("bb_low", "离布林下轨的距离(收盘/下轨-1)"), ("macd_hn", "MACD 柱/价格(%)"), ("macd_x3", "近 3 日 MACD 金叉(+1)/死叉(-1)"),
    ("cons_down", "连续下跌天数"), ("clv", "收盘在当日区间的位置"), ("ll20", "离 20 日最低价的涨幅"), ("gap", "今日开盘跳空"), ("rng", "当日振幅"), ("rmin5", "近 5 日最低 RSI"),
]
NF = len(FACTORS)


def build():
    t0 = time.time()
    D = pickle.load(gzip.open(T.CACHE_BARS, "rb"))
    spy, bars, caps = D["spy"], D["bars"], D["caps"]
    sidx = {d: i for i, d in enumerate(spy["d"])}
    nan = float("nan")
    date_i, stock_i = array("i"), array("i")
    F = [array("f") for _ in range(NF)]
    R = {h: array("f") for h in HS}
    SP = {h: array("f") for h in HS}
    syms = []
    for si, (sym, B) in enumerate(bars.items()):
        if caps.get(sym, 0) < 5e9:
            continue
        syms.append(sym)
        c, h_, l_, v, a, ao, ds = B["c"], B["h"], B["l"], B["v"], B["a"], B["ao"], B["d"]
        n = len(c)
        s20, s50, s200 = S.sma(c, 20), S.sma(c, 50), S.sma(c, 200)
        rs = S.rsi_wilder(c, 14)
        atr, adx, pdi, mdi = BT.wilder_series(h_, l_, c)
        sa, last = [], None
        for d in ds:
            last = spy["a"][sidx[d]] if d in sidx else last
            sa.append(last)
        ml = S.macd_line(c)
        sg = S.ema(ml, 9)
        bl = BT.roll_boll_lower(c)
        cdn = [0] * n
        for i in range(1, n):
            cdn[i] = cdn[i - 1] + 1 if c[i] < c[i - 1] else 0
        r = [0.0] + [a[i] / a[i - 1] - 1 for i in range(1, n)]
        sr = [0.0] + [sa[i] / sa[i - 1] - 1 if sa[i - 1] else 0.0 for i in range(1, n)]
        pr, ps, prs, pss, pr2, pcv, pup, pdn = ([0.0] for _ in range(8))
        for i in range(n):
            pr.append(pr[-1] + r[i]); ps.append(ps[-1] + sr[i]); prs.append(prs[-1] + r[i] * sr[i]); pss.append(pss[-1] + sr[i] * sr[i]); pr2.append(pr2[-1] + r[i] * r[i])
            pcv.append(pcv[-1] + c[i] * v[i])
            up = v[i] if i > 0 and c[i] >= c[i - 1] else 0.0
            pup.append(pup[-1] + up); pdn.append(pdn[-1] + (v[i] - up))
        for t in range(260, n - 2, STEP):
            if s200[t] is None or atr[t] is None or adx[t] is None or rs[t] is None or sa[t] is None or sa[t - 126] is None:
                continue
            px = c[t]
            adv = (pcv[t + 1] - pcv[t - 59]) / 60
            if px < 10 or adv < 20e6 or ds[t + 1] not in sidx or ds[t] not in sidx:
                continue
            i1 = sidx[ds[t + 1]]
            avg20 = (pup[t] + pdn[t] - pup[t - 20] - pdn[t - 20]) / 20
            hi252, lo252 = max(h_[t - 251:t + 1]), min(l_[t - 251:t + 1])
            sl, r2 = BT.slope_r2(c, t)
            m = 126
            mr, ms = (pr[t + 1] - pr[t + 1 - m]) / m, (ps[t + 1] - ps[t + 1 - m]) / m
            cov = (prs[t + 1] - prs[t + 1 - m]) / m - mr * ms
            var = (pss[t + 1] - pss[t + 1 - m]) / m - ms * ms
            v60 = math.sqrt(max((pr2[t + 1] - pr2[t - 59]) / 60 - ((pr[t + 1] - pr[t - 59]) / 60) ** 2, 0)) * math.sqrt(252)
            ups, dns = pup[t + 1] - pup[t - 19], pdn[t + 1] - pdn[t - 19]
            vals = [a[t] / a[t - 21] - 1, a[t] / a[t - 63] - 1, a[t] / a[t - 126] - 1, a[t - 21] / a[t - 252] - 1,
                    (a[t] / a[t - 63]) / (sa[t] / sa[t - 63]) - 1, (a[t] / a[t - 126]) / (sa[t] / sa[t - 126]) - 1, px / hi252, (px - lo252) / (hi252 - lo252) if hi252 > lo252 else 0.5,
                    px / s50[t] - 1, px / s200[t] - 1, s50[t] / s50[t - 20] - 1, r2 * (1 if sl > 0 else -1), adx[t] * (1 if pdi[t] > mdi[t] else -1), rs[t], a[t] / a[t - 5] - 1,
                    1 - px / max(h_[t - 19:t + 1]), v60, atr[t] / px, cov / var if var > 0 else 1.0, math.log(adv), v[t] / avg20 if avg20 > 0 else 1.0, ups / (ups + dns) if ups + dns > 0 else 0.5]
            up_b = 2 * s20[t] - bl[t] if bl[t] is not None else None
            xs = 0
            for i in (t - 2, t - 1, t):
                if ml[i - 1] <= sg[i - 1] and ml[i] > sg[i]:
                    xs = 1
                elif ml[i - 1] >= sg[i - 1] and ml[i] < sg[i]:
                    xs = -1
            vals += [(px - bl[t]) / (up_b - bl[t]) if up_b and up_b > bl[t] else 0.5, px / bl[t] - 1 if bl[t] else 0.0, (ml[t] - sg[t]) / px * 100, xs, cdn[t],
                     (px - l_[t]) / (h_[t] - l_[t]) if h_[t] > l_[t] else 0.5, px / min(l_[t - 19:t + 1]) - 1, ao[t] / a[t - 1] - 1, (h_[t] - l_[t]) / px, min(x for x in rs[t - 4:t + 1] if x is not None)]
            date_i.append(i1 - 1)          # 信号日在 SPY 日期里的位置(入场在其后一天)
            stock_i.append(si)
            for k, x in enumerate(vals):
                F[k].append(x)
            for hh in HS:
                x = t + 1 + hh
                if x < n and i1 + hh < len(spy["a"]):
                    R[hh].append(a[x] / ao[t + 1] - 1)
                    SP[hh].append(spy["a"][i1 + hh] / spy["ao"][i1] - 1)
                else:
                    R[hh].append(nan); SP[hh].append(nan)
        if (len(syms)) % 200 == 0:
            print(f"  {len(syms)} 只,观测 {len(date_i):,},用时 {time.time() - t0:.0f} 秒", flush=True)
    pickle.dump({"date": date_i, "F": F, "R": R, "SP": SP, "dates": spy["d"]}, gzip.open(DATA, "wb"))
    print(f"完成:观测 {len(date_i):,},用时 {time.time() - t0:.0f} 秒")


# =============================== 分析 ===============================
def rank_pct(vals):
    """百分位排名(0 到 1,并列取平均)。"""
    n = len(vals)
    order = sorted(range(n), key=lambda i: vals[i])
    out = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = ((i + j) / 2) / (n - 1) if n > 1 else 0.5
        i = j + 1
    return out


def pearson(x, y):
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else 0.0


def tstat_monthly(pairs):
    by = {}
    for ym, x in pairs:
        by.setdefault(ym, []).append(x)
    m = [sum(v) / len(v) for v in by.values()]
    if len(m) < 3:
        return None
    sd = statistics.stdev(m)
    return statistics.mean(m) / (sd / math.sqrt(len(m))) if sd else None


def net(g, c=COST):
    return (1 + g) * (1 - c) / (1 + c) - 1


def pc(x, d=2, s=True):
    return "--" if x is None else (f"{x * 100:+.{d}f}%" if s else f"{x * 100:.{d}f}%")


def analyze():
    Z = pickle.load(gzip.open(DATA, "rb"))
    dates, date_i, F, R, SP = Z["dates"], Z["date"], Z["F"], Z["R"], Z["SP"]
    N = len(date_i)
    groups = {}
    for o in range(N):
        groups.setdefault(date_i[o], []).append(o)
    gdates = sorted(g for g, v in groups.items() if len(v) >= 150)
    ym = {g: dates[g][:7] for g in gdates}
    is_g = [g for g in gdates if dates[g] < T.SPLIT]
    oos_g = [g for g in gdates if dates[g] >= T.SPLIT]
    print(f"观测 {N:,},抽样日 {len(gdates)}(样本内 {len(is_g)},样本外 {len(oos_g)})")
    # 每个抽样日、每个变量的百分位排名(只算一次)
    RK = {}
    for g in gdates:
        idx = groups[g]
        RK[g] = [rank_pct([F[k][o] for o in idx]) for k in range(NF)]
    nanchk = lambda x: x == x
    out = ["# 横向变量探索报告:按变量排序选股,和标普 500 对比\n"]
    w = out.append
    w(f"数据:10 年日线({dates[0]} 到 {dates[-1]}),股票池:今天市值 ≥ 50 亿美元的美股,且当天成交额 ≥ 2000 万美元、股价 ≥ 10 美元;每 5 个交易日抽样一次,共 {len(gdates)} 个抽样日、{N:,} 个观测。样本内 = 2023 年以前({len(is_g)} 个抽样日),样本外 = 2023 年以后({len(oos_g)} 个)。\n")
    w("入场 T+1 开盘价,持有 h 天 = 到 T+1+h 日收盘;成本每边 0.10%。**偏差(会让数字偏好看):** 幸存者偏差、今天的市值筛选、基本面没测。**试了 22 个变量 × 4 个持有期,最好的那些有运气成分,所以只看样本外。**\n")

    def ic_series(k, h, gs):
        pairs = []
        for g in gs:
            idx = groups[g]
            ok = [(RK[g][k][j], R[h][o]) for j, o in enumerate(idx) if nanchk(R[h][o])]
            if len(ok) >= 100:
                x, y = zip(*ok)
                pairs.append((ym[g], pearson(x, rank_pct(list(y)))))
        return pairs

    # ---- 1. IC 表 ----
    w("## 1. 每个变量的预测力(rank IC:排序和之后收益排序的相关,正 = 变量越大之后越好)\n")
    w("IC 一般 0.02–0.05 就算有用;按月 t 值 ≥ 2 才算较稳。按样本内 60 天 IC 的绝对值从大到小排。\n")
    w("| 变量 | 说明 | 样本内 IC(5/30/60/120天) | 样本内 60天 t | 样本外 IC(5/30/60/120天) | 样本外 60天 t |\n|---|---|---|---|---|---|")
    icres = {}
    for k, (code, desc) in enumerate(FACTORS):
        row = {}
        for h in IC_H:
            row[("is", h)] = ic_series(k, h, is_g)
            row[("oos", h)] = ic_series(k, h, oos_g)
        icres[k] = row
    order = sorted(range(NF), key=lambda k: -abs(statistics.mean(x for _, x in icres[k][("is", 60)])))
    for k in order:
        code, desc = FACTORS[k]
        mi = [statistics.mean(x for _, x in icres[k][("is", h)]) for h in IC_H]
        mo = [statistics.mean(x for _, x in icres[k][("oos", h)]) for h in IC_H]
        ti, to = tstat_monthly(icres[k][("is", 60)]), tstat_monthly(icres[k][("oos", 60)])
        w(f"| {code} | {desc} | " + " / ".join(f"{x:+.3f}" for x in mi) + f" | {ti:.1f} | " + " / ".join(f"{x:+.3f}" for x in mo) + f" | {to:.1f} |")

    # ---- 2. 五分位 ----
    def quint(rank_fn, gs, h, top=True, frac=0.2):
        """每个抽样日取排名最高/最低 20% 的股票,返回 [(月份, 毛收益均值, 净收益均值, SPY 收益, 全体均值)]。"""
        res = []
        for g in gs:
            idx = groups[g]
            rk = rank_fn(g)
            sel = [o for j, o in enumerate(idx) if nanchk(R[h][o]) and ((rk[j] >= 1 - frac) if top else (rk[j] <= frac))]
            allv = [R[h][o] for o in idx if nanchk(R[h][o])]
            if len(sel) < 10 or len(allv) < 100:
                continue
            gm = statistics.mean(R[h][o] for o in sel)
            res.append((ym[g], gm, statistics.mean(net(R[h][o]) for o in sel), statistics.mean(SP[h][o] for o in sel), statistics.mean(allv)))
        return res

    def summarize(res):
        if len(res) < 5:
            return None
        ex_g = [(m, g - s) for m, g, n_, s, a in res]
        ex_n = [(m, n_ - s) for m, g, n_, s, a in res]
        return {"gross": statistics.mean(x for _, x in ex_g), "net": statistics.mean(x for _, x in ex_n), "t": tstat_monthly(ex_n), "beat": sum(1 for _, x in ex_n if x > 0) / len(ex_n),
                "ret": statistics.mean(n_ for _, _, n_, _, _ in res), "spy": statistics.mean(s for *_, s, _ in res), "uni": statistics.mean(a for *_, a in res), "n": len(res)}

    w("\n## 2. 单个变量:排在最高 20% 的股票 vs 标普 500(每边 0.10% 成本后的平均超额,样本外)\n")
    w("只列样本内 60 天 IC 最强的 8 个变量(按它们样本内的符号取最高或最低 20%)。\n")
    w("| 变量 | 方向 | 持有 | 样本内超 SPY | 样本外 平均收益 | 样本外 SPY | **样本外超 SPY(净)** | 样本外 无成本超额 | 胜 SPY 的抽样日占比 | 按月 t |\n|---|---|---|---|---|---|---|---|---|---|")
    top8 = order[:8]
    sign = {k: (1 if statistics.mean(x for _, x in icres[k][("is", 60)]) > 0 else -1) for k in range(NF)}
    for k in top8:
        for h in (30, 60, 120):
            rf = (lambda g, k=k: RK[g][k]) if sign[k] > 0 else (lambda g, k=k: [1 - x for x in RK[g][k]])
            si, so = summarize(quint(rf, is_g, h)), summarize(quint(rf, oos_g, h))
            if si and so:
                w(f"| {FACTORS[k][0]} | {'越大越好' if sign[k] > 0 else '越小越好'} | {h} 天 | {pc(si['net'])} | {pc(so['ret'])} | {pc(so['spy'])} | **{pc(so['net'])}** | {pc(so['gross'])} | {pc(so['beat'], 0, False)} | {('%.2f' % so['t']) if so['t'] is not None else '--'} |")

    # ---- 3. 组合变量(只用样本内选)----
    w("\n## 3. 组合变量:只用样本内选出最有效的 3 个变量,取排名平均,样本外检验\n")
    cand = [k for k in order if abs(tstat_monthly(icres[k][("is", 60)]) or 0) >= 2][:3] or order[:3]
    w("选择规则:样本内 60 天 IC 按月 t 值绝对值 ≥ 2、IC 绝对值最大的前 3 个(符号按样本内)。选出的变量:" + "、".join(f"**{FACTORS[k][0]}**({FACTORS[k][1]},{'越大越好' if sign[k] > 0 else '越小越好'})" for k in cand) + "\n")
    comp = lambda g: [sum((RK[g][k][j] if sign[k] > 0 else 1 - RK[g][k][j]) for k in cand) / len(cand) for j in range(len(groups[g]))]
    comp_rk = {}
    for g in gdates:
        sc = comp(g)
        comp_rk[g] = rank_pct(sc)
    rf = lambda g: comp_rk[g]
    w("**组合最高 20%(每次抽样日等权持有,每笔 h 天)对比标普 500:**\n")
    w("| 持有 | 时期 | 抽样日 | 平均收益(净) | 同期 SPY | 全体股票平均 | 无成本超额 | **超 SPY(净)** | 胜 SPY 占比 | 按月 t |\n|---|---|---|---|---|---|---|---|---|---|")
    summ_all = {}
    for h in HS:
        for per, gs in (("样本内", is_g), ("样本外", oos_g)):
            s = summarize(quint(rf, gs, h))
            summ_all[(h, per)] = s
            if s:
                w(f"| {h} 天 | {per} | {s['n']} | {pc(s['ret'])} | {pc(s['spy'])} | {pc(s['uni'])} | {pc(s['gross'])} | **{pc(s['net'])}** | {pc(s['beat'], 0, False)} | {('%.2f' % s['t']) if s['t'] is not None else '--'} |")
    w("\n**对照:组合最低 20%(应该比最高 20% 差,差得越明显说明变量越真)——样本外 60 天:**\n")
    low = summarize(quint(rf, oos_g, 60, top=False))
    hi = summ_all[(60, "样本外")]
    if low and hi:
        w(f"最高 20%:平均 {pc(hi['ret'])}(超 SPY {pc(hi['net'])});最低 20%:平均 {pc(low['ret'])}(超 SPY {pc(low['net'])});全体平均 {pc(hi['uni'])};SPY {pc(hi['spy'])}。\n")
    # beta/波动对照:最高 20% 的平均波动
    k_vol = [i for i, (c_, _) in enumerate(FACTORS) if c_ == "vol60"][0]
    k_beta = [i for i, (c_, _) in enumerate(FACTORS) if c_ == "beta126"][0]
    sel_v, all_v, sel_b, all_b = [], [], [], []
    for g in oos_g:
        idx = groups[g]
        rk = comp_rk[g]
        for j, o in enumerate(idx):
            all_v.append(F[k_vol][o]); all_b.append(F[k_beta][o])
            if rk[j] >= 0.8:
                sel_v.append(F[k_vol][o]); sel_b.append(F[k_beta][o])
    w(f"**风险对照(样本外):** 组合最高 20% 的平均年化波动 {pc(statistics.mean(sel_v), 0, False)}、平均 beta {statistics.mean(sel_b):.2f};全体股票平均波动 {pc(statistics.mean(all_v), 0, False)}、平均 beta {statistics.mean(all_b):.2f}。如果组合选出来的主要是高波动、高 beta 的股票,那么它的超额收益主要是在承担更高的市场风险,不是选股能力。\n")
    open(os.path.join(HERE, "factor_report.md"), "w", encoding="utf-8").write("\n".join(out))
    print("已生成 tools/factor_report.md")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build()
    elif len(sys.argv) > 1 and sys.argv[1] == "analyze":
        analyze()
    else:
        print(__doc__)
