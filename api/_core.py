"""数据后台的核心逻辑(只用 Python 自带库,无需安装任何东西)。
- 行情/K线:Yahoo 财经(非官方接口,不需要 Key)
- 新闻/财报日历:Finnhub(环境变量 FINNHUB_KEY);目标价/评级变动/涨跌榜:FMP(环境变量 FMP_KEY)。Key 只在终端或 Vercel 环境变量里设置,不写入任何文件
"""
import re, json, os, time, datetime, urllib.request, urllib.parse
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


def sec_cik(tk, sym):
    """SEC 代码表里 BRK-B 写作 BRK-B,而别处有时写 BRK.B:两种写法都认。"""
    names = {sym, sym.replace("-", "."), sym.replace(".", "-")}
    return next((v["cik_str"] for v in tk.values() if v["ticker"] in names), None)


def quote(sym):
    r = _chart(sym, "1d", "1d", 8)
    m = r["meta"]
    price = m["regularMarketPrice"]
    prev = m.get("chartPreviousClose") or m.get("previousClose") or price
    return {"sym": sym, "name": m.get("shortName") or m.get("longName") or sym, "price": price, "prev": prev,
            "change": price - prev, "pct": (price / prev - 1) * 100 if prev else 0,
            "high": m.get("regularMarketDayHigh") or price, "low": m.get("regularMarketDayLow") or price,
            "open": next((x for x in reversed(r["indicators"]["quote"][0].get("open") or []) if x), price),
            "volume": m.get("regularMarketVolume") or 0,
            "asof": m.get("regularMarketTime")}          # 这条报价对应的交易所时间(Unix 秒),页面用它判断是不是旧数据


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
    if True:        # Yahoo(不需要 Key):补 FMP 免费版不覆盖的股票,并提供英文公司简介
        y = _yh_summary(sym)
        out["about"] = (y or {}).get("about")
        out["rec"] = out.get("rec") or (y or {}).get("rec")
        out["etf"] = (y or {}).get("etf")
        out["target"] = out["target"] or (y or {}).get("target")
        out["grades"] = out["grades"] or (y or {}).get("grades")
    out["backlog"] = _sec_backlog(sym)
    out["extra"] = _yh_extra(sym)
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


def _yh_session():
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
    return _yh["op"], _yh["crumb"]


def _yh_open(url):
    op, crumb = _yh_session()
    return json.load(op.open(url + "&crumb=" + urllib.parse.quote(crumb), timeout=15))


US_EX = ("NMS", "NYQ", "NGM", "NCM", "ASE", "PCX")


