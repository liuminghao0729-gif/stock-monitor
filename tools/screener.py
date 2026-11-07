"""每日选股:三种组合,每种取 5 只。只用 Python 自带库,数据来自 Yahoo,不需要任何 Key。
用法:python3 tools/screener.py            (全量,约几分钟)
      python3 tools/screener.py --limit 150  (只扫前 150 只,用来试跑)
结果写入 public/screener.json,网页的"股票推荐"页读取它。
说明:仅为条件筛选,不构成投资建议。技术信号没有被证明有预测能力。
"""
import json, os, sys, time, math, datetime, argparse, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))
import _core as core

# ---------- 筛选范围(用户设定) ----------
MIN_CAP = 5e9            # 市值 ≥ 50 亿美元
MIN_DOLLAR_VOL = 10e6    # 日均成交额 ≥ 1000 万美元
MIN_PRICE = 10.0         # 股价 ≥ 10 美元
PICKS = 5                # 每种组合每天 5 只

# ---------- 指标(纯 Python) ----------
def sma(v, n):
    return [None if i < n - 1 else sum(v[i - n + 1:i + 1]) / n for i in range(len(v))]

def ema(v, n):
    k, out, e = 2 / (n + 1), [], None
    for x in v:
        e = x if e is None else x * k + e * (1 - k)
        out.append(e)
    return out

def rsi(c, n=14):
    out = [None] * len(c)
    if len(c) <= n:
        return out
    g = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
    l = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    ag, al = sum(g[:n]) / n, sum(l[:n]) / n
    out[n] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n, len(g)):
        ag, al = (ag * (n - 1) + g[i]) / n, (al * (n - 1) + l[i]) / n
        out[i + 1] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    return out

def macd(c):
    f, s = ema(c, 12), ema(c, 26)
    m = [a - b for a, b in zip(f, s)]
    return m, ema(m, 9)

def boll(c, n=20, k=2.0):
    mid, lo, up = sma(c, n), [], []
    for i in range(len(c)):
        if mid[i] is None:
            lo.append(None); up.append(None); continue
        w = c[i - n + 1:i + 1]
        sd = math.sqrt(sum((x - mid[i]) ** 2 for x in w) / n)
        lo.append(mid[i] - k * sd); up.append(mid[i] + k * sd)
    return mid, lo, up

def adx(h, l, c, n=14):
    if len(c) < n * 2 + 1:
        return None
    tr, pdm, mdm = [], [], []
    for i in range(1, len(c)):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(up if up > dn and up > 0 else 0)
        mdm.append(dn if dn > up and dn > 0 else 0)
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    atr, p, m = sum(tr[:n]), sum(pdm[:n]), sum(mdm[:n])
    dx = []
    for i in range(n, len(tr) + 1):
        if i > n:
            atr, p, m = atr - atr / n + tr[i - 1], p - p / n + pdm[i - 1], m - m / n + mdm[i - 1]
        pi, mi = (100 * p / atr, 100 * m / atr) if atr else (0, 0)
        dx.append(100 * abs(pi - mi) / (pi + mi) if pi + mi else 0)
    if len(dx) < n:
        return None
    a = sum(dx[:n]) / n
    for x in dx[n:]:
        a = (a * (n - 1) + x) / n
    return a

def trend_fit(c, n=60):
    """最近 n 根收盘价的线性回归:返回 (每日斜率占价格的比例, R²)。"""
    y = c[-n:]
    if len(y) < n:
        return None, None
    x = list(range(n))
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return None, None
    return sxy / sxx / my, (sxy * sxy) / (sxx * syy)

def swing_lows(c, w=5):
    return [i for i in range(w, len(c) - w) if c[i] == min(c[i - w:i + w + 1])]

# ---------- 数据 ----------
def bars(sym):
    r = core._chart(sym, "2y", "1d", 3600)
    q = r["indicators"]["quote"][0]
    rows = [(q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i] or 0) for i in range(len(r["timestamp"]))
            if None not in (q["high"][i], q["low"][i], q["close"][i])]
    return [x[1] for x in rows], [x[2] for x in rows], [x[3] for x in rows], [x[4] for x in rows]

