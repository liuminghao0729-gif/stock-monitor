"""参数诊断与调优(10 年日线):先用"样本内"(2023 年以前)找规律和调参数,再用"样本外"(2023 年以后)检验。
为什么用 10 年:5 年只有一个牛市周期,样本内外都太像;10 年包含 2018 年底下跌、2020 年崩盘、2022 年熊市、2023 年之后的 AI 牛市。
本文件只做技术条件(基本面没有历史时点数据,没法回测)。已知偏差:幸存者偏差(今天的成分股)、用今天的市值筛选、10 年比 5 年的幸存者偏差更重。
用法:python3 tools/backtest_tune.py scan   生成带特征的信号事件(约十分钟,结果缓存)
      python3 tools/backtest_tune.py tune   诊断 + 调参 + 样本外检验,写 tools/tune_report.md
仅为研究,不构成投资建议。"""
import datetime, gzip, math, os, pickle, statistics, sys, time
from array import array
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "api"), HERE]
import _core as core
import screener_v2 as S
import backtest as BT

H = (20, 60, 120)
COST = BT.COST_SIDE
COOLDOWN = 20
WARM = 252
CACHE_BARS = os.path.join(HERE, ".cache", "bars10y.pkl.gz")
CACHE_EV = os.path.join(HERE, ".cache", "events10y.pkl.gz")
SPLIT = "2023-01-01"            # 样本内:此前;样本外:此后
PATHLEN = 61                    # 保存 60 天的逐日路径(用来算组合曲线)


# =============================== 数据 ===============================
def fetch10(sym):
    r = core._chart(sym, "10y", "1d", 3600)
    q, ts = r["indicators"]["quote"][0], r["timestamp"]
    adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
    rows = [i for i in range(len(ts)) if None not in (q["open"][i], q["high"][i], q["low"][i], q["close"][i], adj[i]) and q["close"][i] > 0]
    f = [adj[i] / q["close"][i] for i in rows]
    return {"d": [datetime.datetime.fromtimestamp(ts[i], datetime.timezone.utc).strftime("%Y-%m-%d") for i in rows],
            "ao": array("d", [q["open"][i] * k for i, k in zip(rows, f)]), "h": array("d", [q["high"][i] for i in rows]), "l": array("d", [q["low"][i] for i in rows]),
            "c": array("d", [q["close"][i] for i in rows]), "a": array("d", [adj[i] for i in rows]), "v": array("d", [(q["volume"][i] or 0) for i in rows])}


def load_bars(refresh=False):
    if os.path.exists(CACHE_BARS) and not refresh:
        return pickle.load(gzip.open(CACHE_BARS, "rb"))
    print("下载 10 年日线(只有第一次)…")
    uni = [u for u in S.get_universe() if u["type_ok"]]
    spy = fetch10("SPY")

    def one(u):
        try:
            return u["sym"], fetch10(u["sym"])
        except Exception:
            return u["sym"], None
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, uni))
    d = {"spy": spy, "bars": {s: b for s, b in res if b and len(b["c"]) > WARM + 130}, "caps": {u["sym"]: u["cap"] for u in uni}}
    os.makedirs(os.path.dirname(CACHE_BARS), exist_ok=True)
    pickle.dump(d, gzip.open(CACHE_BARS, "wb"))
    print(f"    股票 {len(d['bars'])} 只")
    return d