def _yh_screen(conds, sort, desc=True, size=30, ttl=240):
    """Yahoo 股票筛选器(美股、按条件排序)。conds 是额外条件;返回精简后的行情列表。"""
    key = "scr:" + json.dumps([conds, sort, desc, size], sort_keys=True)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    ops = [{"operator": "eq", "operands": ["region", "us"]}, {"operator": "or", "operands": [{"operator": "eq", "operands": ["exchange", e]} for e in US_EX]}] + conds
    body = {"size": size, "offset": 0, "sortField": sort, "sortType": "DESC" if desc else "ASC", "quoteType": "EQUITY", "topOperator": "AND",
            "query": {"operator": "AND", "operands": ops}, "userId": "", "userIdType": "guid"}
    op, crumb = _yh_session()
    req = urllib.request.Request("https://query1.finance.yahoo.com/v1/finance/screener?lang=en-US&region=US&formatted=false&crumb=" + urllib.parse.quote(crumb),
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    q = json.load(op.open(req, timeout=15))["finance"]["result"][0]
    out = [{"sym": x["symbol"], "name": x.get("shortName") or x.get("longName") or x["symbol"], "price": x.get("regularMarketPrice"),
            "pct": x.get("regularMarketChangePercent"), "vol": x.get("regularMarketVolume"), "cap": x.get("marketCap"), "pe": x.get("trailingPE"), "fpe": x.get("forwardPE")} for x in q.get("quotes", []) if not re.search(r"-P[A-Z]?$", x["symbol"])]      # 去掉优先股
    _cache[key] = (time.time(), out)
    return out


# 20 个板块:前 11 个是 Yahoo 的行业大类(sector),后 9 个是细分行业(industry)
SECTOR_DEFS = [("科技", "sector", "Technology"), ("通信与传媒", "sector", "Communication Services"), ("可选消费", "sector", "Consumer Cyclical"),
               ("必需消费", "sector", "Consumer Defensive"), ("医疗健康", "sector", "Healthcare"), ("金融", "sector", "Financial Services"),
               ("工业", "sector", "Industrials"), ("能源", "sector", "Energy"), ("公用事业", "sector", "Utilities"), ("房地产", "sector", "Real Estate"),
               ("基础材料", "sector", "Basic Materials"),
               ("半导体", "industry", "Semiconductors"), ("半导体设备", "industry", "Semiconductor Equipment & Materials"), ("AI 硬件/存储", "industry", "Computer Hardware"),
               ("生物科技", "industry", "Biotechnology"), ("航空航天与国防", "industry", "Aerospace & Defense"), ("汽车整车", "industry", "Auto Manufacturers"),
               ("电商零售", "industry", "Internet Retail"), ("投行与券商", "industry", "Capital Markets"), ("医疗器械", "industry", "Medical Devices")]


def sectors(n=10, only=None, ttl=600):
    """每个板块取市值最大的 n 只美股(含在美上市的 ADR)。only 指定板块名时只取这一个(详情页用)。"""
    defs = [d for d in SECTOR_DEFS if only is None or d[0] == only]
    def one(d):
        name, field, val = d
        try:
            rows = _yh_screen([{"operator": "eq", "operands": [field, val]}, {"operator": "gt", "operands": ["intradaymarketcap", 2e9]}], "intradaymarketcap", True, n, ttl)
        except Exception as e:
            DBG["sectors"] = f"{name}: {type(e).__name__}"
            rows = []
        return {"name": name, "items": rows}
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(one, defs))
    return {"sectors": res}


SCREEN_SECTORS = {"Technology", "Communication Services", "Consumer Cyclical", "Consumer Defensive", "Healthcare", "Financial Services", "Industrials", "Energy", "Utilities", "Real Estate", "Basic Materials"}
SCREEN_INDUSTRIES = {d[2] for d in SECTOR_DEFS if d[1] == "industry"} | {"Credit Services", "Gold", "Airlines", "Restaurants", "Specialty Retail", "Internet Content & Information", "Communication Equipment",
                     "Insurance Brokers", "Oil & Gas Integrated", "Telecom Services", "Entertainment", "Information Technology Services", "Railroads"}


def screen(q):
    """条件筛选:行业(大类/细分)+ 市值范围 + 排序 + 估值上限 + 只要盈利公司。返回最多 30 只。"""
    conds = [{"operator": "gt", "operands": ["intradayprice", 1]}]
    sec, ind = q.get("sector", ""), q.get("industry", "")
    if sec:
        if sec not in SCREEN_SECTORS:
            return {"error": "bad sector"}
        conds.append({"operator": "eq", "operands": ["sector", sec]})
    if ind:
        if ind not in SCREEN_INDUSTRIES:
            return {"error": "bad industry"}
        conds.append({"operator": "eq", "operands": ["industry", ind]})
    try:
        lo, hi = float(q.get("cmin") or 2e9), float(q.get("cmax") or 1e14)
        pemax = float(q.get("pemax") or 0)
    except ValueError:
        return {"error": "bad number"}
    conds.append({"operator": "btwn", "operands": ["intradaymarketcap", max(lo, 3e8), hi]})
    if pemax > 0 or q.get("profit") == "1":
        conds.append({"operator": "btwn", "operands": ["peratio.lasttwelvemonths", 0.1, pemax if pemax > 0 else 1e6]})
    sort = {"cap": ("intradaymarketcap", True), "pct": ("percentchange", True), "pctdown": ("percentchange", False), "vol": ("dayvolume", True),
            "pe": ("peratio.lasttwelvemonths", False)}.get(q.get("sort", "cap"), ("intradaymarketcap", True))
    if sort[0].startswith("peratio") and not any(c["operands"][0].startswith("peratio") for c in conds):
        conds.append({"operator": "btwn", "operands": ["peratio.lasttwelvemonths", 0.1, 1e6]})
    return {"items": _yh_screen(conds, sort[0], sort[1], 30, 180)}


