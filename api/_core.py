"""数据后台的核心逻辑(只用 Python 自带库,无需安装任何东西)。
- 行情/K线:Yahoo 财经(非官方接口,不需要 Key)
- 新闻/财报日历:Finnhub(环境变量 FINNHUB_KEY);目标价/评级变动/涨跌榜:FMP(环境变量 FMP_KEY)。Key 只在终端或 Vercel 环境变量里设置,不写入任何文件
"""
import json, os, time, datetime, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0"}
_cache = {}
DBG = {}          # 最近一次各功能的失败原因(只含错误类型和简短说明,不含网址和 Key),方便排查

# 页面上的代码 -> Yahoo 代码
ALIAS = {"SPX": "^GSPC", "IXIC": "^IXIC", "DJI": "^DJI", "GOLD": "GC=F", "VIX": "^VIX",
         "US10Y": "^TNX", "DXY": "DX-Y.NYB", "WTI": "CL=F", "BTC": "BTC-USD"}


def _get(url, ttl=10, headers=None):
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    _cache[url] = (time.time(), data)
    return data


def _chart(sym, rng, interval, ttl):
    ys = urllib.parse.quote(ALIAS.get(sym, sym), safe="")
    span = f"period1=0&period2={int(time.time()) + 86400}" if rng == "max" else f"range={rng}"   # range=max 会被 Yahoo 强制合并成季线
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ys}?{span}&interval={interval}"
    res = _get(url, ttl)["chart"]["result"]
    if not res:
        raise ValueError("no data")
    return res[0]


def quote(sym):
    r = _chart(sym, "1d", "1d", 8)
    m = r["meta"]
    price = m["regularMarketPrice"]
    prev = m.get("chartPreviousClose") or m.get("previousClose") or price
    return {"sym": sym, "name": m.get("shortName") or m.get("longName") or sym, "price": price, "prev": prev,
            "change": price - prev, "pct": (price / prev - 1) * 100 if prev else 0,
            "high": m.get("regularMarketDayHigh") or price, "low": m.get("regularMarketDayLow") or price,
            "open": next((x for x in reversed(r["indicators"]["quote"][0].get("open") or []) if x), price),
            "volume": m.get("regularMarketVolume") or 0}


def quotes(symbols):
    def one(s):
        try:
            return quote(s)
        except Exception:
            return None
    with ThreadPoolExecutor(8) as ex:
        return [q for q in ex.map(one, symbols) if q]


# 周期 -> (Yahoo 取数范围, Yahoo 间隔, 缓存秒数)。Yahoo 没有 4 小时和年K,由我们自己合成。
PERIODS = {
    "D": ("10y", "1d", 60), "W": ("max", "1wk", 300), "M": ("max", "1mo", 300), "Q": ("max", "3mo", 300),
    "Y": ("max", "1mo", 300),
    "1m": ("7d", "1m", 15), "5m": ("60d", "5m", 15), "15m": ("60d", "15m", 15),
    "1h": ("730d", "60m", 30), "4h": ("730d", "60m", 30),
}
INTRADAY = {"1m", "5m", "15m", "1h", "4h"}


def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    first = d + datetime.timedelta(days=(6 - d.weekday()) % 7)
    return first + datetime.timedelta(weeks=n - 1)


def _ny(ts):
    """把时间戳转成纽约当地时间(自带夏令时规则,不依赖系统时区库)。"""
    u = datetime.datetime.utcfromtimestamp(ts)
    start = datetime.datetime.combine(_nth_sunday(u.year, 3, 2), datetime.time(7, 0))   # 3月第2个周日 2:00 EST
    end = datetime.datetime.combine(_nth_sunday(u.year, 11, 1), datetime.time(6, 0))    # 11月第1个周日 2:00 EDT
    return u + datetime.timedelta(hours=-4 if start <= u < end else -5)


def _agg(bars, keyfn):
    out, key = [], None
    for b in bars:
        k = keyfn(b)
        if k != key:
            out.append(dict(b)); key = k
        else:
            c = out[-1]
            c["h"] = max(c["h"], b["h"]); c["l"] = min(c["l"], b["l"]); c["c"] = b["c"]; c["v"] += b["v"]
    return out


