"""财务健康体检 / 质量分(Piotroski F-Score) / 风险分(Altman Z'' 分数) / 内在价值区间 / 财报前预期波动。
所有数字都由代码用 SEC 官方财报数据(以及 Yahoo 行情)算出,公式取自 FinanceToolkit 文档里的标准定义;好/一般/差的阈值是常见经验区间,
只说明「相对常见水平」,不是买卖结论。需要环境变量 SEC_CONTACT。
"""
import os, time
import _core as C
import _fin as F

EXTRA_FLOW = {"intexp": ["InterestExpense", "InterestExpenseDebt", "InterestExpenseNonoperating"],
              "shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"]}
EXTRA_STOCK = {"re": ["RetainedEarningsAccumulatedDeficit"], "dc": ["DebtCurrent", "LongTermDebtCurrent"]}


def _cf(sym):
    contact = (os.environ.get("SEC_CONTACT") or "").strip().strip("\"'“”‘’ ")
    if not contact:
        return None, "no_contact"
    if not contact.isascii():
        return None, "bad_contact"
    if sym in C.ALIAS:
        return None, "not_stock"
    h = {"User-Agent": "StocksMonitor " + contact}
    tk = C._get("https://www.sec.gov/files/company_tickers.json", 86400, h)
    cik = next((v["cik_str"] for v in tk.values() if v["ticker"] == sym.replace("-", ".")), None)
    if cik is None:
        return None, "no_cik"
    cf = C._get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json", 21600, h)
    if "us-gaap" not in cf.get("facts", {}):
        return None, "no_us_gaap"
    return cf, None


def _extra(cf, years):
    """补充指标:利息支出、股数、留存收益(按财年末对齐)。"""
    out = {}
    for k, tags in EXTRA_FLOW.items():
        unit = "shares" if k == "shares" else "USD"
        out[k] = F.annual(F._facts(cf, tags, unit))
    for k, tags in EXTRA_STOCK.items():
        out[k] = F.stock_series(F._facts(cf, tags, "USD"))
    dei = cf.get("facts", {}).get("dei", {}).get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares") or []
    latest = max(dei, key=lambda r: r["end"])["val"] if dei else None
    if latest is None and out["shares"]:
        latest = out["shares"][max(out["shares"])][0]
    for y in years:
        e = y["end"]
        y["intexp"] = (out["intexp"].get(e) or (None,))[0]
        y["shares"] = (out["shares"].get(e) or (None,))[0]
        y["re"] = (out["re"].get(e) or (None,))[0]
        y["dc"] = (out["dc"].get(e) or (None,))[0]
    return latest


def _r(v, good, bad, higher=True):
    """按阈值分档:higher=True 时越大越好。good/bad 是两条分界线。"""
    if v is None:
        return None
    if higher:
        return "good" if v >= good else "bad" if v < bad else "ok"
    return "good" if v <= good else "bad" if v > bad else "ok"


def _pct(v, d=1):
    return None if v is None else f"{v:.{d}f}%"


def _money(v):
    if v is None:
        return "--"
    a = abs(v)
    s = f"{a / 1e12:.2f}T" if a >= 1e12 else f"{a / 1e9:.1f}B" if a >= 1e9 else f"{a / 1e6:.0f}M"
    return ("-" if v < 0 else "") + "$" + s