def movers():
    """全市场涨幅榜 / 跌幅榜 / 成交最活跃,各 20 只(Yahoo 筛选器,不需要 Key)。过滤掉市值低于 20 亿美元或股价低于 5 美元的小票。"""
    base = [{"operator": "gt", "operands": ["intradaymarketcap", 2e9]}, {"operator": "gt", "operands": ["intradayprice", 5]}]
    out = {}
    for key, sort, desc in [("gainers", "percentchange", True), ("losers", "percentchange", False), ("actives", "dayvolume", True)]:
        try:
            rows = _yh_screen(base, sort, desc, 20, 120)
        except Exception as e:
            DBG["movers"] = f"{key}: {type(e).__name__}"
            rows = []
        out[key] = {"items": rows}
    return out


def _zh(text):
    """英译中(Google 翻译的非官方免费接口,不需要 Key;失败返回 None,页面会显示英文原文)。"""
    try:
        parts, cur = [], ""
        for sent in text.replace("\n", " ").split(". "):
            if len(cur) + len(sent) > 1200 and cur:
                parts.append(cur); cur = ""
            cur += sent + ". "
        parts.append(cur)
        out = []
        for part in parts:
            u = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q=" + urllib.parse.quote(part)
            out.append("".join(x[0] for x in _get(u, 86400)[0]))
        return "".join(out)
    except Exception as e:
        DBG["translate"] = f"{type(e).__name__}: {str(e)[:60]}"
        return None


def _head(t, n=450):
    """只取英文简介开头一小段(在句子结尾处截断),避免翻译又长又慢。"""
    t = t.replace("\n", " ")
    if len(t) <= n:
        return t
    i = t.rfind(". ", 0, n)
    return t[:i + 1] if i > 100 else t[:n]


def _brief(zh, lo=50, hi=110):
    """把中文简介压缩到一两句话(和手写的那 36 家风格一致)。"""
    if not zh:
        return None
    out = ""
    for sent in zh.replace("。 ", "。").split("。"):
        if not sent.strip():
            continue
        if out and len(out) + len(sent) > hi:
            break
        out += sent + "。"
        if len(out) >= lo:
            break
    if len(out) > hi + 30:           # 第一句本身就太长:在逗号处截断
        cut = max(out.rfind("，", 0, hi), out.rfind(",", 0, hi))
        out = (out[:cut] if cut > 30 else out[:hi]) + "。"
    return out


def _yh_summary(sym):
    """Yahoo 的分析师目标价和评级变动(非官方接口,可能随时变动)。ETF 或没人覆盖的股票返回 None。"""
    hit = _cache.get("yh:" + sym)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    try:
        d = _yh_open(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(sym)}?modules=financialData,upgradeDowngradeHistory,assetProfile,recommendationTrend,topHoldings")
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
        ap = r.get("assetProfile") or {}
        about = {"summary": ap.get("longBusinessSummary"), "sector": ap.get("sector"), "industry": ap.get("industry"),
                 "employees": ap.get("fullTimeEmployees"), "zh": _brief(_zh(_head(ap.get("longBusinessSummary") or "")))} if ap.get("longBusinessSummary") else None
        rt = (r.get("recommendationTrend") or {}).get("trend") or []
        rec = [{"period": time.strftime("%Y-%m"), **{k: rt[0].get(k) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}}] if rt else None
        th = r.get("topHoldings") or {}
        etf = [{"sym": x.get("symbol"), "name": x.get("holdingName"), "pct": (x.get("holdingPercent") or {}).get("raw")} for x in th.get("holdings", [])] or None
        out = {"target": target, "grades": grades, "about": about, "rec": rec, "etf": etf}
    except Exception as e:
        DBG["yahoo"] = f"{sym}: {type(e).__name__}: {str(e)[:60]}"
        out = None
    _cache["yh:" + sym] = (time.time(), out)
    return out