# =============================== 扫描:每个"候选日"记录特征和之后的收益 ===============================
def scan_feat(sym, B, spy, spy_idx, regime, cap):
    n = len(B["c"])
    c, h, l, v, a, ao = B["c"], B["h"], B["l"], B["v"], B["a"], B["ao"]
    s5, s20, s50, s200 = S.sma(c, 5), S.sma(c, 20), S.sma(c, 50), S.sma(c, 200)
    rs = S.rsi_wilder(c, 14)
    mc = S.macd_line(c)
    bl = BT.roll_boll_lower(c)
    atr, adx, pdi, mdi = BT.wilder_series(h, l, c)
    piv3 = BT.pivot_lows(c, 3)
    pre, prv = [0.0], [0.0]
    for i in range(n):
        pre.append(pre[-1] + c[i] * v[i])
        prv.append(prv[-1] + v[i])
    sa = []
    last = None
    for d in B["d"]:
        last = spy["a"][spy_idx[d]] if d in spy_idx else last
        sa.append(last)
    ev = {"growth": [], "pullback": [], "reversal": []}
    nxt = {k: 0 for k in ev}
    cap5, cap10 = cap >= 5e9, cap >= 10e9

    def make(t, f):
        e = t + 1
        if e >= n or B["d"][e] not in spy_idx:
            return None
        path = array("f", [(a[k] / a[k - 1] - 1) if k > e else (a[k] / ao[e] - 1) for k in range(e, min(n, e + PATHLEN))])
        rec = {"sym": sym, "date": B["d"][t], "reg": regime.get(B["d"][t], "NEUTRAL"), "f": f, "path": path}
        for hh in H:
            x = e + hh
            if x < n and B["d"][x] in spy_idx:
                r = 1.0
                for k in range(e, x + 1):
                    r *= (a[k] / a[k - 1]) if k > e else (a[k] / ao[e])
                rec[f"r{hh}"] = r * (1 - COST) / (1 + COST) - 1
                rec[f"s{hh}"] = spy["a"][spy_idx[B["d"][x]]] / spy["ao"][spy_idx[B["d"][e]]] - 1
        return rec if "r60" in rec else None

    base = {hh: [0.0, 0.0, 0] for hh in H}
    for t in range(WARM, n - 2):
        if s200[t] is None or atr[t] is None or adx[t] is None or rs[t] is None or sa[t] is None or sa[t - 63] is None:
            continue
        px = c[t]
        adv = (pre[t + 1] - pre[t - 59]) / 60
        if px < 10 or adv < 20e6:
            continue
        if t % 5 == 0:
            for hh in H:
                x = t + 1 + hh
                if x < n and B["d"][x] in spy_idx and B["d"][t + 1] in spy_idx:
                    base[hh][0] += a[x] / ao[t + 1] - 1
                    base[hh][1] += spy["a"][spy_idx[B["d"][x]]] / spy["ao"][spy_idx[B["d"][t + 1]]] - 1
                    base[hh][2] += 1
        avg20x = (prv[t] - prv[t - 20]) / 20
        vr = v[t] / avg20x if avg20x > 0 else None
        rs63 = (a[t] / a[t - 63]) / (sa[t] / sa[t - 63]) - 1
        rs126 = (a[t] / a[t - 126]) / (sa[t] / sa[t - 126]) - 1 if sa[t - 126] else None
        hi52, lo52 = max(h[t - 251:t + 1]), min(l[t - 251:t + 1])
        atrp, ext = atr[t] / px, (px - s20[t]) / atr[t]
        common = {"rs63": rs63, "rs126": rs126, "atrp": atrp, "ext": ext, "vr": vr, "rsi": rs[t], "adx": adx[t], "dm": pdi[t] - mdi[t],
                  "near_high": px / hi52, "dd52": 1 - px / hi52, "ret63": a[t] / a[t - 63] - 1}
        # ---- 激进成长家族:多头排列的趋势股 ----
        if cap5 and s20[t] > s50[t] > s200[t] and px > s20[t] and t >= nxt["growth"]:
            sl, r2 = BT.slope_r2(c, t)
            f = dict(common, r2=r2, slope=sl, s50slope=s50[t] / s50[t - 20] - 1, dd20=1 - px / max(h[t - 19:t + 1]))
            rec = make(t, f)
            if rec:
                ev["growth"].append(rec)
                nxt["growth"] = t + COOLDOWN
        # ---- 强势回调家族:长期上升趋势中的回调后回升 ----
        if cap5 and px > s200[t] and s50[t] > s200[t] and s200[t] > s200[t - 20] and t >= nxt["pullback"]:
            rmin5 = min(x for x in rs[t - 4:t + 1] if x is not None)
            if rmin5 <= 55 and rs[t] > rs[t - 1]:
                last5 = range(t - 4, t + 1)
                touch5 = any(bl[i] is not None and l[i] <= bl[i] for i in last5)
                near5 = any(atr[i] is not None and ((s20[i] is not None and abs(l[i] - s20[i]) <= .5 * atr[i]) or (s50[i] is not None and abs(l[i] - s50[i]) <= .5 * atr[i])) for i in last5)
                f = dict(common, rmin5=rmin5, bounce=rs[t] - rmin5, dd20=1 - px / max(h[t - 19:t + 1]), touch5=touch5, near5=near5,
                         conf_hi=px > h[t - 1], conf_sma5=(c[t - 1] <= s5[t - 1] and px > s5[t]), dist50=(px - s50[t]) / atr[t],
                         rs_pre=((a[t - 10] / a[t - 136]) / (sa[t - 10] / sa[t - 136]) - 1) if t >= 136 and sa[t - 136] else None,
                         s200slope=s200[t] / s200[t - 20] - 1)
                rec = make(t, f)
                if rec:
                    ev["pullback"].append(rec)
                    nxt["pullback"] = t + COOLDOWN
        # ---- 超跌反转家族:深度回撤后 RSI 回升 ----
        if cap10 and rs[t] >= 38 and rs[t] > rs[t - 1] and t >= nxt["reversal"]:
            rmin15 = min(x for x in rs[t - 14:t + 1] if x is not None)
            rpos = (px - lo52) / (hi52 - lo52) if hi52 > lo52 else None
            if rmin15 <= 40 and rpos is not None and (rpos <= 0.5 or 1 - px / hi52 >= 0.15) and avg20x > 0:
                above2 = px > s20[t] and c[t - 1] > s20[t - 1]
                f = dict(common, rpos=rpos, rmin15=rmin15, divA=BT.div_signal(c, mc, piv3, t, 3, 90, 10, 20), above2=above2,
                         brk5=px > max(h[t - 5:t]), brk10=px > max(h[t - 10:t]), capit=max(v[t - 14:t + 1]) / avg20x, ret20=px / c[t - 20] - 1)
                rec = make(t, f)
                if rec:
                    ev["reversal"].append(rec)
                    nxt["reversal"] = t + COOLDOWN
    return ev, base


