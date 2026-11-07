"""选股技术信号的回测:V1.0 对比 V2.0(只测技术部分)。
为什么只测技术部分:免费数据没有"当时已公布的财报"(只有季度截止日,没有公告日期),基本面条件回测会有前视偏差,所以不测。
所以这里的 V2.0 是"V2.0 的技术条件",不等于完整的 V2.0 选股(完整版还要求营收增长、自由现金流等)。
已知偏差(会让结果偏好看,必须在报告里披露):
  1) 幸存者偏差:股票池是"今天"的成分股,历史上退市、被收购、跌出名单的公司不在里面。
  2) 市值前视:用今天的市值筛选范围(历史市值拿不到)。
  3) 只有最近约 5 年(一个主要牛熊周期),样本有限。
入场/出场:信号在 T 日收盘后确认 → T+1 日开盘价入场(最早能成交的价格)→ 持有 20/60/120 个交易日后按收盘价出场。价格用复权价。
成本:每边 0.1%(含滑点),往返 0.2%。同一只股票同一个策略,信号后 20 个交易日内不重复计入。
用法:python3 tools/backtest.py [--limit N] [--refresh]    结果写入 tools/backtest_results.json 和 tools/backtest_report.md
仅为研究,不构成投资建议。"""
import argparse, datetime, gzip, json, math, os, pickle, statistics, sys, time
from array import array
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "api"), HERE]
import _core as core
import screener_v2 as S
from screener_config import CONFIG as CFG

HORIZONS = (20, 60, 120)
COST_SIDE = 0.001
COOLDOWN = 20
WARM = 252
CACHE = os.path.join(HERE, ".cache", "bars5y.pkl.gz")
SPLIT = "2024-11-01"          # 样本内:此前;样本外:此后


# =============================== 数据 ===============================
def fetch(sym):
    r = core._chart(sym, "5y", "1d", 3600)
    q, ts = r["indicators"]["quote"][0], r["timestamp"]
    adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
    rows = [i for i in range(len(ts)) if None not in (q["open"][i], q["high"][i], q["low"][i], q["close"][i], adj[i]) and q["close"][i] > 0]
    f = [adj[i] / q["close"][i] for i in rows]
    return {"d": [datetime.datetime.fromtimestamp(ts[i], datetime.timezone.utc).strftime("%Y-%m-%d") for i in rows],
            "o": array("d", [q["open"][i] * k for i, k in zip(rows, f)]), "h": array("d", [q["high"][i] for i in rows]), "l": array("d", [q["low"][i] for i in rows]),
            "c": array("d", [q["close"][i] for i in rows]), "a": array("d", [adj[i] for i in rows]), "v": array("d", [(q["volume"][i] or 0) for i in rows]),
            "ao": array("d", [q["open"][i] * k for i, k in zip(rows, f)])}


def load_data(limit=0, refresh=False):
    if os.path.exists(CACHE) and not refresh:
        d = pickle.load(gzip.open(CACHE, "rb"))
        if (limit and len(d["bars"]) >= limit) or (not limit and d.get("full")):
            return d
    print("下载 5 年日线…(只有第一次需要,之后用本地缓存)")
    uni = S.get_universe()
    uni = [u for u in uni if u["type_ok"]]
    if limit:
        uni = uni[:limit]
    spy = fetch("SPY")

    def one(u):
        try:
            return u["sym"], fetch(u["sym"])
        except Exception:
            return u["sym"], None
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, uni))
    bars = {s: b for s, b in res if b and len(b["c"]) > WARM + 130}
    d = {"spy": spy, "bars": bars, "caps": {u["sym"]: u["cap"] for u in uni}, "asof": datetime.date.today().isoformat(), "full": not limit}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    pickle.dump(d, gzip.open(CACHE, "wb"))
    print(f"    股票 {len(bars)} 只,已缓存")
    return d