def _yh_extra(sym):
    """Yahoo:关键指标(做空/估值)、机构持仓、内部人交易、盈利预测、近期事件。ETF 等没有的部分为空。"""
    hit = _cache.get("yx:" + sym)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    ms = "defaultKeyStatistics,majorHoldersBreakdown,institutionOwnership,insiderTransactions,earningsTrend,calendarEvents,netSharePurchaseActivity"
    try:
        r = _yh_open(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(sym)}?modules={ms}")["quoteSummary"]["result"][0]
        g = lambda d, k: ((d or {}).get(k) or {}).get("raw") if isinstance((d or {}).get(k), dict) else None
        ks, mh = r.get("defaultKeyStatistics") or {}, r.get("majorHoldersBreakdown") or {}
        stats = {k: g(ks, k) for k in ("shortPercentOfFloat", "sharesShort", "shortRatio", "forwardPE", "pegRatio", "profitMargins", "beta", "floatShares", "priceToBook", "trailingEps", "forwardEps")}
        stats = stats if any(v is not None for v in stats.values()) else None
        top = [{"org": x.get("organization"), "pct": g(x, "pctHeld"), "chg": g(x, "pctChange")} for x in ((r.get("institutionOwnership") or {}).get("ownershipList") or [])[:5]]
        holders = {"insiders": g(mh, "insidersPercentHeld"), "inst": g(mh, "institutionsPercentHeld"), "count": g(mh, "institutionsCount"), "top": top} if (top or g(mh, "institutionsPercentHeld") is not None) else None
        ns = r.get("netSharePurchaseActivity") or {}
        tx = sorted((r.get("insiderTransactions") or {}).get("transactions") or [], key=lambda x: g(x, "startDate") or 0, reverse=True)[:8]
        insiders = {"net": {"period": ns.get("period"), "buy": g(ns, "buyInfoShares"), "sell": g(ns, "sellInfoShares"), "buyN": g(ns, "buyInfoCount"), "sellN": g(ns, "sellInfoCount")} if ns else None,
                    "list": [{"name": x.get("filerName"), "rel": x.get("filerRelation"), "text": x.get("transactionText"), "shares": g(x, "shares"), "value": g(x, "value"),
                              "date": ((x.get("startDate") or {}).get("fmt"))} for x in tx]} if (tx or ns) else None
        names = {"0q": "本季度", "+1q": "下季度", "0y": "本财年", "+1y": "下财年"}
        trend = []
        for t in (r.get("earningsTrend") or {}).get("trend") or []:
            if t.get("period") in names:
                e, v = t.get("earningsEstimate") or {}, t.get("revenueEstimate") or {}
                trend.append({"label": names[t["period"]], "end": t.get("endDate"), "eps": g(e, "avg"), "epsLow": g(e, "low"), "epsHigh": g(e, "high"), "epsGrowth": g(e, "growth"),
                              "rev": g(v, "avg"), "revGrowth": g(v, "growth"), "n": g(e, "numberOfAnalysts")})
        ce = r.get("calendarEvents") or {}
        ed = (ce.get("earnings") or {}).get("earningsDate") or []
        events = {"earn": (ed[0] or {}).get("fmt") if ed else None, "earnEst": (ce.get("earnings") or {}).get("isEarningsDateEstimate"),
                  "exDiv": (ce.get("exDividendDate") or {}).get("fmt"), "div": (ce.get("dividendDate") or {}).get("fmt")}
        events = events if any(events.values()) else None
        out = {"stats": stats, "holders": holders, "insiders": insiders, "trend": trend or None, "events": events}
    except Exception as e:
        DBG["yahoo_extra"] = f"{sym}: {type(e).__name__}: {str(e)[:60]}"
        out = None
    _cache["yx:" + sym] = (time.time(), out)
    return out


# FRED 宏观数据:(代码, 名称, 单位, 变换, 取多少期画走势)
MACRO = [("DGS10", "10年期美债收益率", "%", None, 90), ("PAYEMS", "非农新增就业", "千人", "chg", 24), ("UNRATE", "失业率", "%", None, 24),
         ("CPIAUCSL", "CPI 通胀(同比)", "%", "pc1", 24), ("FEDFUNDS", "联邦基金利率", "%", None, 24)]
# 未来预期:美联储官员每季度发布的经济预测(FOMC 经济预测摘要,中位数)和市场隐含通胀,都来自 FRED。取不到的就不显示。
EXPECT = {"DGS10": [("T10YIE", "市场隐含的未来 10 年平均通胀", "latest"), ("FEDTARMDLR", "官员预测的长期利率(中性水平)", "latest")],
          "UNRATE": [("UNRATEMD", "官员预测的年底失业率(中位数)", "years")],
          "CPIAUCSL": [("PCECTPIMD", "官员预测的年底 PCE 通胀(中位数,美联储盯的是 PCE)", "years"), ("T10YIE", "市场隐含的未来 10 年平均通胀", "latest")],
          "FEDFUNDS": [("FEDTARMD", "官员预测的年底利率(中位数)", "years"), ("FEDTARMDLR", "官员预测的长期利率(中性水平)", "latest")]}
