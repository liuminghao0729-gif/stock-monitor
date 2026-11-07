"""每日选股 V2.0:五层结构(股票池 → 财务安全 → 策略条件 → 信号确认 → 策略评分)。
只用 Python 自带库。数据:Yahoo(行情、季度财报、估值);Finnhub(可选,只补充 TTM 营收同比,需要 FINNHUB_KEY)。
用法:python3 tools/screener_v2.py [--limit N] [--out 文件] [--no-history]
仅为条件筛选,不构成投资建议;参数没有经过回测验证。
"""
import json, os, sys, time, math, datetime, argparse, urllib.parse, urllib.request, re
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "api"), HERE]
import _core as core
from screener_config import CONFIG as CFG


# =============================== 指标(纯 Python) ===============================
def sma(v, n):
    out, s = [None] * len(v), 0.0
    for i, x in enumerate(v):
        s += x
        if i >= n:
            s -= v[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(v, n):
    k, out, e = 2 / (n + 1), [], None
    for x in v:
        e = x if e is None else x * k + e * (1 - k)
        out.append(e)
    return out


def rsi_wilder(c, n=14):
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


def macd_line(c):
    f, s = ema(c, 12), ema(c, 26)
    return [a - b for a, b in zip(f, s)]


def boll_lower(c, n=20, k=2.0):
    mid, out = sma(c, n), []
    for i in range(len(c)):
        if mid[i] is None:
            out.append(None)
            continue
        w = c[i - n + 1:i + 1]
        out.append(mid[i] - k * math.sqrt(sum((x - mid[i]) ** 2 for x in w) / n))
    return out


def wilder_atr_adx(h, l, c, n=14):
    """标准 Wilder 算法:返回 (ATR 序列, ADX, +DI, -DI)。"""
    m = len(c)
    atr = [None] * m
    if m < n * 2 + 1:
        return atr, None, None, None
    tr, pdm, mdm = [], [], []
    for i in range(1, m):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(up if up > dn and up > 0 else 0)
        mdm.append(dn if dn > up and dn > 0 else 0)
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    a, p, q = sum(tr[:n]), sum(pdm[:n]), sum(mdm[:n])
    atr[n] = a / n
    dx, pi, mi = [], 0, 0
    for i in range(n, len(tr) + 1):
        if i > n:
            a, p, q = a - a / n + tr[i - 1], p - p / n + pdm[i - 1], q - q / n + mdm[i - 1]
            atr[i] = a / n
        pi, mi = (100 * p / a, 100 * q / a) if a else (0, 0)
        dx.append(100 * abs(pi - mi) / (pi + mi) if pi + mi else 0)
    adx = sum(dx[:n]) / n
    for x in dx[n:]:
        adx = (adx * (n - 1) + x) / n
    return atr, adx, pi, mi


def trend_fit(c, n=60):
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


def macd_divergence(c, macd, cfg=CFG["reversal"]):
    """MACD 底背离(用收盘价找波段低点)。波段低点需要左右各 pivot_window 根确认:
    第 i 天的低点最早在第 i+w 天才被识别,所以只使用 i+w ≤ 最后一根 的低点,不泄露未来。
    返回 dict(found, p1, p2, signal_idx, low, strength)。"""
    n, w = len(c), cfg["pivot_window"]
    res = {"found": False}
    pivots = [i for i in range(max(w, n - 1 - cfg["pivot_lookback"]), n - w) if c[i] <= min(c[i - w:i + w + 1])]
    clean = []
    for i in pivots:                       # 平台期只保留第一个
        if not clean or i - clean[-1] > 1:
            clean.append(i)
    if len(clean) < 2:
        return res
    p2 = clean[-1]
    if p2 < n - 1 - cfg["pivot_recent"]:
        return res
    p1 = next((i for i in reversed(clean[:-1]) if p2 - i >= cfg["pivot_gap"]), None)
    if p1 is None:
        return res
    if min(c[p2 + 1:]) < c[p2]:            # 后续又创新低 → 背离被破坏
        return res
    if c[p2] < c[p1] and macd[p2] > macd[p1]:
        strength = min(abs(macd[p2] - macd[p1]) / max(abs(macd[p1]), 1e-9), 1.0)
        return {"found": True, "p1": p1, "p2": p2, "signal_idx": p2 + w, "low": c[p2], "strength": strength}
    return res


def tail_mean(v, k, skip=0):
    seg = v[len(v) - k - skip:len(v) - skip]
    return sum(seg) / len(seg) if seg else None


# =============================== 技术面汇总 ===============================
def technicals(b, spy_adj, cfg=CFG):
    """b: dict(h,l,c,adj,v)。返回当天所有技术量;历史不足(R5)返回 None。"""
    h, l, c, adj, v = b["h"], b["l"], b["c"], b["adj"], b["v"]
    n = len(c)
    if n < cfg["universe"]["min_history"]:
        return None
    ic = cfg["ind"]
    s5, s20, s50, s200 = sma(c, 5), sma(c, 20), sma(c, 50), sma(c, 200)
    rs = rsi_wilder(c, ic["rsi"])
    mc = macd_line(c)
    bl = boll_lower(c, ic["boll_n"], ic["boll_k"])
    atr, adx, pdi, mdi = wilder_atr_adx(h, l, c, ic["atr"])
    slope, r2 = trend_fit(c, ic["trend_n"])
    px = c[-1]
    hi52, lo52 = max(h[-ic["range_days"]:]), min(l[-ic["range_days"]:])
    rng = hi52 - lo52
    adv = sum(c[i] * v[i] for i in range(n - cfg["universe"]["adv_days"], n)) / cfg["universe"]["adv_days"]
    avg20x = tail_mean(v, 20, skip=1)            # 过去 20 日均量,不含当天
    rel = lambda k: (adj[-1] / adj[-1 - k]) / (spy_adj[-1] / spy_adj[-1 - k]) - 1
    tr = lambda i, w: i >= n - w
    last5 = range(n - 5, n)
    touch5 = any(bl[i] is not None and l[i] <= bl[i] for i in last5)
    near5 = any(atr[i] is not None and (s20[i] is not None and abs(l[i] - s20[i]) <= .5 * atr[i] or s50[i] is not None and abs(l[i] - s50[i]) <= .5 * atr[i]) for i in last5)
    dn_days = [v[i] for i in range(n - 10, n) if c[i] < c[i - 1]]
    up_days = [v[i] for i in range(n - 10, n) if c[i] >= c[i - 1]]
    div = macd_divergence(c, mc, cfg["reversal"])
    rsi_min = lambda k: min(x for x in rs[n - k:] if x is not None)
    T = {
        "px": px, "adv": adv, "sma5": s5[-1], "sma20": s20[-1], "sma50": s50[-1], "sma200": s200[-1], "sma5_prev": s5[-2],
        "sma50_ago": s50[-1 - cfg["growth"]["sma50_slope_days"]], "sma200_ago": s200[-1 - cfg["pullback"]["sma200_slope_days"]],
        "rsi": rs[-1], "rsi_prev": rs[-2], "rsi_min5": rsi_min(5), "rsi_min15": rsi_min(cfg["reversal"]["rsi_lookback"]),
        "adx": adx, "pdi": pdi, "mdi": mdi, "atr": atr[-1], "slope": slope, "r2": r2,
        "hi52": hi52, "lo52": lo52, "range_pos": (px - lo52) / rng if rng > 0 else None, "dd52": 1 - px / hi52,
        "near_high": px / hi52, "dd20": 1 - px / max(h[-cfg["pullback"]["dd_window"]:]), "hh20": max(h[-20:]),
        "rs63": rel(cfg["growth"]["rs_days"]), "rs126": rel(126), "rs_pre": (adj[-10] / adj[-136]) / (spy_adj[-10] / spy_adj[-136]) - 1,
        "atr_pct": atr[-1] / px if atr[-1] else None, "ext_atr": (px - s20[-1]) / atr[-1] if atr[-1] else None,
        "sma200_slope": s200[-1] / s200[-1 - cfg["pullback"]["sma200_slope_days"]] - 1,
        "vol_ratio": v[-1] / avg20x if avg20x else None,
        "dn_vol": (sum(dn_days) / len(dn_days) / avg20x) if dn_days and avg20x else None,
        "updn_vol": ((sum(up_days) / len(up_days)) / (sum(dn_days) / len(dn_days))) if up_days and dn_days and sum(dn_days) else None,
        "capit_vol": max(v[-cfg["reversal"]["rsi_lookback"]:]) / avg20x if avg20x else None,
        "touch5": touch5, "near5": near5, "pullback_low": min(l[-10:]),
        "prev_high": h[-2], "break_prev_high": px / h[-2] - 1,
        "cross_sma5": c[-2] <= s5[-2] and px > s5[-1],
        "above20_2": px > s20[-1] and c[-2] > s20[-2],
        "break5": px > max(h[-1 - cfg["reversal"]["breakout_A"]:-1]), "break10": px > max(h[-1 - cfg["reversal"]["pathB_breakout"]:-1]),
        "breakout_pct": px / max(h[-6:-1]) - 1, "div": div, "date": b["dates"][-1], "day_chg": px / c[-2] - 1,
    }
    return T


# =============================== 财报与估值 ===============================
TS_TYPES = ["quarterlyTotalRevenue", "quarterlyGrossProfit", "quarterlyOperatingIncome", "quarterlyOperatingCashFlow", "quarterlyCapitalExpenditure",
            "quarterlyFreeCashFlow", "quarterlyDilutedEPS", "quarterlyCashCashEquivalentsAndShortTermInvestments", "quarterlyTotalDebt",
            "quarterlyStockholdersEquity", "quarterlyNetIncome"]


def yget(url, tries=3):
    for k in range(tries):
        try:
            return core._yh_open(url)
        except Exception as e:
            if "404" in str(e):
                return None
            time.sleep(1.0 + k)
    return None


def fetch_raw(sym):
    ts = yget(f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{urllib.parse.quote(sym)}?type={','.join(TS_TYPES)}&period1=1451606400&period2={int(time.time()) + 86400}&merge=false")
    qs = yget(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(sym)}?modules=financialData,defaultKeyStatistics,assetProfile,earningsHistory,earningsTrend")
    series = {}
    try:
        for x in ts["timeseries"]["result"]:
            k = x["meta"]["type"][0]
            series[k] = [(i["asOfDate"], i["reportedValue"]["raw"]) for i in x.get(k, []) if i]
    except Exception:
        series = {}
    try:
        qr = qs["quoteSummary"]["result"][0]
    except Exception:
        qr = {}
    return {"series": series, "qs": qr}


def derive(raw):
    """把原始数据整理成策略要用的财务指标。任何拿不到的指标为 None(不默认通过)。"""
    S, Q = raw.get("series") or {}, raw.get("qs") or {}
    val = lambda k: [x[1] for x in S.get(k, [])]
    rev, gp, oi, ocf, cap, fcf, eps = (val(k) for k in ("quarterlyTotalRevenue", "quarterlyGrossProfit", "quarterlyOperatingIncome", "quarterlyOperatingCashFlow",
                                                      "quarterlyCapitalExpenditure", "quarterlyFreeCashFlow", "quarterlyDilutedEPS"))
    cash, debt, eq = val("quarterlyCashCashEquivalentsAndShortTermInvestments"), val("quarterlyTotalDebt"), val("quarterlyStockholdersEquity")
    at = lambda a, i: a[-1 - i] if len(a) > i else None
    ratio = lambda a, b: (a / b) if a is not None and b else None
    F = {"asof": (S.get("quarterlyTotalRevenue") or [(None,)])[-1][0] if S.get("quarterlyTotalRevenue") else None}
    r0, r4 = at(rev, 0), at(rev, 4)
    F["q_yoy"] = (r0 / r4 - 1) if r0 is not None and r4 and r4 > 0 else None
    F["ttm_rev"] = sum(rev[-4:]) if len(rev) >= 4 else None
    # 自由现金流:优先用 经营现金流 + CAPEX(Yahoo 里 CAPEX 为负数,先统一符号,避免重复相减);与 Yahoo 自带 FCF 交叉核对
    f_calc = None
    if len(ocf) >= 4 and len(cap) >= 4:
        f_calc = [o + (c if c <= 0 else -c) for o, c in zip(ocf[-4:], cap[-4:])]
    F["ttm_fcf"] = sum(fcf[-4:]) if len(fcf) >= 4 else (sum(f_calc) if f_calc else None)
    F["fcf_mismatch"] = bool(f_calc and len(fcf) >= 4 and abs(sum(f_calc) - sum(fcf[-4:])) > 0.05 * max(abs(sum(fcf[-4:])), 1))
    F["fcf_m"] = ratio(F["ttm_fcf"], F["ttm_rev"])
    m0, m4 = ratio(at(fcf, 0), r0), ratio(at(fcf, 4), r4)
    F["fcf_m_yoy_q"] = (m0 - m4) if m0 is not None and m4 is not None else None      # 单季度口径(免费数据只有 5 个季度)
    F["opinc_yoy"] = (at(oi, 0) / at(oi, 4) - 1) if at(oi, 0) is not None and at(oi, 4) and at(oi, 4) > 0 else None
    o0, o4 = ratio(at(oi, 0), r0), ratio(at(oi, 4), r4)
    F["opm"], F["opm_yoy_chg"] = o0, (o0 - o4) if o0 is not None and o4 is not None else None
    g0, g4 = ratio(at(gp, 0), r0), ratio(at(gp, 4), r4)
    F["gm"], F["gm_yoy_chg"] = g0, (g0 - g4) if g0 is not None and g4 is not None else None
    e0, e4 = at(eps, 0), at(eps, 4)
    F["eps_yoy"] = (e0 / e4 - 1) if e0 is not None and e4 is not None and e4 > 0.05 else None      # 去年为负或接近零 → 不算失真的百分比
    c0, d0, q0 = at(cash, 0), at(debt, 0), at(eq, 0)
    F["cash"], F["debt"] = c0, d0
    F["cash_debt"] = (c0 / d0) if c0 is not None and d0 else (10.0 if c0 is not None and d0 == 0 else None)
    F["debt_eq"] = (d0 / q0) if d0 is not None and q0 and q0 > 0 else None
    F["neg_equity"] = q0 is not None and q0 <= 0
    t = F["ttm_fcf"]
    F["runway"] = (12 * c0 / abs(t)) if t is not None and t < 0 and c0 is not None else None
    ks, fd, ap = Q.get("defaultKeyStatistics") or {}, Q.get("financialData") or {}, Q.get("assetProfile") or {}
    raw_of = lambda d, k: (d.get(k) or {}).get("raw") if isinstance(d.get(k), dict) else None
    F["sector"], F["industry"] = ap.get("sector"), ap.get("industry")
    F["fpe"], F["peg"], F["ev_rev"], F["ev_ebitda"] = raw_of(ks, "forwardPE"), raw_of(ks, "pegRatio"), raw_of(ks, "enterpriseToRevenue"), raw_of(ks, "enterpriseToEbitda")
    F["roe"], F["roa"] = raw_of(fd, "returnOnEquity"), raw_of(fd, "returnOnAssets")
    if F["roe"] is not None and F["neg_equity"]:
        F["roe"] = None                               # 负净资产下的 ROE 不参与评分
    try:
        tr = (Q.get("earningsTrend") or {}).get("trend", [])[0].get("epsTrend") or {}
        cur, ago = (tr.get("current") or {}).get("raw"), (tr.get("30daysAgo") or {}).get("raw")
        F["eps_rev30"] = (cur / ago - 1) if cur is not None and ago and ago > 0 else None
    except Exception:
        F["eps_rev30"] = None
    try:
        hist = (Q.get("earningsHistory") or {}).get("history") or []
        F["surprise"] = (hist[-1].get("surprisePercent") or {}).get("raw") if hist else None
    except Exception:
        F["surprise"] = None
    F["ttm_yoy"] = None
    F["has_data"] = F["q_yoy"] is not None or F["ttm_fcf"] is not None
    return F


def finnhub_ttm_yoy(sym):
    """可选:Finnhub 的 TTM 营收同比(小数)。没有 FINNHUB_KEY 或取不到返回 None。"""
    key = os.environ.get("FINNHUB_KEY")
    if not key:
        return None
    try:
        d = core._get("https://finnhub.io/api/v1/stock/metric?" + urllib.parse.urlencode({"symbol": sym, "metric": "all", "token": key}), 3600)
        v = (d.get("metric") or {}).get("revenueGrowthTTMYoy")
        time.sleep(1.1)                                # 免费版每分钟 60 次
        return v / 100 if v is not None else None
    except Exception:
        return None


# =============================== 条件判定(纯函数,便于测试) ===============================
def cond(cid, label, ok, note=""):
    return {"id": cid, "label": label, "ok": ok, "note": note}


def allok(cs):
    if any(c["ok"] is False for c in cs):
        return False
    if any(c["ok"] is None for c in cs):
        return None
    return True


def gt(a, b):
    return None if a is None or b is None else a > b


def ge(a, b):
    return None if a is None or b is None else a >= b


def universe_conds(s, T, strat, cfg=CFG):
    u = cfg["universe"]
    return [cond("R1", f"市值 ≥ ${u['cap_min'][strat] / 1e9:.0f}B", s["cap"] >= u["cap_min"][strat]),
            cond("R2", "60 日均成交额 ≥ $20M", None if T is None else T["adv"] >= u["adv_min"]),
            cond("R3", "股价 ≥ $10", None if T is None else T["px"] >= u["price_min"]),
            cond("R4", "NYSE/NASDAQ 普通股", bool(s.get("type_ok", True))),
            cond("R5", "至少 252 个交易日行情", T is not None)]


def fcf_safety(F, cfg_b):
    """激进成长财务安全:TTM FCF>0;或(季度营收同比≥35% 且 FCF 率同比改善≥3pp 且现金覆盖≥18 个月)。"""
    t = F.get("ttm_fcf")
    if t is None:
        return None
    if t > 0:
        return True
    parts = [ge(F.get("q_yoy"), cfg_b["fcf_b_q_yoy"]), ge(F.get("fcf_m_yoy_q"), cfg_b["fcf_b_margin_improve"]), ge(F.get("runway"), cfg_b["runway_months"])]
    if any(p is False for p in parts):
        return False
    return None if any(p is None for p in parts) else True


def eval_growth(s, T, F, cfg=CFG):
    g = cfg["growth"]
    U = universe_conds(s, T, "growth", cfg)
    if T is None:
        return {"status": "NONE", "conds": U}
    F = F or {}
    G1 = cond("G1", f"最新季度营收同比 ≥ {g['g1_q_yoy'] * 100:.0f}%", ge(F.get("q_yoy"), g["g1_q_yoy"]), "G1-B 路径因缺少前一季度同比数据已关闭" if not g["g1b_enabled"] else "")
    SAFE = cond("FS", "财务安全:TTM 自由现金流>0,或高增长+FCF 改善+现金≥18 个月", fcf_safety(F, g))
    trend = [cond("AG4", "收盘价 > 20日线 > 50日线 > 200日线,且 50 日线 20 天前更低", T["px"] > T["sma20"] > T["sma50"] > T["sma200"] and T["sma50"] > T["sma50_ago"]),
             cond("AG5", "60 日回归斜率 > 0", None if T["slope"] is None else T["slope"] > 0),
             cond("AG6", "ADX ≥ 20 且 +DI > -DI", None if T["adx"] is None else (T["adx"] >= g["adx_min"] and T["pdi"] > T["mdi"])),
             cond("AG7", "近 63 日收益跑赢 SPY", T["rs63"] > 0)]
    miss = sum(1 for c in trend if c["ok"] is False)
    fund, hu = allok([G1, SAFE]), allok(U)
    if hu is False or fund is False:
        status = "NONE"
    elif fund is None:
        status = "DATA_INSUFFICIENT" if miss == 0 else "NONE"
    else:
        status = "CONFIRMED" if miss == 0 else ("WATCHING" if miss <= g["watch_max_miss"] else "NONE")
    flags = ["EXTENDED_PRICE"] if T["atr"] and T["px"] > T["sma20"] + g["extended_atr_mult"] * T["atr"] else []
    return {"status": status, "conds": U + [G1, SAFE] + trend, "flags": flags, "layers": {"universe": hu, "safety": fund, "setup": miss == 0}}


def eval_pullback(s, T, F, cfg=CFG):
    p = cfg["pullback"]
    U = universe_conds(s, T, "pullback", cfg)
    if T is None:
        return {"status": "NONE", "conds": U}
    F = F or {}
    q_ok = ge(F.get("q_yoy"), p["g1_q_yoy"])
    t_ok = ge(F.get("ttm_yoy"), p["g1_ttm_yoy"])
    g1 = False if (q_ok is False or t_ok is False) else (None if q_ok is None or t_ok is None else True)
    G1 = cond("G1", f"季度营收同比 ≥ {p['g1_q_yoy'] * 100:.0f}% 且 TTM 营收同比 ≥ {p['g1_ttm_yoy'] * 100:.0f}%", g1, "TTM 同比需要 Finnhub" if F.get("ttm_yoy") is None else "")
    SAFE = cond("FS", "TTM 自由现金流 > 0", gt(F.get("ttm_fcf"), 0))
    sp1 = T["px"] > T["sma200"] and T["sma50"] > T["sma200"] and T["sma200"] > T["sma200_ago"]
    A = T["touch5"]
    B = T["near5"]
    C = p["dd20_min"] <= T["dd20"] <= p["dd20_max"]
    SP = [cond("SP1", "收盘价>200日线、50日线>200日线、200日线向上", sp1),
          cond("SP2", "回调形态:触及布林下轨 / 贴近 20·50 日线(0.5×ATR)/ 距 20 日高点回撤 4%–12%", (A or B or C) and sp1, f"触及下轨={A} 贴近均线={B} 回撤={T['dd20'] * 100:.1f}%"),
          cond("SP3", "最近 5 日最低 RSI ≤ 50", T["rsi_min5"] <= p["rsi_min5_max"])]
    sp4a = T["rsi"] > T["rsi_prev"] and T["rsi"] - T["rsi_min5"] >= p["rsi_bounce"]
    sp4b = T["px"] > T["prev_high"] or T["cross_sma5"]
    SP4 = cond("SP4", "止跌确认:RSI 回升≥3 点,且收盘>前日最高价 或 上穿 5 日线", sp4a and sp4b)
    hu, fund, setup = allok(U), allok([G1, SAFE]), allok(SP)
    need_ttm = hu and setup and F.get("ttm_yoy") is None and q_ok is not False and gt(F.get("ttm_fcf"), 0) is True
    if hu is False or fund is False or setup is not True:
        status = "NONE"
    elif fund is None:
        status = "DATA_INSUFFICIENT"
    else:
        status = "CONFIRMED" if SP4["ok"] else "WATCHING"
    return {"status": status, "conds": U + [G1, SAFE] + SP + [SP4], "flags": [], "need_ttm": bool(need_ttm), "layers": {"universe": hu, "safety": fund, "setup": setup}}


def eval_reversal(s, T, F, cfg=CFG):
    r = cfg["reversal"]
    U = universe_conds(s, T, "reversal", cfg)
    if T is None:
        return {"status": "NONE", "conds": U}
    F = F or {}
    OR2 = cond("OR2", "52 周区间位置 ≤ 35%,或距 52 周高点回撤 ≥ 25%", None if T["range_pos"] is None else (T["range_pos"] <= r["range_pos_max"] or T["dd52"] >= r["dd52_min"]))
    OR3 = cond("OR3", "最近 15 日最低 RSI ≤ 35,当前 RSI ≥ 40 且高于前一日", T["rsi_min15"] <= r["rsi_min_max"] and T["rsi"] >= r["rsi_now_min"] and T["rsi"] > T["rsi_prev"])
    OR4 = cond("OR4", "TTM 营收同比 > 0", gt(F.get("ttm_yoy"), 0), "TTM 同比需要 Finnhub" if F.get("ttm_yoy") is None else "")
    t = F.get("ttm_fcf")
    OR5 = cond("OR5", "财务安全:TTM 自由现金流>0,或现金覆盖 ≥ 18 个月", None if t is None else (True if t > 0 else ge(F.get("runway"), r["runway_months"])),
               "无法检测债务到期/持续经营风险(数据源缺失)")
    d = T["div"]
    price_a = T["break5"] or T["above20_2"]
    path_a = bool(d["found"] and price_a and T["vol_ratio"] is not None and T["vol_ratio"] >= r["vol_mult_A"])
    path_b = bool(T["rsi_min15"] <= r["pathB_rsi_min"] and T["break10"] and T["above20_2"] and T["vol_ratio"] is not None and T["vol_ratio"] >= r["pathB_vol_mult"])
    CONF = cond("CF", "反转确认:路径A(MACD 底背离+价格+放量1.2倍)或路径B(RSI≤30+突破10日高+连续2日>20日线+放量1.5倍)", path_a or path_b,
                "MACD_DIVERGENCE" if path_a else ("PRICE_VOLUME_REVERSAL" if path_b else ("仅出现底背离,价格未确认" if d["found"] else "")))
    base = allok(U + [OR2, OR3, OR4, OR5])
    need_ttm = allok(U + [OR2, OR3, OR5]) is True and F.get("ttm_yoy") is None
    if base is False:
        status = "NONE"
    elif base is None:
        status = "DATA_INSUFFICIENT" if allok(U + [OR2, OR3, OR5]) is True and (path_a or path_b or d["found"]) else "NONE"
    elif path_a or path_b:
        status = "CONFIRMED"
    else:
        status = "WATCHING" if d["found"] else "NONE"
    low = d["low"] if (path_a and d["found"]) else (T["pullback_low"] if path_b else None)
    return {"status": status, "conds": U + [OR2, OR3, OR4, OR5, CONF], "flags": [], "path": "MACD_DIVERGENCE" if path_a else ("PRICE_VOLUME_REVERSAL" if path_b else None),
            "invalid_below": low, "need_ttm": bool(need_ttm), "layers": {"universe": allok(U), "safety": allok([OR4, OR5]), "setup": allok([OR2, OR3])}}


EVALS = {"growth": eval_growth, "pullback": eval_pullback, "reversal": eval_reversal}
NAMES = {"growth": "激进成长", "pullback": "强势回调", "reversal": "超跌反转"}


# =============================== 评分 ===============================
FUND_KEYS = {"q_yoy", "opinc_yoy", "eps_yoy", "opm_yoy_chg", "fcf_m", "opm", "gm", "gm_yoy_chg", "roe", "ev_rev", "fcf_yield", "peg", "eps_rev30", "surprise", "cash_debt", "debt_eq"}


class Pool:
    """池内百分位:财务指标先按行业(≥30 只),不足用板块,再不足用全体;技术指标在全体里比较。极端值先截尾。"""
    def __init__(self, stocks, cfg=CFG):
        self.cfg, self.cache, self.stocks = cfg, {}, stocks

    def group(self, s, key):
        if key not in FUND_KEYS:
            return ("all",)
        for lvl, gk in (("industry", s.get("industry")), ("sector", s.get("sector"))):
            if gk:
                members = [x for x in self.stocks if x.get(lvl) == gk and x["M"].get(key) is not None]
                if len(members) >= self.cfg["pool_min_group"]:
                    return (lvl, gk)
        return ("all",)

    def values(self, g, key):
        ck = (g, key)
        if ck not in self.cache:
            if g[0] == "all":
                vals = [x["M"][key] for x in self.stocks if x["M"].get(key) is not None]
            else:
                vals = [x["M"][key] for x in self.stocks if x.get(g[0]) == g[1] and x["M"].get(key) is not None]
            vals.sort()
            lo, hi = self.cfg["winsor"]
            if vals:
                a, b = vals[int(lo * (len(vals) - 1))], vals[int(hi * (len(vals) - 1))]
                vals = [min(max(v, a), b) for v in vals]
            self.cache[ck] = vals
        return self.cache[ck]

    def pct(self, s, key):
        v = s["M"].get(key)
        if v is None:
            return None
        vals = self.values(self.group(s, key), key)
        if not vals:
            return None
        v = min(max(v, vals[0]), vals[-1])
        less = sum(1 for x in vals if x < v)
        eq = sum(1 for x in vals if x == v)
        return (less + 0.5 * eq) / len(vals)


def score(s, strat, pool, extra, cfg=CFG):
    """返回 (0–100 分, 覆盖度, 分项明细)。缺失子项不当作 0 也不当作达标:重新归一化可用权重,并输出覆盖度。"""
    comps, total_w, got, cov, detail = cfg["score"][strat], 0.0, 0.0, 0.0, {}
    for name, cw, subs in comps:
        sw_all = sum(x[3] for x in subs)
        acc, sw = 0.0, 0.0
        for key, kind, hib, w in subs:
            v = extra.get(key) if kind == "d" else pool.pct(s, key)
            if v is None:
                continue
            acc += w * (v if hib else 1 - v)
            sw += w
        cov += cw * sw / sw_all
        if sw:
            detail[name] = round(acc / sw * 100)
            got += cw * acc / sw
            total_w += cw
    return (round(got / total_w * 100, 1) if total_w else None), round(cov, 3), detail


def strat_extra(strat, T, F, ev, cfg=CFG):
    ex = {}
    if strat == "pullback":
        ex["depth_fit"] = max(0.0, 1 - abs(T["dd20"] - 0.08) / 0.08)
    if strat == "reversal":
        d = T["div"]
        ex["path_score"] = 1.0 if ev.get("path") == "MACD_DIVERGENCE" else (0.75 if ev.get("path") else 0.3)
        ex["div_strength"] = d["strength"] if d["found"] else 0.0
        t = F.get("ttm_fcf") if F else None
        ex["runway_score"] = None if t is None else (1.0 if t > 0 else (min(F["runway"] / 36, 1.0) if F.get("runway") is not None else None))
    return ex


# =============================== 历史追踪 ===============================
LIVE = ("NEW", "STILL_VALID", "CONFIRMED")


def update_history(hist, today, date, keep_days=5):
    """hist: {key: {...}}; today: {key: {status, score, invalid_below, px, reason}}。返回 (新 hist, 本次状态 {key: status})。
    今天 CONFIRMED:此前是 NEW/STILL_VALID → STILL_VALID,否则 NEW。此前确认过、今天不再满足 → INVALIDATED。"""
    out, st = {k: dict(v) for k, v in hist.items()}, {}
    d0 = datetime.date.fromisoformat(date)
    for k, t in today.items():
        h = out.get(k, {})
        prev = h.get("latest_status")
        status = t["status"]
        if status == "CONFIRMED":
            if prev in LIVE and h.get("last_updated_date") == date:
                status = prev                                  # 同一个数据日重跑:保持原状态,不把 NEW 变成 STILL_VALID
            else:
                status = "STILL_VALID" if prev in LIVE else "NEW"
        if status in ("NEW", "STILL_VALID", "WATCHING", "DATA_INSUFFICIENT"):
            h.setdefault("first_detected_date", date)
            if status in ("NEW", "STILL_VALID"):
                h.setdefault("first_confirmed_date", date if status == "NEW" else h.get("first_confirmed_date", date))
                h["invalid_below"] = t.get("invalid_below")
            h.update(latest_status=status, latest_score=t.get("score"), last_updated_date=date)
            out[k] = h
            st[k] = status
    for k, h in list(out.items()):
        if k in st:
            continue
        if h.get("latest_status") in LIVE:                 # 之前确认过,今天不在确认名单里
            t = today.get(k)
            reason = "不再满足全部确认条件" + (f"(收盘价 {t['px']:.2f} 跌破 {h['invalid_below']:.2f})" if t and h.get("invalid_below") and t["px"] < h["invalid_below"] else "")
            h.update(latest_status="INVALIDATED", last_updated_date=date, invalid_reason=reason)
            st[k] = "INVALIDATED"
        elif h.get("latest_status") == "INVALIDATED":
            if (d0 - datetime.date.fromisoformat(h.get("last_updated_date", date))).days > keep_days:
                del out[k]
            else:
                st[k] = "INVALIDATED"
        elif h.get("latest_status") in ("WATCHING", "DATA_INSUFFICIENT"):
            del out[k]
    return out, st


# =============================== 数据获取 ===============================
def get_bars(sym):
    r = core._chart(sym, "2y", "1d", 3600)
    q, ts = r["indicators"]["quote"][0], r["timestamp"]
    adjc = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
    rows = [i for i in range(len(ts)) if None not in (q["high"][i], q["low"][i], q["close"][i], adjc[i])]
    return {"dates": [datetime.datetime.utcfromtimestamp(ts[i]).strftime("%Y-%m-%d") for i in rows], "h": [q["high"][i] for i in rows], "l": [q["low"][i] for i in rows],
            "c": [q["close"][i] for i in rows], "adj": [adjc[i] for i in rows], "v": [(q["volume"][i] or 0) for i in rows]}


def get_universe(cfg=CFG):
    u = cfg["universe"]
    out, seen = [], set()
    core._yh_open("https://query2.finance.yahoo.com/v10/finance/quoteSummary/AAPL?modules=price")
    cap_floor = min(u["cap_min"].values())
    for off in range(0, 2000, 250):
        body = {"offset": off, "size": 250, "sortField": "intradaymarketcap", "sortType": "DESC", "quoteType": "EQUITY", "topOperator": "AND",
                "query": {"operator": "AND", "operands": [{"operator": "eq", "operands": ["region", "us"]}, {"operator": "gt", "operands": ["intradaymarketcap", cap_floor]},
                                                         {"operator": "or", "operands": [{"operator": "eq", "operands": ["exchange", e]} for e in u["exchanges"]]}]},
                "userId": "", "userIdType": "guid"}
        req = urllib.request.Request("https://query1.finance.yahoo.com/v1/finance/screener?crumb=" + urllib.parse.quote(core._yh["crumb"]) + "&lang=en-US&region=US",
                                     data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
        try:
            res = json.load(core._yh["op"].open(req, timeout=25))["finance"]["result"][0]
        except Exception as e:
            print("  股票池查询失败:", type(e).__name__, str(e)[:60])
            break
        for q in res.get("quotes", []):
            sym = q.get("symbol")
            if not sym or sym in seen:
                continue
            seen.add(sym)
            name = q.get("shortName") or q.get("longName") or sym
            ok = not any(w in name.lower() for w in u["exclude_name_words"]) and q.get("quoteType", "EQUITY") == "EQUITY"
            px, vol = q.get("regularMarketPrice") or 0, q.get("averageDailyVolume3Month") or 0
            if px >= u["price_min"] * 0.9 and px * vol >= u["adv_min"] * 0.6:       # 粗筛;精确的 R2/R3 稍后用行情逐只计算
                out.append({"sym": sym, "name": name, "cap": q.get("marketCap") or 0, "type_ok": ok})
        if len(res.get("quotes", [])) < 250:
            break
    return out


def market_regime(spy):
    c = spy["c"]
    s50, s200 = sma(c, 50), sma(c, 200)
    if c[-1] > s200[-1] and s50[-1] > s50[-21]:
        return "BULL"
    if c[-1] < s200[-1] and s200[-1] < s200[-21]:
        return "BEAR"
    return "NEUTRAL"


# =============================== 输出行 ===============================
def extra_risks(strat, row):
    """确认条件满足不等于当前价格适合买入:价格已离回调低点/波段低点很远,或距 20 日高点空间不足,单独提示。"""
    out, px = [], row.get("price")
    low, rr, inv = row.get("pullbackLow"), row.get("rr"), row.get("invalidBelow")
    if strat == "pullback" and low and px and px / low - 1 > 0.10:
        out.append(f"价格已较回调低点上涨 {(px / low - 1) * 100:.0f}%,反弹可能已走完一段")
    if strat == "pullback" and rr is not None and rr < 1:
        out.append(f"估计收益风险比仅 {rr}(到 20 日高点的空间小于到回调低点的风险)")
    if strat == "reversal" and inv and px and px / inv - 1 > 0.25:
        out.append(f"价格已较确认低点上涨 {(px / inv - 1) * 100:.0f}%,反转可能已经走了很远")
    if row.get("rsi") is not None and row["rsi"] >= 70:
        out.append(f"RSI {row['rsi']:.0f} 已进入偏热区间")
    return out


def val_label(s, pool):
    """估值标签:用 EV/Revenue 在同行业(样本不足则板块/全体)里的百分位判断;不适用就标 NOT_MEANINGFUL。"""
    ev = s["M"].get("ev_rev")
    if ev is None or ev <= 0:
        return "NOT_MEANINGFUL"
    p = pool.pct(s, "ev_rev")
    return "NOT_MEANINGFUL" if p is None else ("UNDERVALUED_RELATIVE_TO_PEERS" if p <= 1 / 3 else ("EXPENSIVE_RELATIVE_TO_PEERS" if p >= 2 / 3 else "FAIR_VALUATION"))


def top_rows(rows, n):
    """只取确认状态的股票,按评分从高到低,最多 n 只;不足 n 只就只显示这么多,不凑数。"""
    return sorted([r for r in rows if r["status"] in ("NEW", "STILL_VALID")], key=lambda r: r["score"] or 0, reverse=True)[:n]


def tier(cap):
    t = CFG["universe"]["cap_tiers"]
    return "Mega" if cap >= t["mega"][0] else ("Large" if cap >= t["large"][0] else "Mid")


def explain(strat, s, T, F, ev):
    pct = lambda v: "--" if v is None else f"{v * 100:.0f}%"
    why = {"growth": f"季度营收同比 {pct(F.get('q_yoy'))},TTM 自由现金流率 {pct(F.get('fcf_m'))};均线多头(20>50>200),ADX {T['adx']:.0f},近 63 日跑赢 SPY {pct(T['rs63'])}。",
           "pullback": f"成长与现金流达标(营收同比 {pct(F.get('q_yoy'))}、FCF 率 {pct(F.get('fcf_m'))});长期趋势未破坏,近期回撤 {T['dd20'] * 100:.1f}%、5 日最低 RSI {T['rsi_min5']:.0f};RSI 回升并出现价格止跌确认。",
           "reversal": f"距 52 周高点回撤 {T['dd52'] * 100:.0f}%,15 日最低 RSI {T['rsi_min15']:.0f},现 RSI {T['rsi']:.0f};路径 {ev.get('path') or '未确认'};财务安全条件通过。"}[strat]
    bull = []
    if T["adx"] and T["adx"] >= 25:
        bull.append(f"ADX {T['adx']:.0f} 趋势较强")
    if (T["r2"] or 0) >= 0.35:
        bull.append(f"60 日趋势拟合 R² {T['r2']:.2f}")
    if T["near_high"] >= 0.9:
        bull.append("距 52 周高点 10% 以内")
    if T["vol_ratio"] and T["vol_ratio"] >= 1.2:
        bull.append(f"当日量能为 20 日均量的 {T['vol_ratio']:.1f} 倍")
    if F.get("eps_rev30") and F["eps_rev30"] > 0:
        bull.append(f"本季 EPS 预期近 30 天上调 {F['eps_rev30'] * 100:.1f}%")
    if F.get("surprise") and F["surprise"] > 0:
        bull.append(f"上季业绩超预期 {F['surprise'] * 100:.1f}%")
    if F.get("opm_yoy_chg") and F["opm_yoy_chg"] > 0:
        bull.append(f"营业利润率同比改善 {F['opm_yoy_chg'] * 100:.1f} 个百分点" if F["opm_yoy_chg"] <= 1 else "营业利润率同比大幅改善(去年同期基数为大幅亏损,数字不具可比性)")
    risks = list(ev.get("flags", []))
    rk = CFG["risk"]
    if F.get("gm_yoy_chg") is not None and F["gm_yoy_chg"] < rk["gm_drop"]:
        risks.append(f"毛利率同比下降 {abs(F['gm_yoy_chg']) * 100:.1f} 个百分点")
    if F.get("neg_equity"):
        risks.append("净资产为负,ROE 不具参考性")
    if F.get("debt_eq") and F["debt_eq"] > rk["high_debt_eq"]:
        risks.append(f"负债/净资产 {F['debt_eq']:.1f}")
    if T["atr_pct"] and T["atr_pct"] > rk["high_atr_pct"]:
        risks.append(f"日波动较大(ATR 约 {T['atr_pct'] * 100:.1f}%)")
    if F.get("ttm_fcf") is not None and F["ttm_fcf"] < 0:
        risks.append("TTM 自由现金流为负,依赖现金储备")
    if F.get("fcf_mismatch"):
        risks.append("自由现金流两种算法差异较大,请核对")
    if F.get("eps_rev30") is not None and F["eps_rev30"] < 0:
        risks.append("本季 EPS 预期近 30 天被下调")
    risks.append("技术形态没有被证明有预测能力;重大债务到期/经营存续风险无法由免费数据检测")
    inv = {"growth": f"收盘价跌破 50 日线({T['sma50']:.2f});季度营收同比低于 25%;TTM 自由现金流转负且现金覆盖不足 18 个月;近 63 日收益不再跑赢 SPY。",
           "pullback": f"收盘价跌破 200 日线({T['sma200']:.2f})或本次回调低点({T['pullback_low']:.2f});50 日线下穿 200 日线;TTM 自由现金流转负。",
           "reversal": f"收盘价重新跌破确认的波段低点({(ev.get('invalid_below') or T['pullback_low']):.2f});财务安全条件不再成立;出现新的更低低点。"}[strat]
    return why, bull, risks, inv


def make_row(strat, s, T, F, ev, sc, cov, detail, hist_status, regime):
    why, bull, risks, inv = explain(strat, s, T, F, ev)
    passed = [c["label"] for c in ev["conds"] if c["ok"]]
    failed = [f"{c['label']}" + (f"({c['note']})" if c["note"] else "") for c in ev["conds"] if c["ok"] is False]
    pend = [f"{c['label']}(无数据:{c['note']})" for c in ev["conds"] if c["ok"] is None]
    risk_to_reward = None
    if strat == "pullback":
        stop, target = T["pullback_low"], T["hh20"]
        if stop < T["px"] < target and T["px"] - stop > 0:
            risk_to_reward = round((target - T["px"]) / (T["px"] - stop), 2)
    prio = "观察" if ev["status"] == "WATCHING" else ("高" if (sc or 0) >= 70 and regime != "BEAR" else ("中" if (sc or 0) >= 55 else "低"))
    if strat == "reversal" and regime == "BEAR" and prio == "高":
        prio = "中"
    return {"sym": s["sym"], "name": s["name"], "price": round(T["px"], 2), "cap": s["cap"], "tier": tier(s["cap"]), "sector": F.get("sector"), "industry": F.get("industry"),
            "strategy": strat, "status": hist_status, "score": sc, "coverage": cov, "score_detail": detail,
            "revYoY": F.get("q_yoy"), "ttmFCF": F.get("ttm_fcf"), "fcfMargin": F.get("fcf_m"), "rsi": round(T["rsi"], 1), "adx": round(T["adx"], 1) if T["adx"] else None,
            "sma": [round(T["sma20"], 2), round(T["sma50"], 2), round(T["sma200"], 2)], "rs63": round(T["rs63"], 4),
            "volRatio": round(T["vol_ratio"], 2) if T["vol_ratio"] else None, "macdDiv": ev.get("path") == "MACD_DIVERGENCE" or T["div"]["found"],
            "path": ev.get("path"), "valuation": {"fpe": F.get("fpe"), "evRev": F.get("ev_rev"), "evEbitda": F.get("ev_ebitda"), "peg": F.get("peg"),
                                                  "fcfYield": F.get("fcf_yield")},
            "atr": round(T["atr"], 2) if T["atr"] else None, "pullbackLow": round(T["pullback_low"], 2), "dist20High": round(T["hh20"] / T["px"] - 1, 4), "rr": risk_to_reward,
            "risks": risks, "flags": ev.get("flags", []), "passed": passed, "failed": failed, "pending": pend, "fundDate": F.get("asof"), "signalDate": T["date"],
            "priority": prio, "why": why, "bullish": bull, "invalidate": inv, "invalidBelow": ev.get("invalid_below")}


# =============================== 主流程 ===============================
def run(limit=0, out_path=None, use_history=True):
    t0 = time.time()
    stats = {"universe_raw": 0, "bars_ok": 0, "history_short": 0, "unsupported_sector": 0, "no_fundamentals": 0, "adv_fail": 0}
    print("1/5 股票池…")
    uni = get_universe()
    if limit:
        uni = uni[:limit]
    stats["universe_raw"] = len(uni)
    spy = get_bars("SPY")
    regime = market_regime(spy)
    print(f"    候选 {len(uni)} 只;市场环境 {regime}")
    print("2/5 行情与技术指标…")

    spy_by_date = dict(zip(spy["dates"], spy["adj"]))

    def tech(s):
        try:
            b = get_bars(s["sym"])
            last, al = spy["adj"][0], []
            for d in b["dates"]:                    # 按日期对齐 SPY(缺失日沿用前一日)
                last = spy_by_date.get(d, last)
                al.append(last)
            return s, technicals(b, al, CFG)
        except Exception:
            return s, "ERR"

    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(tech, uni))
    stocks = []
    for s, T in res:
        if T == "ERR":
            continue
        stats["bars_ok"] += 1
        if T is None:
            stats["history_short"] += 1
        elif T["adv"] < CFG["universe"]["adv_min"] or T["px"] < CFG["universe"]["price_min"]:
            stats["adv_fail"] += 1
            continue
        s["T"] = T
        stocks.append(s)
    stocks = [s for s in stocks if s["T"] is not None]
    print(f"    行情成功 {stats['bars_ok']} 只,通过 R2/R3/R5 的 {len(stocks)} 只,用时 {time.time() - t0:.0f} 秒")
    print("3/5 财报与估值(Yahoo)…")
    with ThreadPoolExecutor(6) as ex:
        raws = list(ex.map(lambda s: fetch_raw(s["sym"]), stocks))
    for s, raw in zip(stocks, raws):
        F = derive(raw)
        s["F"], s["sector"], s["industry"] = F, F.get("sector"), F.get("industry")
        F["fcf_yield"] = (F["ttm_fcf"] / s["cap"]) if F.get("ttm_fcf") is not None and s["cap"] else None
        if not F["has_data"]:
            stats["no_fundamentals"] += 1
    unsupported = set(CFG["universe"]["unsupported_sectors"])
    work = [s for s in stocks if s["sector"] not in unsupported]
    stats["unsupported_sector"] = len(stocks) - len(work)
    print(f"    不支持的板块(金融/REIT)跳过 {stats['unsupported_sector']} 只;缺财报数据 {stats['no_fundamentals']} 只")
    print("4/5 策略判定…")
    evals = {}
    for s in work:
        evals[s["sym"]] = {k: fn(s, s["T"], s["F"]) for k, fn in EVALS.items()}
    # 只对"需要 TTM 营收同比"的少数股票取 Finnhub
    need = sorted({s["sym"] for s in work for k in ("pullback", "reversal") if evals[s["sym"]][k].get("need_ttm")})
    if need and os.environ.get("FINNHUB_KEY"):
        print(f"    需要 TTM 营收同比的 {len(need)} 只,向 Finnhub 查询…")
        for sym in need:
            s = next(x for x in work if x["sym"] == sym)
            s["F"]["ttm_yoy"] = finnhub_ttm_yoy(sym)
            evals[sym] = {k: fn(s, s["T"], s["F"]) for k, fn in EVALS.items()}
    elif need:
        print(f"    注意:{len(need)} 只依赖 TTM 营收同比,但没有设置 FINNHUB_KEY,将标记为 DATA_INSUFFICIENT")
    # 评分池:所有有数据的股票(不是只在入选的几只之间比)
    for s in work:
        F, T = s["F"], s["T"]
        s["M"] = {**{k: F.get(k) for k in ("q_yoy", "opinc_yoy", "eps_yoy", "opm_yoy_chg", "fcf_m", "opm", "gm", "gm_yoy_chg", "roe", "ev_rev", "fcf_yield", "peg", "eps_rev30", "surprise", "cash_debt", "debt_eq")},
                  **{k: T.get(k) for k in ("rs63", "rs126", "rs_pre", "adx", "r2", "near_high", "atr_pct", "ext_atr", "sma200_slope", "dn_vol", "vol_ratio", "updn_vol", "capit_vol", "breakout_pct", "break_prev_high")},
                  "rsi_bounce": T["rsi"] - T["rsi_min5"], "rsi_min15": T["rsi_min15"], "dd52": T["dd52"]}
    pool = Pool(work)
    print("5/5 评分、状态与历史…")
    today_hist, rows_by = {}, {k: [] for k in EVALS}
    counts = {k: {"universe": 0, "safety": 0, "setup": 0, "WATCHING": 0, "CONFIRMED": 0, "DATA_INSUFFICIENT": 0, "LOW_SCORE_COVERAGE": 0} for k in EVALS}
    fails = {k: {} for k in EVALS}
    for s in work:
        for k in EVALS:
            ev = evals[s["sym"]][k]
            ly = ev.get("layers") or {}
            for lk in ("universe", "safety", "setup"):
                if ly.get(lk):
                    counts[k][lk] += 1
            st = ev["status"]
            if st == "NONE":
                for c in ev["conds"]:
                    if c["ok"] is False:
                        fails[k][c["id"]] = fails[k].get(c["id"], 0) + 1
                        break
                continue
            sc, cov, det = score(s, k, pool, strat_extra(k, s["T"], s["F"], ev))
            if st in ("CONFIRMED", "WATCHING") and cov < CFG["score_min_coverage"]:
                counts[k]["LOW_SCORE_COVERAGE"] += 1
                st = "DATA_INSUFFICIENT"
            if st in counts[k]:
                counts[k][st] += 1
            today_hist[f"{s['sym']}|{k}"] = {"status": st, "score": sc, "invalid_below": ev.get("invalid_below"), "px": s["T"]["px"]}
            s.setdefault("_r", {})[k] = (ev, sc, cov, det, st)
    date = max(s["T"]["date"] for s in work)
    hist_path = os.path.join(ROOT, "public", "screener_history.json")
    hist = {}
    if use_history and os.path.exists(hist_path):
        try:
            hist = json.load(open(hist_path)).get("records", {})
        except Exception:
            hist = {}
    new_hist, status = update_history(hist, today_hist, date, CFG["invalidated_keep_days"]) if use_history else (hist, {k: ("NEW" if v["status"] == "CONFIRMED" else v["status"]) for k, v in today_hist.items()})
    presets = []
    for k in EVALS:
        conf, watch, inval = [], [], []
        for s in work:
            r = s.get("_r", {}).get(k)
            key = f"{s['sym']}|{k}"
            if not r:
                if status.get(key) == "INVALIDATED":
                    inval.append({"sym": s["sym"], "name": s["name"], "reason": new_hist[key].get("invalid_reason", ""), "date": new_hist[key].get("last_updated_date")})
                continue
            ev, sc, cov, det, st = r
            hs = status.get(key, st)
            if hs in ("NEW", "STILL_VALID", "WATCHING"):
                row = make_row(k, s, s["T"], s["F"], ev, sc, cov, det, hs, regime)
                row["valuation"]["label"] = val_label(s, pool)
                row["risks"] = extra_risks(k, row) + row["risks"]
                (watch if hs == "WATCHING" else conf).append(row)
        watch.sort(key=lambda r: r["score"] or 0, reverse=True)
        counts[k]["CONFIRMED"] = len(conf)
        presets.append({"id": k, "name": NAMES[k], "counts": counts[k], "confirmed": top_rows(conf, CFG["max_confirmed"]), "confirmedTotal": len(conf),
                        "watching": watch[:CFG["max_watching"]], "watchingTotal": len(watch), "invalidated": inval[:5],
                        "topFailures": sorted(fails[k].items(), key=lambda x: -x[1])[:5]})
    out = {"version": 2, "asof": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "dataDate": date, "regime": regime, "stats": stats,
           "universe": len(work), "presets": presets, "dataLimits": ["免费数据只有最近 5 个季度:G1-B 路径(需前一季度同比)已关闭;FCF 率同比为单季度口径",
                                                                  "TTM 营收同比依赖 Finnhub(可选);未设置时强势回调/超跌反转标记为 DATA_INSUFFICIENT",
                                                                  "财报只有季度截止日,没有公告日期,因此不能做严格的历史回测",
                                                                  "无法检测债务到期、持续经营风险等事件"]}
    out_path = out_path or os.path.join(ROOT, "public", "screener.json")
    json.dump(out, open(out_path, "w"), ensure_ascii=False)
    if use_history:
        json.dump({"records": new_hist, "updated": date}, open(hist_path, "w"), ensure_ascii=False)
    for p in presets:
        c = p["counts"]
        print(f"  {p['name']}: 股票池 {c['universe']} → 财务安全 {c['safety']} → 形态 {c['setup']} → 观察 {p['watchingTotal']} / 确认 {p['confirmedTotal']} / 数据不足 {c['DATA_INSUFFICIENT']};"
              f"入选 {[r['sym'] for r in p['confirmed']]};常见失败 {p['topFailures'][:3]}")
    print(f"完成,用时 {time.time() - t0:.0f} 秒 → {out_path}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-history", action="store_true")
    ap.add_argument("--probe-finnhub", action="store_true")
    a = ap.parse_args()
    if a.probe_finnhub:
        print("AAPL TTM 营收同比(Finnhub):", finnhub_ttm_yoy("AAPL"))
    else:
        run(a.limit, a.out, not a.no_history)