def cmd_scan():
    t0 = time.time()
    D = load_bars()
    spy, bars, caps = D["spy"], D["bars"], D["caps"]
    if len(sys.argv) > 2:
        bars = dict(list(bars.items())[:int(sys.argv[2])])
    spy_idx = {d: i for i, d in enumerate(spy["d"])}
    reg = BT.regime_map(spy)
    print(f"扫描 {len(bars)} 只股票:{spy['d'][0]} 到 {spy['d'][-1]}")
    allev = {k: [] for k in ("growth", "pullback", "reversal")}
    base = {hh: [0.0, 0.0, 0] for hh in H}
    for j, (sym, B) in enumerate(bars.items()):
        ev, bs = scan_feat(sym, B, spy, spy_idx, reg, caps.get(sym, 0))
        for k in allev:
            allev[k] += ev[k]
        for hh in H:
            for z in range(3):
                base[hh][z] += bs[hh][z]
        if (j + 1) % 100 == 0:
            print(f"  {j + 1}/{len(bars)} 用时 {time.time() - t0:.0f} 秒;事件 " + str({k: len(v) for k, v in allev.items()}), flush=True)
    pickle.dump({"events": allev, "base": base, "spy_dates": spy["d"]}, gzip.open(CACHE_EV, "wb"))
    print(f"完成,用时 {time.time() - t0:.0f} 秒;事件 {({k: len(v) for k, v in allev.items()})}")


# =============================== 统计工具 ===============================
def exc(e, hh):
    return e[f"r{hh}"] - e[f"s{hh}"]


def cluster_t(evs, hh):
    """按月聚类的 t 值:先算每个月所有事件的平均超额,再对月份做 t 检验(同一个月的信号高度相关,不能把事件当独立样本)。"""
    by = {}
    for e in evs:
        if f"r{hh}" in e:
            by.setdefault(e["date"][:7], []).append(exc(e, hh))
    m = [sum(v) / len(v) for v in by.values()]
    if len(m) < 3:
        return None, len(m), None
    sd = statistics.stdev(m)
    return (statistics.mean(m) / (sd / math.sqrt(len(m))) if sd else None), len(m), sum(1 for x in m if x > 0) / len(m)


def summ(evs, hh=60):
    ev = [e for e in evs if f"r{hh}" in e]
    if not ev:
        return None
    t, months, pos = cluster_t(ev, hh)
    rs = [e[f"r{hh}"] for e in ev]
    return {"n": len(ev), "mean": statistics.mean(rs), "excess": statistics.mean(exc(e, hh) for e in ev), "beat": sum(1 for e in ev if exc(e, hh) > 0) / len(ev),
            "t": t, "months": months, "posm": pos, "atrp": statistics.mean(e["f"]["atrp"] for e in ev)}