RELEASES = {"Consumer Price Index": "CPI 通胀数据", "Employment Situation": "非农就业报告", "Gross Domestic Product": "GDP",
            "Personal Income and Outlays": "PCE 通胀数据", "Producer Price Index": "PPI 生产者物价", "Advance Monthly Sales for Retail": "零售销售",
            "Job Openings and Labor Turnover": "JOLTS 职位空缺"}


def _fred(path, params, ttl):
    key = os.environ.get("FRED_KEY")
    if not key:
        return None
    return _get("https://api.stlouisfed.org/fred/" + path + "?" + urllib.parse.urlencode(dict(params, api_key=key, file_type="json")), ttl)


# ---- 经济日历:经济数据发布日(FRED 发布日程)+ FOMC 会议(美联储官网日程) ----
# FOMC:(会议第一天, 公布决议的那天, 是否同时发布经济预测)。来自美联储官网 https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# (页面 2026-11-18 更新)。页面写明:每次会议日期在上一次会议确认前都是暂定的;会议纪要在决议后三周公布;2027 年页面还没标出哪些会议带经济预测。
FOMC = [("2026-01-27", "2026-01-28", False), ("2026-03-17", "2026-03-18", True), ("2026-04-28", "2026-04-29", False), ("2026-06-16", "2026-06-17", True),
        ("2026-07-28", "2026-07-29", False), ("2026-09-15", "2026-09-16", True), ("2026-10-27", "2026-10-28", False), ("2026-12-08", "2026-12-09", True),
        ("2027-01-26", "2027-01-27", False), ("2027-03-16", "2027-03-17", False), ("2027-04-27", "2027-04-28", False), ("2027-06-08", "2027-06-09", False),
        ("2027-07-27", "2027-07-28", False), ("2027-09-14", "2027-09-15", False), ("2027-10-26", "2027-10-27", False), ("2027-11-16", "2027-11-17", False),
        ("2028-01-25", "2028-01-26", False)]
# (FRED 发布名里的关键词, 代号, 中文名, 重要程度 3 高 / 2 中, 大白话说明)
ECON = [("Consumer Price Index", "cpi", "CPI 通胀数据", 3, "衡量物价同比涨了多少,是美联储决定加息还是降息最看重的数据之一。"),
        ("Employment Situation", "jobs", "非农就业报告", 3, "上个月新增了多少非农就业岗位、失业率是多少,反映经济和就业市场的冷热。"),
        ("Gross Domestic Product", "gdp", "GDP", 3, "衡量整个经济增长了多少。同一个季度会先后公布初值和修正值,数字可能被修正。"),
        ("Personal Income and Outlays", "pce", "PCE 通胀数据", 3, "美联储真正盯的通胀指标 PCE 就在这份报告里,同时还有居民收入和消费。"),
        ("Producer Price Index", "ppi", "PPI 生产者物价", 2, "企业买进原材料和商品的价格变化,常被看作 CPI 的先行信号。"),
        ("Advance Monthly Sales for Retail", "retail", "零售销售", 2, "消费者花了多少钱。消费是美国经济最大的引擎,这个数据反映它的强弱。"),
        ("Job Openings and Labor Turnover", "jolts", "JOLTS 职位空缺", 2, "企业有多少空缺职位,用来看就业市场有多紧张。")]
ECON_SPAN_MAX = 62


def fomc_events(frm, to):
    out = []
    for a, b, sep in FOMC:
        if frm <= b <= to:
            out.append({"date": b, "key": "fomc", "name": "FOMC 利率决议", "imp": 3, "src": "美联储官网",
                        "desc": f"美联储开两天会议({a[5:]} 至 {b[5:]}),这天公布是否调整利率" + (";同时发布经济预测摘要(含点阵图)。" if sep else "。") + "会议日期在上一次会议确认前都是暂定的。"})
        m = (datetime.date.fromisoformat(b) + datetime.timedelta(days=21)).isoformat()      # 美联储规则:纪要在决议后三周公布
        if frm <= m <= to:
            out.append({"date": m, "key": "fomc_min", "name": "FOMC 会议纪要", "imp": 2, "src": "美联储官网(按三周规则推算)",
                        "desc": f"{b[5:]} 那次会议的详细记录,会透露官员们有哪些分歧、倾向往哪走。"})
    return out