# =============================== 逐日指标(都只用当天及以前的数据) ===============================
def wilder_series(h, l, c, n=14):
    m = len(c)
    atr, adx, pdi, mdi = [None] * m, [None] * m, [None] * m, [None] * m
    if m < 2 * n + 2:
        return atr, adx, pdi, mdi
    tr, pdm, mdm = [0.0], [0.0], [0.0]
    for i in range(1, m):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    a, p, q = sum(tr[1:n + 1]), sum(pdm[1:n + 1]), sum(mdm[1:n + 1])
    dx = []
    for i in range(n, m):
        if i > n:
            a, p, q = a - a / n + tr[i], p - p / n + pdm[i], q - q / n + mdm[i]
        pi, mi = (100 * p / a, 100 * q / a) if a else (0.0, 0.0)
        atr[i], pdi[i], mdi[i] = a / n, pi, mi
        dx.append(100 * abs(pi - mi) / (pi + mi) if pi + mi else 0.0)
        if len(dx) == n:
            adx[i] = sum(dx) / n
        elif len(dx) > n:
            adx[i] = (adx[i - 1] * (n - 1) + dx[-1]) / n
    return atr, adx, pdi, mdi


def roll_boll_lower(c, n=20, k=2.0):
    out = [None] * len(c)
    s = s2 = 0.0
    for i, x in enumerate(c):
        s += x
        s2 += x * x
        if i >= n:
            s -= c[i - n]
            s2 -= c[i - n] * c[i - n]
        if i >= n - 1:
            mu = s / n
            out[i] = mu - k * math.sqrt(max(s2 / n - mu * mu, 0.0))
    return out


def pivot_lows(c, w):
    """全部波段低点(右侧需要 w 根确认,第 i 个低点最早在 i+w 日才知道)。平台期只保留第一个。"""
    out = []
    for i in range(w, len(c) - w):
        if c[i] <= min(c[i - w:i + w + 1]) and (not out or i - out[-1] > 1):
            out.append(i)
    return out


def slope_r2(c, t, n=60):
    y = c[t - n + 1:t + 1]
    my = sum(y) / n
    mx = (n - 1) / 2
    sxx = n * (n * n - 1) / 12
    sxy = sum((i - mx) * (v - my) for i, v in enumerate(y))
    syy = sum((v - my) ** 2 for v in y)
    return (sxy / sxx / my, sxy * sxy / (sxx * syy)) if syy > 0 else (0.0, 0.0)


def div_signal(c, macd, piv, t, w, lookback, gap, recent):
    """t 日的 MACD 底背离:只用在 t 日已经确认的波段低点(p ≤ t-w)。"""
    avail = [p for p in piv if p <= t - w and p >= t - lookback]
    if len(avail) < 2:
        return False
    p2 = avail[-1]
    if p2 < t - recent:
        return False
    p1 = next((p for p in reversed(avail[:-1]) if p2 - p >= gap), None)
    if p1 is None or (p2 < t and min(c[p2 + 1:t + 1]) < c[p2]):
        return False
    return c[p2] < c[p1] and macd[p2] > macd[p1]


