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
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ys}?range={rng}&interval={interval}"
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


def _bars(r, daily):
    off = r["meta"].get("gmtoffset", 0)
    q = r["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(r.get("timestamp") or []):
        o, h, l, c, v = (q[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c):
            continue
        d = datetime.datetime.utcfromtimestamp(t + off)
        out.append({"t": d.strftime("%Y-%m-%d" if daily else "%m-%d %H:%M"), "o": o, "h": h, "l": l, "c": c, "v": v or 0})
    return out


def bars(sym, rng):
    if rng in ("1D", "5D"):
        r = _chart(sym, "1d" if rng == "1D" else "5d", "5m" if rng == "1D" else "30m", 20)
        return {"daily": False, "bars": _bars(r, False)}
    n = {"1M": 22, "6M": 126, "1Y": 252, "5Y": 1260}[rng]
    full = _bars(_chart(sym, "5y", "1d", 300), True)   # 取满5年,用来计算200日均线
    return {"daily": True, "n": min(n, len(full)), "full": full, "bars": full[-n:]}


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
            rng = q.get("range", "6M")
            if rng not in ("1D", "5D", "1M", "6M", "1Y", "5Y"):
                return 400, {"error": "bad range"}, 0
            return 200, bars(q["symbol"].upper(), rng), 20
        if name == "news":
            return 200, news(q.get("symbol", "").upper()), 120
        if name == "earnings":
            datetime.date.fromisoformat(q["date"])      # 校验日期格式
            return 200, earnings(q["date"]), 600
        if name == "status":
            return 200, {"finnhub": bool(os.environ.get("FINNHUB_KEY"))}, 0
        return 404, {"error": "not found"}, 0
    except Exception as e:
        return 500, {"error": "server error"}, 0