def _fred_release_dates(frm, to):
    rows = []
    for off in range(0, 3000, 1000):
        d = _fred("releases/dates", {"realtime_start": frm, "realtime_end": to, "include_release_dates_with_no_data": "true",
                                     "order_by": "release_date", "sort_order": "asc", "limit": 1000, "offset": off}, 3600)
        if d is None:
            return None
        got = d.get("release_dates", [])
        rows += got
        if len(got) < 1000:
            break
    return rows


def econ(frm, to):
    """经济日历:返回 [frm, to] 之间的经济事件。FRED 取不到时仍返回 FOMC,并用 fred 字段说明。"""
    items = fomc_events(frm, to)
    fred_ok = True
    try:
        rows = _fred_release_dates(frm, to)
        if rows is None:
            fred_ok = False
        else:
            seen = set()
            for x in rows:
                nm = (x.get("release_name") or "")
                if "fomc" in nm.lower():
                    continue                                                   # FOMC 以美联储官网日程为准
                hit = next((e for e in ECON if e[0].lower() in nm.lower()), None)
                d = x.get("date") or ""
                if hit and frm <= d <= to and (d, hit[1]) not in seen:
                    seen.add((d, hit[1]))
                    items.append({"date": d, "key": hit[1], "name": hit[2], "imp": hit[3], "desc": hit[4], "src": "FRED(圣路易斯联储)发布日程"})
    except Exception as e:
        DBG["econ"] = f"{type(e).__name__}: {str(e)[:60]}"
        fred_ok = False
    items.sort(key=lambda i: (i["date"], -i["imp"], i["name"]))
    return {"items": items, "fred": fred_ok, "from": frm, "to": to}


def macro():
    if not os.environ.get("FRED_KEY"):
        return {"error": "no_key"}

    def one(m):
        sid, name, unit, tr, n = m
        try:
            p = {"series_id": sid, "sort_order": "desc", "limit": n + 5}
            if tr:
                p["units"] = tr
            obs = [o for o in _fred("series/observations", p, 3600)["observations"] if o["value"] != "."][:n]
            vals = [float(o["value"]) for o in reversed(obs)]
            return {"id": sid, "name": name, "unit": unit, "date": obs[0]["date"], "value": vals[-1], "prev": vals[-2] if len(vals) > 1 else None, "hist": vals}
        except Exception as e:
            DBG["fred_" + sid] = f"{type(e).__name__}: {str(e)[:60]}"
            return None
    def expect(spec):
        sid, label, mode = spec
        try:
            obs = [o for o in _fred("series/observations", {"series_id": sid, "sort_order": "desc", "limit": 8}, 21600)["observations"] if o["value"] != "."]
            if not obs:
                return None
            if mode == "latest":
                return {"label": label, "points": [{"k": obs[0]["date"], "v": float(obs[0]["value"])}]}
            this = str(datetime.date.today().year)
            pts = sorted(({"k": o["date"][:4], "v": float(o["value"])} for o in obs if o["date"][:4] >= this), key=lambda p: p["k"])[:4]
            return {"label": label, "points": pts} if pts else None
        except Exception as e:
            DBG["fred_exp_" + sid] = f"{type(e).__name__}: {str(e)[:60]}"
            return None
    with ThreadPoolExecutor(4) as ex:
        items = [x for x in ex.map(one, MACRO) if x]
        specs = [(m[0], s) for m in MACRO for s in EXPECT.get(m[0], [])]
        res = list(ex.map(lambda ms: (ms[0], expect(ms[1])), specs))
    for it in items:
        it["expect"] = [r for k, r in res if k == it["id"] and r]
    cal = []
    try:
        today = datetime.date.today()
        d = _fred("releases/dates", {"realtime_start": str(today), "realtime_end": str(today + datetime.timedelta(days=35)), "include_release_dates_with_no_data": "true",
                                      "order_by": "release_date", "sort_order": "asc", "limit": 1000}, 3600)
        seen, cnt = set(), {}
        for x in d.get("release_dates", []):
            zh = next((v for k, v in RELEASES.items() if k.lower() in (x.get("release_name") or "").lower()), None)
            if zh and x["date"] >= str(today) and (x["date"], zh) not in seen and cnt.get(zh, 0) < 2:   # 去重;每类只列最近两次
                seen.add((x["date"], zh)); cnt[zh] = cnt.get(zh, 0) + 1
                cal.append({"date": x["date"], "name": zh})
    except Exception as e:
        DBG["fred_cal"] = f"{type(e).__name__}: {str(e)[:60]}"
    return {"items": items, "calendar": cal[:12], "dbg": {k: v for k, v in DBG.items() if k.startswith("fred")}}


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
        cik = sec_cik(tk, sym)
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


