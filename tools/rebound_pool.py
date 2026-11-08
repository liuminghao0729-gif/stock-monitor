"""短线「反弹」候选池:把三种思路放进同一个池子,统一特征、统一回测。
三种思路(宽松基础条件,之后在分析里收紧):
  R 超跌反转:近 15 天 RSI 最低 ≤ 40,今天 RSI ≥ 38 且回升,且深度(52 周区间位置 ≤ 50% 或回撤 ≥ 15%)。(旧「超跌反转」的思路)
  P 企稳放量形态:前面大跌 → 最低点后不再创新低 → 一波放量反弹 → 缩量回调且不破前低 → 今天放量再涨。(你描述的形态)
  B 趋势内回调到下沿:长期上升趋势(价>200 日线、50 日线>200 日线)中,近 5 天触及布林下轨/贴近均线/回撤 4–12%,RSI 回升。(旧「强势回调」的思路)
每个事件记录约 50 个特征(价格位置、RSI、布林带、MACD、成交量、波动、beta、形态等)和之后 1、3、5、10、30、60、120 天的收益及同期标普 500 收益。
入场 T+1 开盘价;同一只股票 10 天内不重复;只保留当时估计市值(今天市值 × 当时价/今天价)≥ 50 亿、价格 ≥ 10、成交额 ≥ 2000 万的。
偏差:幸存者偏差(退市股不在里面),对「买下跌的股票」影响最大。
运行:python3 tools/rebound_pool.py build"""
import gzip, math, os, pickle, sys, time
from array import array

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "api")]
import screener_v2 as S
import backtest as BT
import backtest_tune as T

HS = (1, 3, 5, 10, 30, 60, 120)
PATHLEN = 61
OUT = os.path.join(HERE, ".cache", "rebound_pool.pkl.gz")
FEATS = ["rsi", "rmin5", "rmin15", "bounce", "ret1", "ret3", "ret5", "ret21", "ret63", "dd20", "dd52", "dd120", "rpos", "dist20", "dist50", "dist200", "pctb", "bb_low", "macd_hn",
         "macd_x3", "cons_down", "clv", "gap", "rng", "atrp", "vol60", "beta", "dvol", "vr20", "updn20", "near_high", "slope50", "adx_dir", "touch5", "near5", "uptrend",
         "above5", "above20", "above50", "above200", "baseR", "baseP", "baseB",
         "dsl", "hl", "retrace", "rally", "shrink", "resume", "upvdn", "dur", "px_vs_h1", "vol_dry"]
nan = float("nan")