def checkup(y, p, t, shares_now, price):
    """约 16 项体检;每项:名称、数值、好/一般/差、新手解释。"""
    items = []
    add = lambda name, val, rate, why: items.append({"name": name, "val": val if val is not None else "数据不足", "rate": rate if val is not None else None, "why": why})
    add("毛利率", _pct(t.get("gm")), _r(t.get("gm"), 40, 20), "每卖 100 元,扣掉直接成本后剩多少。越高说明产品越有定价权、越难被替代。")
    add("营业利润率", _pct(t.get("om")), _r(t.get("om"), 20, 8), "扣完研发、销售、管理等所有运营费用后还剩多少,反映主业赚钱能力。")
    add("净利率", _pct(t.get("nm")), _r(t.get("nm"), 15, 5), "最终落到股东口袋的利润占营收的比例。")
    roe = roa = None
    if y.get("ni") is not None:
        eq = [e for e in (y.get("equity"), p.get("equity") if p else None) if e is not None]
        if eq and sum(eq) / len(eq) > 0:
            roe = y["ni"] / (sum(eq) / len(eq)) * 100
        if y.get("assets"):
            roa = y["ni"] / y["assets"] * 100
    add("净资产收益率 ROE", _pct(roe), _r(roe, 15, 8), "股东每投入 100 元净资产,一年赚多少。长期 15% 以上算优秀(股东权益为负或被大量回购时失真)。")
    add("总资产收益率 ROA", _pct(roa), _r(roa, 8, 3), "公司全部资产(含借来的钱)一年赚多少,比 ROE 更不容易被负债放大。")
    add("营收增速", _pct(t.get("rev_yoy")), _r(t.get("rev_yoy"), 10, 0), "近 12 个月营收比上一个 12 个月增长多少,生意在不在变大。")
    add("净利润增速", _pct(t.get("ni_yoy")), _r(t.get("ni_yoy"), 10, 0), "近 12 个月净利润的增长,和营收增速对着看:利润涨得比营收快说明越赚越多。")
    fm = t["fcf"] / t["rev"] * 100 if t.get("fcf") is not None and t.get("rev") else None
    add("自由现金流利润率", _pct(fm), _r(fm, 12, 5), "营收里有多少变成了真正能自由支配的现金(经营现金流减去设备投入)。")
    cv = t["fcf"] / t["ni"] if t.get("fcf") is not None and t.get("ni") and t["ni"] > 0 else None
    add("利润含金量", None if cv is None else f"{cv * 100:.0f}%", _r(cv, 0.8, 0.5), "自由现金流占净利润的比例。接近或超过 100% 说明利润是真金白银,不是账面数字。")
    dr = y.get("dr")
    add("资产负债率", _pct(dr), _r(dr, 50, 70, False), "总负债占总资产的比例。越低越稳;但大量回购分红的公司(如苹果)会把股东权益压低,数字偏高并不一定危险。")
    cr = y.get("cr")
    add("流动比率", None if cr is None else f"{cr:.2f}", _r(cr, 1.5, 1.0), "短期能变现的资产 ÷ 一年内要还的债。低于 1 说明短期还债有压力。")
    debt = (y.get("debt") or 0) + (y.get("dc") or 0) if y.get("debt") is not None or y.get("dc") is not None else None
    if debt is not None and y.get("cash") is not None:
        net = y["cash"] - debt
        if net >= 0:
            add("净现金 / 净债务", "净现金 " + _money(net), "good", "现金(不含有价证券)比有息负债还多,财务缓冲厚。")
        else:
            yrs = -net / y["ocf"] if y.get("ocf") and y["ocf"] > 0 else None
            add("净现金 / 净债务", f"净债务 {_money(-net)}" + (f"(约 {yrs:.1f} 年经营现金流可还清)" if yrs else ""), _r(yrs, 2, 4, False) if yrs else "bad", "有息负债减现金(现金只算现金及现金等价物,不含有价证券,所以会比实际偏保守)。用「几年的经营现金流能还清」衡量压力:2 年以内轻松,超过 4 年偏重。")
    else:
        add("净现金 / 净债务", None, None, "有息负债减现金。")
    ic = None
    if y.get("oi") is not None and y.get("intexp"):
        ic = y["oi"] / y["intexp"]
    if y.get("intexp") is None:
        add("利息保障倍数", None, None, "营业利润是利息支出的几倍。这家公司的财报里没有单独列出利息支出,无法计算。")
    elif y.get("intexp") == 0:
        add("利息保障倍数", "利息支出为 0", "good", "营业利润是利息支出的几倍,越高越不怕还息。")
    else:
        add("利息保障倍数", None if ic is None else f"{ic:.1f} 倍", _r(ic, 8, 3), "营业利润是利息支出的几倍,越高越不怕还息;低于 3 倍要警惕。")
    cx = abs(y["capex"]) / y["ocf"] * 100 if y.get("capex") is not None and y.get("ocf") and y["ocf"] > 0 else None
    add("资本开支强度", _pct(cx, 0), _r(cx, 30, 60, False), "经营现金流里有多少要花在设备厂房上。越低越轻资产,越高说明要不停砸钱才能维持增长。")
    cap = price * shares_now if price and shares_now else None
    pe = price / t["eps"] if price and t.get("eps") and t["eps"] > 0 else None
    if t.get("eps") is not None and t["eps"] <= 0:
        add("市盈率 P/E", "亏损,无意义", "bad", "股价 ÷ 每股收益,花多少年的利润买下它。")
    else:
        add("市盈率 P/E", None if pe is None else f"{pe:.1f} 倍", _r(pe, 18, 35, False), "股价 ÷ 近 12 个月每股收益。低不一定便宜、高不一定贵,要结合增速看;这里只表示相对常见区间。")
    fy = t["fcf"] / cap * 100 if cap and t.get("fcf") is not None else None
    add("自由现金流收益率", _pct(fy), _r(fy, 5, 2), "近 12 个月自由现金流 ÷ 总市值,相当于「把公司整个买下来,每年现金回报率多少」。")
    return items