def _yh_caps(symbols):
    """Yahoo 批量报价(每次最多 50 只):市值、公司全名、财报币种。结果缓存 6 小时。"""
    out, todo = {}, []
    for sym in symbols:
        hit = _cache.get("cap:" + sym)
        if hit and time.time() - hit[0] < 21600:
            out[sym] = hit[1]
        else:
            todo.append(sym)
    for i in range(0, len(todo), 50):
        chunk = todo[i:i + 50]
        try:
            r = _yh_open("https://query2.finance.yahoo.com/v7/finance/quote?symbols=" + ",".join(urllib.parse.quote(x.replace(".", "-")) for x in chunk))
            got = {q["symbol"]: q for q in r["quoteResponse"]["result"]}
        except Exception as e:
            DBG["earn_caps"] = f"{type(e).__name__}: {str(e)[:60]}"
            continue
        for sym in chunk:
            q = got.get(sym.replace(".", "-"))
            info = {"cap": q.get("marketCap") or 0, "name": q.get("longName") or q.get("shortName") or sym,
                    "cur": q.get("financialCurrency") or q.get("currency") or "USD"} if q else {"cap": 0, "name": sym, "cur": "USD"}
            _cache["cap:" + sym] = (time.time(), info)
            out[sym] = info
    return out


EARN_MIN_CAP = 5e9          # 只列市值超过 50 亿美元的公司


def earnings(date):
    d = _fh("calendar/earnings", {"from": date, "to": date}, 600)
    if d is None:
        return {"error": "no_key", "items": []}
    rows = [x for x in d.get("earningsCalendar", []) if x.get("hour") != "dmh"]       # 盘中几乎不发财报,不显示
    caps = _yh_caps([x["symbol"] for x in rows])
    if rows and not any(v["cap"] for v in caps.values()):
        return {"error": "no_cap", "items": []}                                       # 拿不到市值就没法过滤,不乱显示
    keep = sorted((x for x in rows if caps.get(x["symbol"], {}).get("cap", 0) >= EARN_MIN_CAP), key=lambda x: caps[x["symbol"]]["cap"], reverse=True)[:60]
    hour = {"bmo": "盘前", "amc": "盘后"}
    return {"items": [{"sym": x["symbol"], "name": caps[x["symbol"]]["name"], "when": hour.get(x.get("hour"), "盘后"), "eps": x.get("epsEstimate"),
                       "rev": x.get("revenueEstimate"), "cur": caps[x["symbol"]]["cur"], "cap": caps[x["symbol"]]["cap"]} for x in keep]}


def search(q):
    """搜索联想:按代码或公司名,返回相关的美股和 ETF(含杠杆/做空 ETF)。来自 Yahoo 的搜索接口,不需要 Key。"""
    q = (q or "").strip()[:30]
    if not q:
        return {"items": []}
    d = _get("https://query2.finance.yahoo.com/v1/finance/search?" + urllib.parse.urlencode({"q": q, "quotesCount": 10, "newsCount": 0, "listsCount": 0}), 60)
    us = {"NMS", "NYQ", "NGM", "NCM", "PCX", "BTS", "ASE", "NAS", "NYS", "BATS", "CBOE"}
    items = []
    for x in d.get("quotes", []):
        if x.get("quoteType") not in ("EQUITY", "ETF") or x.get("exchange") not in us or not x.get("symbol") or re.search(r"-P[A-Z]?$", x["symbol"]):
            continue
        items.append({"sym": x["symbol"], "name": x.get("shortname") or x.get("longname") or x["symbol"], "type": x["quoteType"], "ex": x.get("exchDisp")})
    return {"items": items[:8]}