def ok(f, k, fn):
    v = f.get(k)
    return v is not None and fn(v)


# =============================== 原版 V2.0 技术条件(在特征事件上复现) ===============================
ORIG = {
    "growth": lambda f: f["adx"] >= 20 and f["dm"] > 0 and ok(f, "rs63", lambda x: x > 0) and f["slope"] > 0 and f["s50slope"] > 0,
    "pullback": lambda f: (f["touch5"] or f["near5"] or 0.04 <= f["dd20"] <= 0.12) and f["rmin5"] <= 50 and f["bounce"] >= 3 and (f["conf_hi"] or f["conf_sma5"]),
    "reversal": lambda f: (f["rpos"] <= 0.35 or f["dd52"] >= 0.25) and f["rmin15"] <= 35 and f["rsi"] >= 40 and ((f["divA"] and (f["brk5"] or f["above2"]) and (f["vr"] or 0) >= 1.2) or (f["rmin15"] <= 30 and f["brk10"] and f["above2"] and (f["vr"] or 0) >= 1.5)),
}

# =============================== 调参网格 ===============================
O = lambda name, fn: (name, fn)
GRID = {
    "growth": {
        "ADX": [O("不限", None), O("≥25", lambda f: f["adx"] >= 25), O("≥30", lambda f: f["adx"] >= 30)],
        "相对强度 RS63": [O("不限", None), O(">5%", lambda f: ok(f, "rs63", lambda x: x > .05)), O(">15%", lambda f: ok(f, "rs63", lambda x: x > .15)), O(">30%", lambda f: ok(f, "rs63", lambda x: x > .30))],
        "离20日线的距离(ATR)": [O("不限", None), O("≤2", lambda f: f["ext"] <= 2), O("≤1", lambda f: f["ext"] <= 1), O("≤0.5", lambda f: f["ext"] <= .5)],
        "距52周高点": [O("不限", None), O("≥90%", lambda f: f["near_high"] >= .90), O("≥95%", lambda f: f["near_high"] >= .95)],
        "趋势拟合 R²": [O("不限", None), O("≥0.6", lambda f: f["r2"] >= .6), O("≥0.8", lambda f: f["r2"] >= .8)],
        "波动 ATR%": [O("不限", None), O("≤4%", lambda f: f["atrp"] <= .04), O("≤3%", lambda f: f["atrp"] <= .03)],
    },
    "pullback": {
        "5日最低RSI": [O("≤55", None), O("≤50", lambda f: f["rmin5"] <= 50), O("≤45", lambda f: f["rmin5"] <= 45), O("≤40", lambda f: f["rmin5"] <= 40)],
        "距20日高点回撤": [O("不限", None), O("4–12%", lambda f: .04 <= f["dd20"] <= .12), O("6–15%", lambda f: .06 <= f["dd20"] <= .15), O("8–20%", lambda f: .08 <= f["dd20"] <= .20)],
        "RSI回升幅度": [O("≥0", None), O("≥3", lambda f: f["bounce"] >= 3), O("≥6", lambda f: f["bounce"] >= 6)],
        "相对强度 RS63": [O("不限", None), O(">0", lambda f: ok(f, "rs63", lambda x: x > 0)), O(">10%", lambda f: ok(f, "rs63", lambda x: x > .10))],
        "价格确认": [O("不限", None), O("破前高或上穿5日线", lambda f: f["conf_hi"] or f["conf_sma5"]), O("收盘破前日最高", lambda f: f["conf_hi"])],
        "波动 ATR%": [O("不限", None), O("≤4%", lambda f: f["atrp"] <= .04)],
        "量比": [O("不限", None), O("≥1", lambda f: (f["vr"] or 0) >= 1), O("≥1.5", lambda f: (f["vr"] or 0) >= 1.5)],
    },
    "reversal": {
        "15日最低RSI": [O("≤40", None), O("≤35", lambda f: f["rmin15"] <= 35), O("≤30", lambda f: f["rmin15"] <= 30), O("≤25", lambda f: f["rmin15"] <= 25)],
        "超跌深度": [O("位置≤50%或回撤≥15%", None), O("位置≤35%或回撤≥25%", lambda f: f["rpos"] <= .35 or f["dd52"] >= .25), O("位置≤20%或回撤≥35%", lambda f: f["rpos"] <= .2 or f["dd52"] >= .35)],
        "当前RSI": [O("≥38", None), O("≥40", lambda f: f["rsi"] >= 40), O("≥45", lambda f: f["rsi"] >= 45)],
        "反转确认": [O("不限", None), O("突破5日高", lambda f: f["brk5"]), O("连续2日站上20日线", lambda f: f["above2"]), O("MACD底背离", lambda f: f["divA"]),
                 O("底背离+价格确认", lambda f: f["divA"] and (f["brk5"] or f["above2"])), O("RSI≤30+破10日高+站上20日线", lambda f: f["rmin15"] <= 30 and f["brk10"] and f["above2"])],
        "量比": [O("不限", None), O("≥1.2", lambda f: (f["vr"] or 0) >= 1.2), O("≥1.5", lambda f: (f["vr"] or 0) >= 1.5)],
    },
}
MIN_N = {"growth": 600, "pullback": 400, "reversal": 120}
NAMES_ZH = {"growth": "激进成长", "pullback": "强势回调", "reversal": "超跌反转"}