# =============================== 扫描一只股票 ===============================
def scan(sym, B, spy, spy_idx, regime, cap):
    n = len(B["c"])
    c, h, l, o, v, a = B["c"], B["h"], B["l"], B["o"], B["v"], B["a"]
    s5, s20, s50, s200 = S.sma(c, 5), S.sma(c, 20), S.sma(c, 50), S.sma(c, 200)
    rs = S.rsi_wilder(c, 14)
    mc = S.macd_line(c)
    bl = roll_boll_lower(c)
    atr, adx, pdi, mdi = wilder_series(h, l, c)
    piv3, piv5 = pivot_lows(c, 3), pivot_lows(c, 5)
    cv = [c[i] * v[i] for i in range(n)]
    pre, prev_ = [0.0], [0.0]
    for i in range(n):
        pre.append(pre[-1] + cv[i])
        prev_.append(prev_[-1] + v[i])
    sa = [spy["a"][spy_idx[d]] if d in spy_idx else None for d in B["d"]]
    last_sa = None
    for i in range(n):          # 缺失日沿用前一日
        if sa[i] is None:
            sa[i] = last_sa
        last_sa = sa[i]
    ev = {k: [] for k in ("g1", "g2", "p1", "p2", "r1", "r2")}
    nxt = {k: 0 for k in ev}
    base = {hh: [0.0, 0.0, 0] for hh in HORIZONS}
    ok_cap5, ok_cap10 = cap >= 5e9, cap >= 10e9

    def make(t, name):
        e = t + 1
        rec = {"sym": sym, "t": t, "date": B["d"][t], "reg": regime[B["d"][t]] if B["d"][t] in regime else "NEUTRAL"}
        path, spyp = [], {}
        for k in range(e, min(n, e + max(HORIZONS) + 1)):
            path.append(a[k] / a[k - 1] - 1 if k > e else a[k] / B["ao"][e] - 1)
        rec["path"] = path
        for hh in HORIZONS:
            x = e + hh
            if x < n and B["d"][x] in spy_idx and B["d"][e] in spy_idx:
                rec[f"spy{hh}"] = spy["a"][spy_idx[B["d"][x]]] / spy["ao"][spy_idx[B["d"][e]]] - 1
        return rec

    for t in range(WARM, n - 2):
        if s200[t] is None or atr[t] is None or adx[t] is None:
            continue
        px = c[t]
        adv = (pre[t + 1] - pre[t + 1 - 60]) / 60
        if px < 10 or adv < 20e6 or sa[t] is None or sa[t - 63] is None:
            continue
        if t % 5 == 0:                                    # 无条件基准:同一批股票、同样条件下,随便哪天入场的平均表现
            for hh in HORIZONS:
                x = t + 1 + hh
                if x < n and B["d"][x] in spy_idx and B["d"][t + 1] in spy_idx:
                    base[hh][0] += a[x] / B["ao"][t + 1] - 1
                    base[hh][1] += spy["a"][spy_idx[B["d"][x]]] / spy["ao"][spy_idx[B["d"][t + 1]]] - 1
                    base[hh][2] += 1
        rs63 = (a[t] / a[t - 63]) / (sa[t] / sa[t - 63]) - 1
        flags = {}
        # ---------- 组合 1:激进成长(技术部分) ----------
        if ok_cap5:
            if s20[t] and s50[t] and s20[t] > s50[t] > s200[t] and px > s20[t]:
                sl, r2 = slope_r2(c, t)
                flags["g1"] = r2 >= 0.5 and sl > 0 and adx[t] >= 20                                            # V1.0
                flags["g2"] = px > s20[t] and s50[t] > s50[t - 20] and sl > 0 and adx[t] >= 20 and pdi[t] > mdi[t] and rs63 > 0   # V2.0
        # ---------- 组合 2:强势回调(技术部分) ----------
        if ok_cap5 and px > s200[t] and rs[t] is not None:
            touch3 = any(bl[i] is not None and l[i] <= bl[i] * 1.005 for i in range(t - 2, t + 1))
            flags["p1"] = rs[t] <= 40 and touch3 and c[t] / c[t - 1] - 1 < 0.09                                  # V1.0
            if s50[t] > s200[t] and s200[t] > s200[t - 20]:
                last5 = range(t - 4, t + 1)
                touch5 = any(bl[i] is not None and l[i] <= bl[i] for i in last5)
                near5 = any(atr[i] is not None and ((s20[i] is not None and abs(l[i] - s20[i]) <= .5 * atr[i]) or (s50[i] is not None and abs(l[i] - s50[i]) <= .5 * atr[i])) for i in last5)
                dd20 = 1 - px / max(h[t - 19:t + 1])
                rmin5 = min(x for x in rs[t - 4:t + 1] if x is not None)
                bounce = rs[t] > rs[t - 1] and rs[t] - rmin5 >= 3
                conf = px > h[t - 1] or (c[t - 1] <= s5[t - 1] and px > s5[t])
                flags["p2"] = (touch5 or near5 or 0.04 <= dd20 <= 0.12) and rmin5 <= 50 and bounce and conf     # V2.0
        # ---------- 组合 3:超跌反转(技术部分) ----------
        if ok_cap10 and rs[t] is not None:
            hi52, lo52 = max(h[t - 251:t + 1]), min(l[t - 251:t + 1])
            avg20x = (prev_[t] - prev_[t - 20]) / 20
            volr5 = (prev_[t + 1] - prev_[t - 4]) / 5 / ((prev_[t - 4] - prev_[t - 29]) / 25) if prev_[t - 4] - prev_[t - 29] > 0 else 0
            pct25 = (px - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else 50
            # V1.0:MACD 底背离(波段窗口 5,第二个低点在最近 15 日内)+ 价格分位 ≤ 25% + RSI ≤ 40 + 5 日量比 ≥ 1.3
            if rs[t] <= 40 and pct25 <= 25 and volr5 >= 1.3:
                flags["r1"] = div_signal(c, mc, piv5, t, 5, 90, 10, 15)
            # V2.0:区间位置/回撤 + RSI 衰竭后回升 + 确认(路径 A 或 B)
            rpos = (px - lo52) / (hi52 - lo52) if hi52 > lo52 else None
            rmin15 = min(x for x in rs[t - 14:t + 1] if x is not None)
            if rpos is not None and (rpos <= 0.35 or 1 - px / hi52 >= 0.25) and rmin15 <= 35 and rs[t] >= 40 and rs[t] > rs[t - 1] and avg20x > 0:
                vr = v[t] / avg20x
                above2 = px > s20[t] and c[t - 1] > s20[t - 1]
                path_a = div_signal(c, mc, piv3, t, 3, 90, 10, 20) and (px > max(h[t - 5:t]) or above2) and vr >= 1.2
                path_b = rmin15 <= 30 and px > max(h[t - 10:t]) and above2 and vr >= 1.5
                flags["r2"] = path_a or path_b
        for k, ok in flags.items():
            if ok and t >= nxt[k]:
                ev[k].append(make(t, k))
                nxt[k] = t + COOLDOWN
    return ev, base


# =============================== 统计 ===============================
def regime_map(spy):
    c = spy["c"]
    s50, s200 = S.sma(c, 50), S.sma(c, 200)
    out = {}
    for i, d in enumerate(spy["d"]):
        if i < 220 or s200[i] is None:
            continue
        out[d] = "BULL" if c[i] > s200[i] and s50[i] > s50[i - 20] else ("BEAR" if c[i] < s200[i] and s200[i] < s200[i - 20] else "NEUTRAL")
    return out


def trade_ret(ev, hh):
    p = ev["path"]
    if len(p) < hh + 1:
        return None
    r = 1.0
    for x in p[:hh + 1]:
        r *= 1 + x
    return r * (1 - COST_SIDE) / (1 + COST_SIDE) - 1           # 入场多付 0.1%,出场少收 0.1%


def mae(ev, hh):
    p, r, worst = ev["path"], 1.0, 0.0
    for x in p[:hh + 1]:
        r *= 1 + x
        worst = min(worst, r - 1)
    return worst


def portfolio_mdd(events, hh, dates_index):
    """等权组合:每天持仓的所有交易的日收益取平均,权益曲线的最大回撤。"""
    day = {}
    for e in events:
        if len(e["path"]) < hh + 1:
            continue
        i0 = dates_index.get(e["date"])
        if i0 is None:
            continue
        for k, x in enumerate(e["path"][:hh + 1]):
            r = x - (COST_SIDE if k == 0 else 0) - (COST_SIDE if k == hh else 0)
            day.setdefault(i0 + 1 + k, []).append(r)
    eq, peak, mdd = 1.0, 1.0, 0.0
    for k in sorted(day):
        eq *= 1 + sum(day[k]) / len(day[k])
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    return mdd


def stats(events, hh, base, dates_index):
    rs, ex = [], []
    for e in events:
        r = trade_ret(e, hh)
        if r is not None and f"spy{hh}" in e:
            rs.append(r)
            ex.append(r - e[f"spy{hh}"])
    if not rs:
        return None
    wins, losses = [x for x in rs if x > 0], [-x for x in rs if x < 0]
    sd = statistics.pstdev(rs) if len(rs) > 1 else 0
    b = base[hh]
    return {"n": len(rs), "win": len(wins) / len(rs), "mean": statistics.mean(rs), "median": statistics.median(rs), "excess_spy": statistics.mean(ex),
            "excess_base": statistics.mean(rs) - (b[0] / b[2] if b[2] else 0), "pf": (sum(wins) / sum(losses)) if losses else None,
            "sharpe": (statistics.mean(rs) / sd * math.sqrt(252 / hh)) if sd else None, "mdd": portfolio_mdd(events, hh, dates_index),
            "mae_avg": statistics.mean(mae(e, hh) for e in events if len(e["path"]) >= hh + 1), "worst": min(rs)}


NAMES = {"g1": ("激进成长", "V1.0"), "g2": ("激进成长", "V2.0"), "p1": ("强势回调", "V1.0"), "p2": ("强势回调", "V2.0"), "r1": ("超跌反转", "V1.0"), "r2": ("超跌反转", "V2.0")}


def run(limit=0, refresh=False):
    t0 = time.time()
    D = load_data(limit, refresh)
    spy, bars, caps = D["spy"], D["bars"], D["caps"]
    if limit:
        bars = dict(list(bars.items())[:limit])
    spy_idx = {d: i for i, d in enumerate(spy["d"])}
    reg = regime_map(spy)
    print(f"扫描 {len(bars)} 只股票,{spy['d'][0]} 到 {spy['d'][-1]}…")
    allev = {k: [] for k in NAMES}
    base = {hh: [0.0, 0.0, 0] for hh in HORIZONS}
    for j, (sym, B) in enumerate(bars.items()):
        ev, bs = scan(sym, B, spy, spy_idx, reg, caps.get(sym, 0))
        for k in allev:
            allev[k] += ev[k]
        for hh in HORIZONS:
            for z in range(3):
                base[hh][z] += bs[hh][z]
        if (j + 1) % 200 == 0:
            print(f"  已扫描 {j + 1}/{len(bars)},用时 {time.time() - t0:.0f} 秒")
    dates_index = {d: i for i, d in enumerate(spy["d"])}
    res = {"asof": datetime.date.today().isoformat(), "period": [spy["d"][0], spy["d"][-1]], "stocks": len(bars), "cost_per_side": COST_SIDE, "cooldown": COOLDOWN,
           "baseline": {str(hh): {"mean": base[hh][0] / base[hh][2], "spy": base[hh][1] / base[hh][2], "n": base[hh][2]} for hh in HORIZONS if base[hh][2]}, "tests": {}}
    for k, (nm, ver) in NAMES.items():
        evs = allev[k]
        r = {"events": len(evs), "all": {}, "regime": {}, "in_sample": {}, "out_sample": {}, "by_year": {}}
        for hh in HORIZONS:
            r["all"][str(hh)] = stats(evs, hh, base, dates_index)
            for rg in ("BULL", "NEUTRAL", "BEAR"):
                r["regime"].setdefault(rg, {})[str(hh)] = stats([e for e in evs if e["reg"] == rg], hh, base, dates_index)
            r["in_sample"][str(hh)] = stats([e for e in evs if e["date"] < SPLIT], hh, base, dates_index)
            r["out_sample"][str(hh)] = stats([e for e in evs if e["date"] >= SPLIT], hh, base, dates_index)
        for y in sorted({e["date"][:4] for e in evs}):
            r["by_year"][y] = stats([e for e in evs if e["date"][:4] == y], 60, base, dates_index)
        res["tests"][k] = {"name": nm, "version": ver, **r}
    out = os.path.join(HERE, "backtest_results.json")
    json.dump(res, open(out, "w"), ensure_ascii=False)
    print(f"完成,用时 {time.time() - t0:.0f} 秒 → {out}")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    run(a.limit, a.refresh)