def fscore(y, p):
    """Piotroski F-Score:9 条是/否检验,每条满足记 1 分。"""
    c = []
    add = lambda name, ok, why: c.append({"name": name, "ok": ok, "why": why})
    roa = lambda r: r["ni"] / r["assets"] if r and r.get("ni") is not None and r.get("assets") else None
    r1, r0 = roa(y), roa(p)
    add("今年赚钱(ROA>0)", None if r1 is None else r1 > 0, "总资产收益率为正")
    add("经营现金流为正", None if y.get("ocf") is None else y["ocf"] > 0, "主业产生现金")
    add("资产收益率在提高", None if r1 is None or r0 is None else r1 > r0, "ROA 比上一财年高")
    add("现金流大于净利润", None if y.get("ocf") is None or y.get("ni") is None else y["ocf"] > y["ni"], "利润有现金支撑,不是靠会计处理")
    lv = lambda r: ((r.get("debt") or 0) / r["assets"]) if r and r.get("assets") and r.get("debt") is not None else None
    a, b = lv(y), lv(p)
    add("长期负债占比下降", None if a is None or b is None else a <= b, "长期债务 ÷ 总资产没有上升")
    add("流动比率提高", None if y.get("cr") is None or not p or p.get("cr") is None else y["cr"] > p["cr"], "短期偿债能力变强")
    add("没有增发摊薄股东", None if not y.get("shares") or not p or not p.get("shares") else y["shares"] <= p["shares"] * 1.005, "股数没有增加(回购会让股数减少)")
    gm = lambda r: r["gp"] / r["rev"] if r and r.get("gp") is not None and r.get("rev") else None
    g1, g0 = gm(y), gm(p)
    add("毛利率提高", None if g1 is None or g0 is None else g1 > g0, "产品定价权或成本在改善")
    at = lambda r: r["rev"] / r["assets"] if r and r.get("rev") and r.get("assets") else None
    t1, t0 = at(y), at(p)
    add("资产周转率提高", None if t1 is None or t0 is None else t1 > t0, "每 1 元资产创造的营收增加")
    known = [x for x in c if x["ok"] is not None]
    score = sum(1 for x in known if x["ok"])
    lv_ = "强" if score >= 7 else "中" if score >= 4 else "弱"
    return {"score": score, "of": len(known), "level": lv_ if len(known) >= 7 else None, "checks": c}


def zscore(y):
    """Altman Z''(适用于非制造业和一般公司,不需要市值):Z=6.56·营运资本/总资产+3.26·留存收益/总资产+6.72·营业利润/总资产+1.05·净资产/总负债。"""
    need = (y.get("ca"), y.get("cl"), y.get("re"), y.get("oi"), y.get("assets"), y.get("equity"))
    liab = y.get("liab") if y.get("liab") is not None else (y["assets"] - y["equity"] if y.get("assets") and y.get("equity") is not None else None)
    if any(v is None for v in need) or not y.get("assets") or not liab or liab <= 0:
        return {"error": "n/a", "msg": "这类公司(银行、保险等没有流动资产概念,或缺少留存收益数据)不适用这个模型"}
    x1, x2, x3, x4 = (y["ca"] - y["cl"]) / y["assets"], y["re"] / y["assets"], y["oi"] / y["assets"], y["equity"] / liab
    z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
    zone = "安全区" if z > 2.6 else "灰色区" if z >= 1.1 else "危险区"
    return {"z": round(z, 2), "zone": zone, "parts": [["营运资本/总资产", round(x1, 3)], ["留存收益/总资产", round(x2, 3)], ["营业利润/总资产", round(x3, 3)], ["净资产/总负债", round(x4, 3)]]}