def _bars(r, period):
    off = r["meta"].get("gmtoffset", 0)
    q = r["indicators"]["quote"][0]
    intra = period in INTRADAY
    out = []
    for i, t in enumerate(r.get("timestamp") or []):
        o, h, l, c, v = (q[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c):
            continue
        if intra and not v and h == l:      # 去掉 Yahoo 在收盘时附带的空K线(成交量为0、没有波动)
            continue
        d = _ny(t) if intra else datetime.datetime.utcfromtimestamp(t + off)
        out.append({"t": d.strftime("%Y-%m-%d %H:%M" if intra else "%Y-%m-%d"),
                    "o": round(o, 4), "h": round(h, 4), "l": round(l, 4), "c": round(c, 4), "v": int(v or 0)})
    if period == "4h":      # 美股一天 6.5 小时:9:30-13:30 为一根,13:30-收盘为一根
        out = _agg(out, lambda b: b["t"][:10] + ("A" if b["t"][11:] < "13:30" else "B"))
    elif period == "Y":
        out = _agg(out, lambda b: b["t"][:4])
    return out


def bars(sym, period):
    rng, interval, ttl = PERIODS[period]
    return {"bars": _bars(_chart(sym, rng, interval, ttl), period)}


def detail(sym):
    """个股详细数据(仿 Moomoo 数据面板)。Yahoo 提供行情类,Finnhub 提供市值/股本/股息等(没有 Key 时这些为空)。"""
    out = {}
    try:
        r = _chart(sym, "1d", "5m", 15)
        m = r["meta"]
        out["wk52h"], out["wk52l"] = m.get("fiftyTwoWeekHigh"), m.get("fiftyTwoWeekLow")
        prev = m.get("chartPreviousClose") or m.get("previousClose")
        hi, lo = m.get("regularMarketDayHigh"), m.get("regularMarketDayLow")
        if prev and hi and lo:
            out["amp"] = (hi - lo) / prev * 100
        tv = vol = 0
        q = r["indicators"]["quote"][0]
        for i in range(len(r.get("timestamp") or [])):
            h_, l_, c_, v_ = q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
            if None in (h_, l_, c_) or not v_:
                continue
            tv += (h_ + l_ + c_) / 3 * v_; vol += v_
        if vol:
            out["avg"], out["turnover"] = tv / vol, tv     # 平均价(成交量加权)、成交额(估算)
        out["volume"] = m.get("regularMarketVolume") or vol
    except Exception:
        pass
    try:
        mb = bars(sym, "M")["bars"]
        if mb:
            out["ath"], out["atl"] = max(b["h"] for b in mb), min(b["l"] for b in mb)
    except Exception:
        pass
    if sym in ALIAS:      # 指数、期货、加密货币没有公司资料
        return out
    try:
        met = (_fh("stock/metric", {"symbol": sym, "metric": "all"}, 3600) or {}).get("metric", {})
        pro = _fh("stock/profile2", {"symbol": sym}, 3600) or {}
        sh = pro.get("shareOutstanding")                      # 单位:百万股
        if pro.get("marketCapitalization"):
            out["mcap"] = pro["marketCapitalization"] * 1e6   # 单位:百万美元 -> 美元
        if sh:
            out["shares"] = sh * 1e6
            if out.get("volume"):
                out["turnoverRate"] = out["volume"] / (sh * 1e6) * 100
        avgv = met.get("10DayAverageTradingVolume")           # 单位:百万股
        if avgv and out.get("volume"):
            out["volRatio"] = out["volume"] / (avgv * 1e6)
        if met.get("dividendYieldIndicatedAnnual") is not None:
            out["divYield"] = met["dividendYieldIndicatedAnnual"]
        if met.get("peTTM") is not None:
            out["pe"] = met["peTTM"]
    except Exception:
        pass
    return out


def company(sym):
    """公司资料、竞争对手、分析师评级分布、财报对比(Finnhub 免费接口,需要 Key)。部分接口失败时对应字段为 None。"""
    if not os.environ.get("FINNHUB_KEY") and not os.environ.get("FMP_KEY"):
        return {"error": "no_key"}
    out = {}
    for key, path, params in [("profile", "stock/profile2", {"symbol": sym}), ("peers", "stock/peers", {"symbol": sym}),
                              ("rec", "stock/recommendation", {"symbol": sym}), ("earn", "stock/earnings", {"symbol": sym, "limit": 4})]:
        try:
            out[key] = _fh(path, params, 3600)
        except Exception:
            out[key] = None
    # 目标价和机构评级变动:FMP 免费接口(需要 FMP_KEY)
    out["target"] = _fmp_target(sym)
    out["grades"] = _fmp_grades(sym)
    if not out["target"] or not out["grades"]:        # FMP 免费版不覆盖的股票,改用 Yahoo(不需要 Key)
        y = _yh_summary(sym)
        out["target"] = out["target"] or (y or {}).get("target")
        out["grades"] = out["grades"] or (y or {}).get("grades")
    out["backlog"] = _sec_backlog(sym)
    return out


def _fmp(path, params, ttl):
    key = os.environ.get("FMP_KEY")
    if not key:
        return None
    params = dict(params, apikey=key)
    return _get("https://financialmodelingprep.com/stable/" + path + "?" + urllib.parse.urlencode(params), ttl)


def _fmp_target(sym):
    try:
        c = _fmp("price-target-consensus", {"symbol": sym}, 3600)
        m = _fmp("price-target-summary", {"symbol": sym}, 3600)
        c = c[0] if c else None
        m = m[0] if m else None
        if not c:
            DBG["target"] = f"{sym}: 空结果 {str(c)[:60]}"
            return None
        return {"high": c.get("targetHigh"), "low": c.get("targetLow"), "avg": c.get("targetConsensus"), "median": c.get("targetMedian"),
                "n": (m or {}).get("lastQuarterCount"), "avgQ": (m or {}).get("lastQuarterAvgPriceTarget")}
    except Exception as e:
        DBG["target"] = f"{sym}: {type(e).__name__}: {str(e)[:60]}"
        return None


def _fmp_grades(sym):
    try:
        d = _fmp("grades", {"symbol": sym, "limit": 30}, 3600) or []
        return [{"date": x.get("date"), "firm": x.get("gradingCompany"), "from": x.get("previousGrade"), "to": x.get("newGrade"),
                 "action": x.get("action")} for x in d[:12]]
    except Exception as e:
        DBG["grades"] = f"{sym}: {type(e).__name__}: {str(e)[:60]}"
        return None


_yh = {"op": None, "crumb": None, "t": 0}


def _yh_open(url):
    import http.cookiejar
    if not _yh["op"] or time.time() - _yh["t"] > 3000:        # Yahoo 需要先拿一个临时的 crumb
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        op.addheaders = list(UA.items())
        try:
            op.open("https://fc.yahoo.com", timeout=10)
        except Exception:
            pass
        _yh["crumb"] = op.open("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10).read().decode()
        _yh["op"], _yh["t"] = op, time.time()
    return json.load(_yh["op"].open(url + "&crumb=" + urllib.parse.quote(_yh["crumb"]), timeout=15))


def _yh_summary(sym):
    """Yahoo 的分析师目标价和评级变动(非官方接口,可能随时变动)。ETF 或没人覆盖的股票返回 None。"""
    hit = _cache.get("yh:" + sym)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    try:
        d = _yh_open(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(sym)}?modules=financialData,upgradeDowngradeHistory")
        r = d["quoteSummary"]["result"][0]
        fd = r.get("financialData") or {}
        raw = lambda k: (fd.get(k) or {}).get("raw")
        target = None
        if raw("targetMeanPrice"):
            target = {"high": raw("targetHighPrice"), "low": raw("targetLowPrice"), "avg": raw("targetMeanPrice"),
                      "median": raw("targetMedianPrice"), "n": raw("numberOfAnalystOpinions"), "avgQ": None}
        act = {"up": "upgrade", "down": "downgrade", "main": "maintain", "init": "initialize", "reit": "reiterate"}
        h = sorted((r.get("upgradeDowngradeHistory") or {}).get("history", []), key=lambda x: x.get("epochGradeDate", 0), reverse=True)[:12]
        grades = [{"date": time.strftime("%Y-%m-%d", time.gmtime(x["epochGradeDate"])), "firm": x.get("firm"), "from": x.get("fromGrade") or None,
                   "to": x.get("toGrade"), "action": act.get(x.get("action"), x.get("action"))} for x in h] or None
        out = {"target": target, "grades": grades}
    except Exception as e:
        DBG["yahoo"] = f"{sym}: {type(e).__name__}: {str(e)[:60]}"
        out = None
    _cache["yh:" + sym] = (time.time(), out)
    return out


def _sec_backlog(sym):
    """在手订单(剩余履约义务 RPO):来自 SEC 官方财报数据。只有部分公司披露;查不到返回 None。需要环境变量 SEC_CONTACT(联系邮箱)。"""
    contact = (os.environ.get("SEC_CONTACT") or "").strip().strip("\"'“”‘’ ")      # 去掉粘贴时可能带进来的引号
    if not contact or sym in ALIAS:
        return None
    if not contact.isascii():
        DBG["sec"] = "SEC_CONTACT 里有非英文字符,请用英文直引号重新设置"
        return None
    h = {"User-Agent": "StocksMonitor " + contact}
    try:
        tk = _get("https://www.sec.gov/files/company_tickers.json", 86400, h)
        cik = next((v["cik_str"] for v in tk.values() if v["ticker"] == sym.replace("-", ".")), None)
        if cik is None:
            DBG["sec"] = f"{sym}: 在 SEC 代码表里找不到"
            return None
        d = _get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{int(cik):010d}/us-gaap/RevenueRemainingPerformanceObligation.json", 21600, h)
        rows = {}
        for x in d["units"].get("USD", []):
            rows[x["end"]] = {"end": x["end"], "val": x["val"], "form": x.get("form")}
        last = sorted(rows.values(), key=lambda r: r["end"])[-5:]
        return last or None
    except Exception as e:
        DBG["sec"] = f"{sym}: {type(e).__name__}: {str(e)[:60]}"
        return None


def movers():
    """全市场涨幅榜 / 跌幅榜 / 成交最活跃(FMP)。过滤掉股价低于 5 美元的小壳股和非美股交易所。"""
    if not os.environ.get("FMP_KEY"):
        return {"error": "no_key"}
    out = {}
    for key, path in [("gainers", "biggest-gainers"), ("losers", "biggest-losers"), ("actives", "most-actives")]:
        try:
            d = _fmp(path, {}, 120) or []
        except Exception:
            d = []
        rows = [x for x in d if (x.get("price") or 0) >= 5 and x.get("exchange") in ("NASDAQ", "NYSE", "AMEX")]
        out[key] = {"total": len(d), "items": [{"sym": x["symbol"], "name": x.get("name", ""), "price": x["price"], "pct": x.get("changesPercentage"),
                                                 "change": x.get("change")} for x in rows[:10]]}
    return out


def _fh(path, params, ttl):
    key = os.environ.get("FINNHUB_KEY")
    if not key:
        return None
    params = dict(params, token=key)
    return _get("https://finnhub.io/api/v1/" + path + "?" + urllib.parse.urlencode(params), ttl)


def news(sym):
    today = datetime.date.today()
    if sym:
        d = _fh("company-news", {"symbol": sym, "from": str(today - datetime.timedelta(days=5)), "to": str(today)}, 120)
    else:
        d = _fh("news", {"category": "general"}, 120)
    if d is None:
        return {"error": "no_key", "items": []}
    return {"items": [{"title": x["headline"], "src": x.get("source", ""), "ts": x["datetime"], "url": x.get("url", "")} for x in d[:10]]}


def earnings(date):
    d = _fh("calendar/earnings", {"from": date, "to": date}, 600)
    if d is None:
        return {"error": "no_key", "items": []}
    rows = sorted(d.get("earningsCalendar", []), key=lambda x: x.get("revenueEstimate") or 0, reverse=True)[:45]

    def cur(sym):       # 公司的财报币种(Finnhub 公司资料里的 currency),查不到就当作美元
        try:
            return (_fh("stock/profile2", {"symbol": sym}, 86400) or {}).get("currency") or "USD"
        except Exception:
            return "USD"
    with ThreadPoolExecutor(6) as ex:
        curs = list(ex.map(cur, [x["symbol"] for x in rows]))
    hour = {"bmo": "盘前", "amc": "盘后", "dmh": "盘中"}
    return {"items": [{"sym": x["symbol"], "when": hour.get(x.get("hour"), "盘后"), "eps": x.get("epsEstimate"),
                       "rev": x.get("revenueEstimate"), "cur": c} for x, c in zip(rows, curs)]}


# ---- 路由:本地服务器和 Vercel 共用 ----
def route(name, q):
    """返回 (状态码, 数据, 缓存秒数)。缓存可减少对 Yahoo / Finnhub 的请求,保护免费额度。"""
    try:
        if name == "quotes":
            syms = [s.strip().upper() for s in q.get("symbols", "").split(",") if s.strip()][:60]
            return 200, quotes(syms), 5
        if name == "bars":
            period = q.get("period", "D")
            if period not in PERIODS:
                return 400, {"error": "bad period"}, 0
            return 200, bars(q["symbol"].upper(), period), PERIODS[period][2]
        if name == "news":
            return 200, news(q.get("symbol", "").upper()), 120
        if name == "earnings":
            datetime.date.fromisoformat(q["date"])      # 校验日期格式
            return 200, earnings(q["date"]), 600
        if name == "movers":
            return 200, movers(), 120
        if name == "company":
            return 200, company(q["symbol"].upper()), 600
        if name == "detail":
            return 200, detail(q["symbol"].upper()), 15
        if name == "status":
            return 200, {"finnhub": bool(os.environ.get("FINNHUB_KEY")), "fmp": bool(os.environ.get("FMP_KEY")), "sec": bool(os.environ.get("SEC_CONTACT")), "dbg": DBG}, 0
        return 404, {"error": "not found"}, 0
    except Exception as e:
        # 只返回错误类型和简短说明(urllib 的错误信息不含网址和密钥),方便排查
        return 500, {"error": "server error", "detail": f"{type(e).__name__}: {str(e)[:80]}"}, 0