# 数据来源清单:页面“数据来源与时间”面板读取它。只写已知事实;没核实的在 note 里标注。
SOURCES = [
    {"k": "行情 / K线 / 分时", "src": "Yahoo Finance(非官方接口)", "delay": "盘中,可能延迟,不保证实时", "note": "每条报价带交易所时间;条款为个人使用口径,见阶段 0 报告"},
    {"k": "涨跌榜 / 板块 / 条件筛选", "src": "Yahoo Finance screener", "delay": "盘中,可能延迟", "note": "仅美股主要交易所"},
    {"k": "分析师目标价 / 升降级", "src": "FMP", "delay": "日更", "note": "需要后台 Key;免费版展示条款待核实"},
    {"k": "新闻 / 公司财报日程", "src": "Finnhub", "delay": "按发布时间", "note": "免费版展示条款待核实"},
    {"k": "经济日历(经济数据发布、FOMC)", "src": "FRED 发布日程;FOMC 取自美联储官网", "delay": "日程提前公布,可能调整", "note": "只有日期,没有具体发布时间;FOMC 日期为暂定"},
    {"k": "宏观指标", "src": "FRED(美联储圣路易斯分行)", "delay": "按各指标发布日(日/月/季)", "note": "部分序列有第三方版权"},
    {"k": "财报 / 分部收入 / 体检 / DCF", "src": "SEC EDGAR(官方)", "delay": "按财报披露日(季报/年报)", "note": "公共领域数据,指标由代码计算"},
    {"k": "持股结构 / 内部人 / 做空比例 / 预期", "src": "Yahoo Finance quoteSummary", "delay": "季度或半月更新,有滞后", "note": "非官方接口"},
    {"k": "公司简介", "src": "维基百科(CC BY-SA)+ Yahoo;翻译为 Google 非官方接口", "delay": "不定期", "note": "翻译可能不准"},
]


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
        if name == "macro":
            if q.get("part") == "econ":                       # 经济日历(复用 macro 这个接口文件,Vercel 免费版最多只能有 12 个函数)
                today = datetime.date.today()
                frm = q.get("from") or str(today)
                to = q.get("to") or str(today + datetime.timedelta(days=30))
                try:
                    a, b = datetime.date.fromisoformat(frm), datetime.date.fromisoformat(to)
                except ValueError:
                    return 400, {"error": "bad date"}, 0
                if b < a or (b - a).days > ECON_SPAN_MAX:
                    return 400, {"error": "bad range"}, 0
                return 200, econ(frm, to), 3600
            return 200, macro(), 600
        if name == "movers":
            return 200, (screen(q) if q.get("part") == "screen" else sectors(10) if q.get("part") == "sectors" else sectors(50, q.get("name", "")) if q.get("part") == "sector" else movers()), 120
        if name == "company":
            if q.get("part") == "profile":
                import _profile
                return 200, _profile.profile(q["symbol"].upper()), 3600
            return 200, company(q["symbol"].upper()), 600
        if name == "fin":
            import _fin, _health
            fn = {"seg": _fin.segments, "health": _health.health, "em": _health.expected_move}.get(q.get("part"), _fin.fin)
            return 200, fn(q["symbol"].upper()), 3600 if q.get("part") != "em" else 600
        if name == "search":
            return 200, search(q.get("q", "")), 60
        if name == "detail":
            return 200, detail(q["symbol"].upper()), 15
        if name == "status":
            return 200, {"finnhub": bool(os.environ.get("FINNHUB_KEY")), "fmp": bool(os.environ.get("FMP_KEY")), "sec": bool(os.environ.get("SEC_CONTACT")), "fred": bool(os.environ.get("FRED_KEY")), "auth": {"url": os.environ.get("SUPABASE_URL"), "key": os.environ.get("SUPABASE_KEY")} if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY") else None, "dbg": DBG, "sources": SOURCES}, 0
        return 404, {"error": "not found"}, 0
    except Exception as e:
        # 只返回错误类型和简短说明(urllib 的错误信息不含网址和密钥),方便排查
        return 500, {"error": "server error", "detail": f"{type(e).__name__}: {str(e)[:80]}"}, 0