def dcf(years, shares_now, price):
    """教育用途的现金流折现:三种情景,所有假设都列出来。自由现金流不稳定或为负时不给。"""
    fc = [r["fcf"] for r in years if r.get("fcf") is not None][-3:]
    revs = [r["rev"] for r in years if r.get("rev")]
    last = years[-1]
    if len(fc) < 2 or fc[-1] <= 0 or min(fc) <= 0:
        return {"error": "n/a", "msg": "近 3 年自由现金流不稳定或为负,这个模型给不出可靠区间"}
    if not shares_now or last.get("cash") is None:
        return {"error": "n/a", "msg": "缺少股数或现金数据"}
    base = 0.6 * fc[-1] + 0.4 * sum(fc) / len(fc)          # 偏重最近一年,同时用近 3 年均值抹平波动
    n = min(5, len(revs) - 1)
    hist = (revs[-1] / revs[-1 - n]) ** (1 / n) - 1 if n >= 2 and revs[-1 - n] > 0 else 0.05
    g0 = max(0.03, min(0.25, hist))
    debt = (last.get("debt") or 0) + (last.get("dc") or 0)
    out = []
    for name, mult, r in (("保守", 0.5, 0.11), ("中性", 0.75, 0.10), ("乐观", 1.0, 0.09)):
        g, f, pv = g0 * mult, base, 0.0
        for yr in range(1, 11):
            gy = g + (0.03 - g) * (yr - 1) / 9                 # 增速在 10 年里线性回落到 3%
            f *= 1 + gy
            pv += f / (1 + r) ** yr
        tv = f * 1.025 / (r - 0.025) / (1 + r) ** 10
        ps = (pv + tv + last["cash"] - debt) / shares_now
        out.append({"name": name, "g": round(g * 100, 1), "r": round(r * 100, 1), "value": round(ps, 2)})
    return {"base_fcf": base, "hist_growth": round(hist * 100, 1), "scenarios": out, "price": price,
            "ratio": None if not price else round(price / out[1]["value"], 2), "terminal": 2.5,
            "asof": last["end"]}


def health(sym):
    cf, err = _cf(sym)
    if err:
        return {"error": err}
    rows, ttm, years = F.build(cf)
    if len(rows) < 4 or len(years) < 2:
        return {"error": "too_short"}
    shares_now = _extra(cf, years)
    try:
        price = C.quote(sym)["price"]
    except Exception:
        price = None
    y, p = years[-1], years[-2]
    y["dr"], y["cr"] = y.get("dr"), y.get("cr")
    return {"asof": y["end"], "price": price, "checkup": checkup(y, p, ttm, shares_now, price), "fscore": fscore(y, p), "zscore": zscore(y),
            "dcf": dcf(years, shares_now, price), "source": "SEC EDGAR 官方财报数据(XBRL)+ Yahoo 行情"}


# ---------- 财报前预期波动:用期权的跨式组合价格估算市场预期的涨跌幅 ----------
def expected_move(sym):
    ex = C._yh_extra(sym) or {}
    ed = (ex.get("events") or {}).get("earn")
    if not ed:
        return {"error": "no_date", "msg": "暂时查不到下一次财报日期"}
    dte = round((time.mktime(time.strptime(ed, "%Y-%m-%d")) - time.time()) / 86400)
    if dte > 45:
        return {"error": "too_far", "earn": ed, "estimate": (ex.get("events") or {}).get("earnEst"), "days": dte,
                "msg": f"下一次财报在 {ed}(还有约 {dte} 天)。离得太远,期权价格里混了太多日常波动,算出来没意义;临近 45 天内再看。"}
    price = C.quote(sym)["price"]
    base = f"https://query2.finance.yahoo.com/v7/finance/options/{sym}?x=1"
    d = C._yh_open(base)["optionChain"]["result"]
    if not d:
        return {"error": "no_options", "msg": "这只股票没有期权数据"}
    exps = d[0].get("expirationDates") or []
    et = time.mktime(time.strptime(ed, "%Y-%m-%d")) + 86400          # 财报当天盘前/盘后都算,取之后的第一个到期日
    nxt = next((e for e in exps if e >= et), None)
    if not nxt:
        return {"error": "no_expiry", "msg": "财报日之后暂无期权到期日"}
    chain = C._yh_open(base + f"&date={nxt}")["optionChain"]["result"][0]["options"][0]
    calls, puts = chain.get("calls") or [], chain.get("puts") or []
    if not calls or not puts:
        return {"error": "no_options", "msg": "期权链为空"}
    k = min((c["strike"] for c in calls), key=lambda s: abs(s - price))
    px = lambda lst: next((x for x in lst if x["strike"] == k), None)
    c, p = px(calls), px(puts)
    if not c or not p:
        return {"error": "no_options", "msg": "找不到对应行权价"}
    mid = lambda x: (x["bid"] + x["ask"]) / 2 if x.get("bid") and x.get("ask") else x.get("lastPrice")
    s = (mid(c) or 0) + (mid(p) or 0)
    if s <= 0:
        return {"error": "no_options", "msg": "期权报价缺失(可能在休市时段)"}
    return {"earn": ed, "estimate": (ex.get("events") or {}).get("earnEst"), "expiry": time.strftime("%Y-%m-%d", time.gmtime(nxt)), "strike": k, "price": price,
            "straddle": round(s, 2), "pct": round(s / price * 100, 1), "iv_c": c.get("impliedVolatility"), "iv_p": p.get("impliedVolatility"),
            "days": max(1, round((nxt - time.time()) / 86400)), "dte": dte}
