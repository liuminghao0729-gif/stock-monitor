"""数据后台的核心逻辑(只用 Python 自带库,无需安装任何东西)。
- 行情/K线:Yahoo 财经(非官方接口,不需要 Key)
- 新闻/财报日历:Finnhub(需要环境变量 FINNHUB_KEY,Key 只由你在终端里临时设置,不写入任何文件)
"""
import json, os, time, datetime, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0"}
_cache = {}

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
    hour = {"bmo": "盘前", "amc": "盘后", "dmh": "盘中"}
    return {"items": [{"sym": x["symbol"], "when": hour.get(x.get("hour"), "盘后"), "eps": x.get("epsEstimate"),
                       "rev": x.get("revenueEstimate")} for x in rows]}


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
        if name == "status":
            return 200, {"finnhub": bool(os.environ.get("FINNHUB_KEY"))}, 0
        return 404, {"error": "not found"}, 0
    except Exception as e:
        # 只返回错误类型和简短说明(urllib 的错误信息不含网址和密钥),方便排查
        return 500, {"error": "server error", "detail": f"{type(e).__name__}: {str(e)[:80]}"}, 0