def universe():
    out, seen = [], set()
    core._yh_open("https://query2.finance.yahoo.com/v10/finance/quoteSummary/AAPL?modules=price")   # 取得 crumb
    for off in range(0, 1500, 250):
        body = {"offset": off, "size": 250, "sortField": "intradaymarketcap", "sortType": "DESC", "quoteType": "EQUITY", "topOperator": "AND",
                "query": {"operator": "AND", "operands": [{"operator": "eq", "operands": ["region", "us"]},
                                                         {"operator": "gt", "operands": ["intradaymarketcap", MIN_CAP]},
                                                         {"operator": "or", "operands": [{"operator": "eq", "operands": ["exchange", "NMS"]}, {"operator": "eq", "operands": ["exchange", "NYQ"]}]}]},
                "userId": "", "userIdType": "guid"}
        req = urllib.request.Request("https://query1.finance.yahoo.com/v1/finance/screener?crumb=" + urllib.parse.quote(core._yh["crumb"]) + "&lang=en-US&region=US",
                                     data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
        try:
            res = json.load(core._yh["op"].open(req, timeout=25))["finance"]["result"][0]
        except Exception as e:
            print("  范围查询失败:", type(e).__name__, str(e)[:60]); break
        for q in res.get("quotes", []):
            s = q.get("symbol")
            if not s or s in seen or "-" in s and False:
                continue
            seen.add(s)
            px, vol = q.get("regularMarketPrice") or 0, q.get("averageDailyVolume3Month") or 0
            if px >= MIN_PRICE and px * vol >= MIN_DOLLAR_VOL:
                out.append({"sym": s, "name": q.get("shortName") or q.get("longName") or s, "cap": q.get("marketCap"), "price": px})
        if len(res.get("quotes", [])) < 250:
            break
    return out

def fundamentals(sym):
    for attempt in range(3):
        try:
            d = core._yh_open(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(sym)}?modules=financialData,defaultKeyStatistics,summaryDetail,assetProfile")
            r = d["quoteSummary"]["result"][0]
            g = lambda blk, k: ((r.get(blk) or {}).get(k) or {}).get("raw") if isinstance((r.get(blk) or {}).get(k), dict) else None
            return {"revG": g("financialData", "revenueGrowth"), "earnG": g("financialData", "earningsGrowth"), "gm": g("financialData", "grossMargins"),
                    "roe": g("financialData", "returnOnEquity"), "roa": g("financialData", "returnOnAssets"), "ocf": g("financialData", "operatingCashflow"),
                    "fpe": g("defaultKeyStatistics", "forwardPE"), "peg": g("defaultKeyStatistics", "pegRatio"), "pb": g("defaultKeyStatistics", "priceToBook"),
                    "tpe": g("summaryDetail", "trailingPE"), "sector": (r.get("assetProfile") or {}).get("sector")}
        except Exception as e:
            if "404" in str(e):
                return None
            time.sleep(1 + attempt)
    return None

# ---------- 技术信号 ----------
def technicals(h, l, c, v, spy6m):
    n = len(c)
    if n < 230:
        return None
    ma20, ma50, ma200 = sma(c, 20), sma(c, 50), sma(c, 200)
    r = rsi(c)
    m, sg = macd(c)
    mid, lo, up = boll(c)
    a = adx(h, l, c)
    slope, r2 = trend_fit(c)
    px, hi52, lo52 = c[-1], max(c[-250:]), min(c[-250:])
    pctile = (px - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else 50
    ret6m = px / c[-126] - 1 if n > 126 else 0
    day = px / c[-2] - 1
    # MACD 底背离:最近两个波段低点,价格创新低但 MACD 没创新低,且第二个低点在最近 15 根内
    sl = [i for i in swing_lows(c[:-1], 5) if i >= n - 1 - 90]
    div = False
    if len(sl) >= 2 and sl[-1] - sl[-2] >= 10 and sl[-1] >= n - 1 - 15:
        div = c[sl[-1]] < c[sl[-2]] and m[sl[-1]] > m[sl[-2]]
    vol_ratio = (sum(v[-5:]) / 5) / (sum(v[-30:-5]) / 25) if sum(v[-30:-5]) else 0
    touch = any(lo[i] is not None and l[i] <= lo[i] * 1.005 for i in range(n - 3, n))
    return {"px": px, "ma20": ma20[-1], "ma50": ma50[-1], "ma200": ma200[-1], "rsi": r[-1], "adx": a, "slope": slope, "r2": r2, "pctile": pctile,
            "hi52": hi52, "ret6m": ret6m, "rel6m": ret6m - spy6m, "day": day, "div": div, "volr": vol_ratio, "touch": touch,
            "bandgap": (px / lo[-1] - 1) if lo[-1] else None}

# ---------- 三种组合 ----------
def growth_checks(f):
    """A4 成长:营收同比 ≥ 20%;净利润同比 ≥ 15% 或营收 ≥ 30%(允许暂时亏损);毛利率 ≥ 40%(科技)/ 30%(其他)。"""
    if not f:
        return [("营收同比 ≥ 20%", None), ("利润同比 ≥ 15% 或营收 ≥ 30%", None), ("毛利率达标", None)]
    tech = f.get("sector") == "Technology"
    rg, eg, gm = f.get("revG"), f.get("earnG"), f.get("gm")
    return [("营收同比 ≥ 20%", None if rg is None else rg >= 0.20),
            ("净利润同比 ≥ 15% 或营收 ≥ 30%", None if rg is None else ((eg or -1) >= 0.15 or rg >= 0.30)),
            (f"毛利率 ≥ {40 if tech else 30}%", None if gm is None else gm >= (0.40 if tech else 0.30))]

def evaluate(t, f):
    """返回三个组合各自的 (条件列表, 分数)。条件为 (文字, True/False/None);None 表示没有数据。"""
    out = {}
    gc = growth_checks(f)
    # 1 激进成长 = A4 + B2(动量 B7 加分)
    tc = [("均线多头 20>50>200 且价格在 20 日线上", t["ma20"] > t["ma50"] > t["ma200"] and t["px"] > t["ma20"]),
          ("60 日趋势拟合度 R² ≥ 0.5 且向上", t["r2"] is not None and t["r2"] >= 0.5 and t["slope"] > 0),
          ("ADX ≥ 20", t["adx"] is not None and t["adx"] >= 20)]
    mom = (t["px"] >= t["hi52"] * 0.90) + (t["ret6m"] >= 0.30) + (t["rel6m"] > 0)
    sc = (f"营收增速 {f['revG'] * 100:.0f}%" if f and f.get("revG") is not None else "")
    score = sum(25 for _, ok in gc if ok) + sum(20 for _, ok in tc if ok) + mom * 5 + min(max((t["r2"] or 0) * 10, 0), 10)
    out["growth"] = (gc + tc, score, {"动量加分": f"{mom}/3(距52周高点≤10%、近6个月涨≥30%、强于大盘)"})
    # 2 强势回调 = A4 + B3
    bc = [("价格在 200 日线上方(仍是上升趋势)", t["px"] > t["ma200"]),
          ("触及布林带下轨(近 3 天)", t["touch"]),
          ("RSI ≤ 40", t["rsi"] is not None and t["rsi"] <= 40),
          ("当日涨幅 < 9%", t["day"] < 0.09)]
    score = sum(25 for _, ok in gc if ok) + sum(25 for _, ok in bc if ok) + max(0, 40 - (t["rsi"] or 40))
    out["pullback"] = (gc + bc, score, {})
    # 3 超跌反转 = B1 + B5 + 营收同比 > 0
    rc = [("MACD 底背离", t["div"]),
          ("近 1 年价格分位 ≤ 25%", t["pctile"] <= 25),
          ("RSI ≤ 40", t["rsi"] is not None and t["rsi"] <= 40),
          ("近 5 日成交量 ≥ 前 25 日均量 1.3 倍", t["volr"] >= 1.3),
          ("营收同比 > 0", None if not f or f.get("revG") is None else f["revG"] > 0)]
    score = sum(25 for _, ok in rc if ok) + max(0, 40 - (t["rsi"] or 40)) + max(0, 25 - t["pctile"])
    out["reversal"] = (rc, score, {})
    return out

PRESETS = [("growth", "激进成长", "高增长公司 + 趋势向上,偏顺势", True),
           ("pullback", "强势回调", "高增长公司在上升趋势中的回调", True),
           ("reversal", "超跌反转", "可能见底的超跌股,风险最高", False)]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=0); ap.add_argument("--out", default=os.path.join(ROOT, "public", "screener.json"))
    a = ap.parse_args()
    t0 = time.time()
    print("1/4 获取筛选范围…")
    uni = universe()
    if a.limit:
        uni = uni[:a.limit]
    print(f"    符合范围的股票:{len(uni)} 只")
    spy = bars("SPY"); spy6m = spy[2][-1] / spy[2][-126] - 1
    print("2/4 计算技术指标…")
    def tech(u):
        try:
            h, l, c, v = bars(u["sym"])
            return u, technicals(h, l, c, v, spy6m)
        except Exception:
            return u, None
    with ThreadPoolExecutor(8) as ex:
        scanned = [x for x in ex.map(tech, uni) if x[1]]
    print(f"    成功 {len(scanned)} 只,用时 {time.time() - t0:.0f} 秒")
    # 只对"技术面有机会进任何一组"的股票取基本面,减少请求
    def gate(t):
        return (t["ma20"] > t["ma50"] > t["ma200"]) or t["px"] > t["ma200"] and (t["touch"] or (t["rsi"] or 99) <= 45) or t["pctile"] <= 30 or t["div"]
    cand = [x for x in scanned if gate(x[1])]
    print(f"3/4 获取基本面(技术面初筛后 {len(cand)} 只)…")
    with ThreadPoolExecutor(6) as ex:
        funds = list(ex.map(lambda x: fundamentals(x[0]["sym"]), cand))
    print("4/4 评分排名…")
    res = []
    for pid, name, desc, _ in PRESETS:
        rows = []
        for (u, t), f in zip(cand, funds):
            conds, score, extra = evaluate(t, f)[pid]
            if pid != "reversal" and not f:
                continue                                  # 成长类必须有基本面数据
            ok_all = all(ok for _, ok in conds if ok is not None) and all(ok is not None for _, ok in conds[:3] if pid != "reversal")
            hits = [c for c, ok in conds if ok]; miss = [c for c, ok in conds if ok is False]; nodata = [c for c, ok in conds if ok is None]
            rows.append({"sym": u["sym"], "name": u["name"], "price": round(t["px"], 2), "cap": u["cap"], "day": round(t["day"] * 100, 2),
                         "sector": (f or {}).get("sector"), "strict": bool(ok_all), "score": round(score, 1), "hits": hits, "misses": miss, "nodata": nodata,
                         "m": {"revG": (f or {}).get("revG"), "earnG": (f or {}).get("earnG"), "gm": (f or {}).get("gm"), "roe": (f or {}).get("roe"),
                               "rsi": round(t["rsi"], 1) if t["rsi"] is not None else None, "adx": round(t["adx"], 1) if t["adx"] else None,
                               "pctile": round(t["pctile"]), "ret6m": round(t["ret6m"] * 100, 1), "volr": round(t["volr"], 2),
                               "fpe": (f or {}).get("fpe"), "peg": (f or {}).get("peg"), "pb": (f or {}).get("pb"),
                               "roeOk": bool(f and f.get("roe") is not None and f["roe"] >= 0.10 and (f.get("roa") or 0) >= 0.03),
                               "valOk": bool(f and f.get("tpe") is not None and f["tpe"] <= 25 and (f.get("pb") or 99) <= 3 and (f.get("peg") or 99) <= 1.5)}})
        rows.sort(key=lambda r: (r["strict"], r["score"]), reverse=True)
        res.append({"id": pid, "name": name, "desc": desc, "strictCount": sum(r["strict"] for r in rows), "picks": rows[:PICKS]})
    out = {"asof": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "universe": len(uni), "scanned": len(scanned),
           "rules": {"cap": "市值 ≥ 50 亿美元", "vol": "日均成交额 ≥ 1000 万美元", "price": "股价 ≥ 10 美元"}, "presets": res}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(out, fh, ensure_ascii=False)
    for p in res:
        print(f"  {p['name']}:完全符合 {p['strictCount']} 只;展示 {[(r['sym'], r['strict']) for r in p['picks']]}")
    print(f"完成,用时 {time.time() - t0:.0f} 秒 → {a.out}")

if __name__ == "__main__":
    main()