def build():
    t0 = time.time()
    D = pickle.load(gzip.open(T.CACHE_BARS, "rb"))
    spy, bars, caps = D["spy"], D["bars"], D["caps"]
    sidx = {d: i for i, d in enumerate(spy["d"])}
    cols = {f: array("f") for f in FEATS}
    R = {h: array("f") for h in HS}
    SP = {h: array("f") for h in HS}
    path = array("f")
    meta_date, meta_sym, est_cap = [], [], array("f")
    n_events = 0
    for si, (sym, B) in enumerate(bars.items()):
        cap = caps.get(sym, 0)
        if cap < 5e9:
            continue
        c, h, l, v, a, ao, ds = B["c"], B["h"], B["l"], B["v"], B["a"], B["ao"], B["d"]
        n = len(c)
        s5, s20, s50, s200 = S.sma(c, 5), S.sma(c, 20), S.sma(c, 50), S.sma(c, 200)
        rs = S.rsi_wilder(c, 14)
        atr, adx, pdi, mdi = BT.wilder_series(h, l, c)
        ml = S.macd_line(c)
        sg = S.ema(ml, 9)
        bl = BT.roll_boll_lower(c)
        cdn = [0] * n
        for i in range(1, n):
            cdn[i] = cdn[i - 1] + 1 if c[i] < c[i - 1] else 0
        sa, last = [], None
        for d in ds:
            last = spy["a"][sidx[d]] if d in sidx else last
            sa.append(last)
        r = [0.0] + [a[i] / a[i - 1] - 1 for i in range(1, n)]
        sr = [0.0] + [sa[i] / sa[i - 1] - 1 if sa[i - 1] else 0.0 for i in range(1, n)]
        pr, ps, prs, pss, pr2, pcv, pup, pdn = ([0.0] for _ in range(8))
        for i in range(n):
            pr.append(pr[-1] + r[i]); ps.append(ps[-1] + sr[i]); prs.append(prs[-1] + r[i] * sr[i]); pss.append(pss[-1] + sr[i] * sr[i]); pr2.append(pr2[-1] + r[i] * r[i])
            pcv.append(pcv[-1] + c[i] * v[i])
            up = v[i] if i > 0 and c[i] >= c[i - 1] else 0.0
            pup.append(pup[-1] + up); pdn.append(pdn[-1] + (v[i] - up))
        nxt = 0
        for t in range(260, n - 2):
            if t < nxt or rs[t] is None or atr[t] is None or adx[t] is None or s200[t] is None or sa[t - 126] is None:
                continue
            px = c[t]
            if px < 10:
                continue
            rmin15 = min(x for x in rs[t - 14:t + 1] if x is not None)
            rmin5 = min(x for x in rs[t - 4:t + 1] if x is not None)
            rising = rs[t] > rs[t - 1]
            # ---- 基础条件 B ----
            baseB = False
            uptrend = px > s200[t] and s50[t] > s200[t] and s200[t] > s200[t - 20]
            last5 = range(t - 4, t + 1)
            touch5 = any(bl[i] is not None and l[i] <= bl[i] for i in last5)
            near5 = any(atr[i] is not None and ((s20[i] is not None and abs(l[i] - s20[i]) <= .5 * atr[i]) or (s50[i] is not None and abs(l[i] - s50[i]) <= .5 * atr[i])) for i in last5)
            dd20 = 1 - px / max(h[t - 19:t + 1])
            if uptrend and rmin5 <= 55 and rising and (touch5 or near5 or 0.04 <= dd20 <= 0.12):
                baseB = True
            # ---- 基础条件 R ----
            hi252, lo252 = max(h[t - 251:t + 1]), min(l[t - 251:t + 1])
            rpos = (px - lo252) / (hi252 - lo252) if hi252 > lo252 else 0.5
            dd52 = 1 - px / hi252
            baseR = rs[t] >= 38 and rising and rmin15 <= 40 and (rpos <= 0.5 or dd52 >= 0.15)
            # ---- 基础条件 P(形态,宽松)----
            baseP = False
            st = {"dsl": nan, "hl": nan, "retrace": nan, "rally": nan, "shrink": nan, "resume": nan, "upvdn": nan, "dur": nan, "px_vs_h1": nan}
            hi120 = max(h[t - 119:t + 1])
            dd120 = 1 - px / hi120
            if c[t] > c[t - 1] and dd120 >= 0.15:
                seg = c[t - 39:t + 1]
                L1 = min(seg)
                i1 = t - 39 + max(i for i, x in enumerate(seg) if x == L1)
                mid = c[i1 + 1:t]
                if t - i1 >= 4 and len(mid) >= 3:
                    H1 = max(mid)
                    iH = i1 + 1 + max(i for i, x in enumerate(mid) if x == H1)
                    if iH - i1 >= 2 and t - 1 - iH >= 1:
                        L2 = min(c[iH:t])
                        vup = sum(v[i1 + 1:iH + 1]) / (iH - i1)
                        vpb = sum(v[iH + 1:t]) / (t - 1 - iH)
                        if L2 > L1 and H1 > L1 and vup > 0 and vpb > 0 and 1 - L1 / hi120 >= 0.20 and vpb / vup <= 1.2 and v[t] / vpb >= 0.8:
                            baseP = True
                            dn = sum(v[max(0, i1 - 9):i1 + 1]) / min(10, i1 + 1)
                            ihi = t - 119 + max(i for i, x in enumerate(h[t - 119:t + 1]) if x == hi120)
                            st = {"dsl": t - i1, "hl": L2 / L1 - 1, "retrace": (H1 - L2) / (H1 - L1), "rally": H1 / L1 - 1, "shrink": vpb / vup, "resume": v[t] / vpb,
                                  "upvdn": vup / dn if dn > 0 else 1.0, "dur": i1 - ihi, "px_vs_h1": px / H1 - 1}
            if not (baseR or baseB or baseP):
                continue
            adv = (pcv[t + 1] - pcv[t - 59]) / 60
            ecap = cap * px / c[-1]
            if adv < 20e6 or ecap < 5e9 or ds[t + 1] not in sidx or ds[t] not in sidx:
                continue
            i1s = sidx[ds[t + 1]]
            if i1s + 1 >= len(spy["a"]):
                continue
            m = 126
            mr, ms = (pr[t + 1] - pr[t + 1 - m]) / m, (ps[t + 1] - ps[t + 1 - m]) / m
            cov = (prs[t + 1] - prs[t + 1 - m]) / m - mr * ms
            var = (pss[t + 1] - pss[t + 1 - m]) / m - ms * ms
            avg20 = (pup[t] + pdn[t] - pup[t - 20] - pdn[t - 20]) / 20
            ups, dns = pup[t + 1] - pup[t - 19], pdn[t + 1] - pdn[t - 19]
            up_b = 2 * s20[t] - bl[t] if bl[t] is not None else None
            xs = 0
            for i in (t - 2, t - 1, t):
                if ml[i - 1] <= sg[i - 1] and ml[i] > sg[i]:
                    xs = 1
                elif ml[i - 1] >= sg[i - 1] and ml[i] < sg[i]:
                    xs = -1
            f = {"rsi": rs[t], "rmin5": rmin5, "rmin15": rmin15, "bounce": rs[t] - rmin5, "ret1": c[t] / c[t - 1] - 1, "ret3": c[t] / c[t - 3] - 1, "ret5": c[t] / c[t - 5] - 1,
                 "ret21": c[t] / c[t - 21] - 1, "ret63": a[t] / a[t - 63] - 1, "dd20": dd20, "dd52": dd52, "dd120": dd120, "rpos": rpos, "dist20": px / s20[t] - 1,
                 "dist50": px / s50[t] - 1, "dist200": px / s200[t] - 1, "pctb": (px - bl[t]) / (up_b - bl[t]) if up_b and bl[t] is not None and up_b > bl[t] else 0.5,
                 "bb_low": px / bl[t] - 1 if bl[t] else 0.0, "macd_hn": (ml[t] - sg[t]) / px * 100, "macd_x3": xs, "cons_down": cdn[t],
                 "clv": (px - l[t]) / (h[t] - l[t]) if h[t] > l[t] else 0.5, "gap": ao[t] / a[t - 1] - 1, "rng": (h[t] - l[t]) / px, "atrp": atr[t] / px,
                 "vol60": math.sqrt(max((pr2[t + 1] - pr2[t - 59]) / 60 - ((pr[t + 1] - pr[t - 59]) / 60) ** 2, 0)) * math.sqrt(252), "beta": cov / var if var > 0 else 1.0,
                 "dvol": math.log(adv), "vr20": v[t] / avg20 if avg20 > 0 else 1.0, "updn20": ups / (ups + dns) if ups + dns > 0 else 0.5, "near_high": px / hi252,
                 "slope50": s50[t] / s50[t - 20] - 1, "adx_dir": adx[t] * (1 if pdi[t] > mdi[t] else -1), "touch5": float(touch5), "near5": float(near5), "uptrend": float(uptrend),
                 "above5": float(px > s5[t]), "above20": float(px > s20[t]), "above50": float(px > s50[t]), "above200": float(px > s200[t]),
                 "baseR": float(baseR), "baseP": float(baseP), "baseB": float(baseB),
                 "vol_dry": (sum(v[t - 4:t + 1]) / 5) / (sum(v[t - 59:t + 1]) / 60) if sum(v[t - 59:t + 1]) > 0 else 1.0}
            f.update(st)
            ok = False
            rr = {}
            for hh in HS:
                x = t + 1 + hh
                if x < n and ds[x] in sidx and i1s + hh < len(spy["a"]):
                    rr[hh] = (a[x] / ao[t + 1] - 1, spy["a"][i1s + hh] / spy["ao"][i1s] - 1)
                    ok = True
                else:
                    rr[hh] = (nan, nan)
            if not ok:
                continue
            for k in FEATS:
                cols[k].append(f[k])
            for hh in HS:
                R[hh].append(rr[hh][0]); SP[hh].append(rr[hh][1])
            e = t + 1
            pth = [(a[k] / a[k - 1] - 1) if k > e else (a[k] / ao[e] - 1) for k in range(e, min(n, e + PATHLEN))]
            pth += [nan] * (PATHLEN - len(pth))
            path.extend(pth)
            meta_date.append(ds[t]); meta_sym.append(sym); est_cap.append(ecap)
            n_events += 1
            nxt = t + 10
        if (si + 1) % 200 == 0:
            print(f"  {si + 1} 只,事件 {n_events:,},用时 {time.time() - t0:.0f} 秒", flush=True)
    pickle.dump({"cols": cols, "R": R, "SP": SP, "path": path, "date": meta_date, "sym": meta_sym, "ecap": est_cap, "n": n_events}, gzip.open(OUT, "wb"))
    print(f"完成:事件 {n_events:,},用时 {time.time() - t0:.0f} 秒")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build()
    else:
        print(__doc__)