def grid_search(fam, IS):
    import itertools
    dims = list(GRID[fam].items())
    masks = []
    for _, opts in dims:
        masks.append([None if fn is None else [bool(fn(e["f"])) for e in IS] for _, fn in opts])
    ex60 = [exc(e, 60) for e in IS]
    mon = [e["date"][:7] for e in IS]
    res = []
    total = 0
    for combo in itertools.product(*[range(len(o)) for _, o in dims]):
        total += 1
        ms = [masks[i][c] for i, c in enumerate(combo) if masks[i][c] is not None]
        if ms:
            sel = [i for i, flags in enumerate(zip(*ms)) if all(flags)]
        else:
            sel = list(range(len(IS)))
        if len(sel) < MIN_N[fam]:
            continue
        by = {}
        for i in sel:
            by.setdefault(mon[i], []).append(ex60[i])
        m = [sum(v) / len(v) for v in by.values()]
        if len(m) < 24:
            continue
        sd = statistics.stdev(m)
        t = statistics.mean(m) / (sd / math.sqrt(len(m))) if sd else 0
        res.append({"combo": combo, "n": len(sel), "excess": sum(ex60[i] for i in sel) / len(sel), "t": t, "posm": sum(1 for x in m if x > 0) / len(m)})
    res.sort(key=lambda r: -r["excess"])
    return dims, res, total


def pick_rule(dims, combo):
    fns = [dims[i][1][c][1] for i, c in enumerate(combo) if dims[i][1][c][1] is not None]
    return lambda f: all(fn(f) for fn in fns)


def desc_rule(dims, combo):
    return ";".join(f"{dims[i][0]} {dims[i][1][c][0]}" for i, c in enumerate(combo) if dims[i][1][c][1] is not None) or "(无额外条件)"


# =============================== 组合层面:等权持仓 vs SPY ===============================
def portfolio_vs_spy(evs, spy, d0, d1, hold=60):
    sidx = {d: i for i, d in enumerate(spy["d"])}
    day = {}
    for e in evs:
        i0 = sidx.get(e["date"])
        if i0 is None:
            continue
        p = e["path"]
        for k in range(min(len(p), hold + 1)):
            r = p[k] - (COST if k == 0 else 0) - (COST if k == min(len(p), hold + 1) - 1 and len(p) >= hold + 1 else 0)
            day.setdefault(i0 + 1 + k, []).append(r)
    dates = [i for i in range(len(spy["d"])) if d0 <= spy["d"][i] <= d1]
    eq = peak = 1.0
    seq, mdd, inv, spy_inv = [], 0.0, 0, 0.0
    seq_spy = []
    for i in dates:
        sr = spy["a"][i] / spy["a"][i - 1] - 1
        seq_spy.append(sr)
        r = (sum(day[i]) / len(day[i])) if i in day else 0.0
        inv += i in day
        spy_inv += sr if i in day else 0.0
        seq.append(r)
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    yrs = len(dates) / 252
    spy_eq = 1.0
    spy_peak, spy_mdd = 1.0, 0.0
    for sr in seq_spy:
        spy_eq *= 1 + sr
        spy_peak = max(spy_peak, spy_eq)
        spy_mdd = min(spy_mdd, spy_eq / spy_peak - 1)
    sh = lambda a: (statistics.mean(a) / statistics.pstdev(a) * math.sqrt(252)) if statistics.pstdev(a) else None
    return {"cagr": eq ** (1 / yrs) - 1, "mdd": mdd, "sharpe": sh(seq), "invested": inv / len(dates), "spy_cagr": spy_eq ** (1 / yrs) - 1, "spy_mdd": spy_mdd, "spy_sharpe": sh(seq_spy),
            "invested_spy_ret": (1 + spy_inv / max(inv, 1)) ** 252 - 1}


def pct(x, s=True):
    return "--" if x is None else (f"{x * 100:+.1f}%" if s else f"{x * 100:.0f}%")


def cmd_tune():
    E = pickle.load(gzip.open(CACHE_EV, "rb"))
    ev, base, spy = E["events"], E["base"], pickle.load(gzip.open(CACHE_BARS, "rb"))["spy"]
    out = []
    w = out.append
    w("# 选股条件的诊断与调参报告(10 年日线,样本内 2023 年以前调参 / 样本外 2023 年以后检验)\n")
    w(f"数据区间 {spy['d'][0]} 到 {spy['d'][-1]}。技术条件回测,入场 T+1 开盘价,每边成本 {COST * 100:.1f}%,同一股票同一家族 20 个交易日不重复。\n")
    w("**偏差(会让数字偏好看):** 幸存者偏差(今天的成分股;10 年比 5 年更重)、用今天的市值筛选范围、基本面没测。\n")
    # ---- 1 基准 ----
    w("## 1. 先看基准:这批股票本身,有没有比标普 500 更好\n\n同一批股票、同样的流动性条件下,随便哪天入场(每 5 天抽样一次)的平均收益 vs 同期 SPY:\n\n| 持有 | 随机入场平均收益 | 同期 SPY | 差 |\n|---|---|---|---|")
    bs = {}
    for hh in H:
        b = base[hh]
        bs[hh] = (b[0] / b[2], b[1] / b[2])
        w(f"| {hh} 天 | {pct(bs[hh][0])} | {pct(bs[hh][1])} | {pct(bs[hh][0] - bs[hh][1])} |")
    w("\n意思:如果这个差接近 0,说明**整个选股池本身没有比标普更好**,选股要靠信号来创造超额收益,而不是靠「挑了一批个股」。\n")
    # ---- 2 现有条件的表现 ----
    for fam in ("growth", "pullback", "reversal"):
        allev = ev[fam]
        IS = [e for e in allev if e["date"] < SPLIT]
        OOS = [e for e in allev if e["date"] >= SPLIT]
        w(f"## 2.{list(NAMES_ZH).index(fam) + 1} {NAMES_ZH[fam]}:现有条件 vs 整个家族\n")
        w("| 版本 | 时期 | 事件数 | 平均收益(60天) | **超 SPY** | 战胜 SPY 的比例 | 按月 t 值 | 平均 ATR% |\n|---|---|---|---|---|---|---|---|")
        for nm, evs in (("家族全体(不加任何过滤)", allev), ("现有 V2.0 技术条件", [e for e in allev if ORIG[fam](e["f"])])):
            for per, sub in (("样本内", [e for e in evs if e["date"] < SPLIT]), ("样本外", [e for e in evs if e["date"] >= SPLIT])):
                s = summ(sub)
                if s:
                    w(f"| {nm} | {per} | {s['n']:,} | {pct(s['mean'])} | **{pct(s['excess'])}** | {pct(s['beat'], False)} | {s['t']:.2f} | {pct(s['atrp'], False)} |" if s["t"] is not None else f"| {nm} | {per} | {s['n']:,} | {pct(s['mean'])} | **{pct(s['excess'])}** | {pct(s['beat'], False)} | -- | {pct(s['atrp'], False)} |")
        regs = {}
        for e in allev:
            regs.setdefault(e["reg"], []).append(e)
        w("\n按入场时的市场环境(全体事件,60 天超 SPY):" + ";".join(f"{k} {len(v):,} 个 {pct(summ(v)['excess'])}" for k, v in regs.items() if summ(v)) + "\n")
        # 单变量诊断:样本内按特征分档
        w(f"**单变量诊断(样本内,60 天超 SPY;每档事件数相近):**\n")
        feats = ["adx", "rs63", "ext", "near_high", "r2", "atrp", "vr", "rsi"] if fam == "growth" else (["rmin5", "dd20", "bounce", "rs63", "dist50", "atrp", "vr", "rs_pre"] if fam == "pullback" else ["rmin15", "rpos", "dd52", "rsi", "vr", "capit", "ret20", "atrp"])
        w("| 特征 | 最低 20% | 20–40% | 40–60% | 60–80% | 最高 20% |\n|---|---|---|---|---|---|")
        for ft in feats:
            vals = sorted(((e["f"][ft], e) for e in IS if e["f"].get(ft) is not None and "r60" in e), key=lambda x: x[0])
            if len(vals) < 500:
                continue
            k = len(vals) // 5
            cells = []
            for q in range(5):
                chunk = [e for _, e in vals[q * k:(q + 1) * k if q < 4 else len(vals)]]
                lo, hi = vals[q * k][0], vals[min((q + 1) * k, len(vals)) - 1][0]
                cells.append(f"{pct(statistics.mean(exc(e, 60) for e in chunk))}<br><span style='color:#888'>{lo:.2f}–{hi:.2f}</span>")
            w(f"| {ft} | " + " | ".join(cells) + " |")
        w("")
        # ---- 调参 ----
        dims, res, total = grid_search(fam, IS)
        w(f"### 调参(只用样本内选;共试了 {total} 种组合,其中事件数够多的 {len(res)} 种)\n")
        w(f"挑选规则:样本内 60 天超 SPY 最高,且事件数 ≥ {MIN_N[fam]}、覆盖 ≥ 24 个月。**因为试了很多组合,样本内最好的那个几乎一定包含运气成分,必须看样本外。**\n")
        w("| 排名 | 条件 | 样本内 事件/超SPY/按月t/正月份占比 | **样本外 事件/超SPY/按月t** | 样本外 超SPY(120天) |\n|---|---|---|---|---|")
        for rk, r in enumerate(res[:6], 1):
            rule = pick_rule(dims, r["combo"])
            o = summ([e for e in OOS if rule(e["f"])])
            o120 = summ([e for e in OOS if rule(e["f"])], 120)
            w(f"| {rk} | {desc_rule(dims, r['combo'])} | {r['n']:,} / {pct(r['excess'])} / {r['t']:.2f} / {pct(r['posm'], False)} | " + (f"{o['n']:,} / **{pct(o['excess'])}** / {('%.2f' % o['t']) if o['t'] is not None else '--'}" if o else "无") + f" | {pct(o120['excess']) if o120 else '--'} |")
        if res:
            best = pick_rule(dims, res[0]["combo"])
            # 组合层面:样本外
            tuned_oos = [e for e in OOS if best(e["f"])]
            orig_oos = [e for e in OOS if ORIG[fam](e["f"])]
            w(f"\n**组合层面(样本外 {SPLIT} 起,等权持有、每笔 60 天、空仓时为现金,含成本)——样本内第 1 名的条件 vs 现有条件 vs 买入持有 SPY:**\n")
            w("| 方案 | 年化收益 | 最大回撤 | 夏普 | 持仓时间占比 | SPY 同期年化 | SPY 回撤 | SPY 夏普 | 只看持仓那些天的 SPY 年化 |\n|---|---|---|---|---|---|---|---|---|")
            for nm, evs in (("调参后(样本内第1名)", tuned_oos), ("现有 V2.0 条件", orig_oos), ("家族全体", [e for e in OOS])):
                if len(evs) < 20:
                    continue
                p = portfolio_vs_spy(evs, spy, SPLIT, spy["d"][-1])
                w(f"| {nm} | {pct(p['cagr'])} | {pct(p['mdd'])} | {p['sharpe']:.2f} | {pct(p['invested'], False)} | {pct(p['spy_cagr'])} | {pct(p['spy_mdd'])} | {p['spy_sharpe']:.2f} | {pct(p['invested_spy_ret'])} |")
        w("")
    open(os.path.join(HERE, "tune_report.md"), "w", encoding="utf-8").write("\n".join(out))
    print("已生成 tools/tune_report.md")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        cmd_scan()
    elif len(sys.argv) > 1 and sys.argv[1] == "tune":
        cmd_tune()
    else:
        print(__doc__)
