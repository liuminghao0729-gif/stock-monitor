"""财报趋势:来自 SEC 官方 XBRL 数据(companyfacts),只用 Python 自带库。
- 单季度数据:有直接披露的单季值就用;没有的(第四季、现金流年中累计)用 年度/累计 相减推出,并标注「推算」。
- 公告日:取该期数据最早出现在 SEC 的提交日期(filed)。
- 交叉验证:最近几季的营收/净利润/经营现金流与 Yahoo 对比,误差 ≤1% ✅,1~5% ⚠️,>5% ❌(规则取自 ai-berkshire 的数据规范)。
需要环境变量 SEC_CONTACT(联系邮箱,SEC 要求访问者表明身份)。
"""
import datetime, os, re, time
import _core as C

# 指标 -> 候选 us-gaap 标签(按优先顺序;不同公司/年份用的标签不同)
FLOW = {
    "rev": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"],
    "gp": ["GrossProfit"],
    "oi": ["OperatingIncomeLoss"],
    "ni": ["NetIncomeLoss", "ProfitLoss"],
    "eps": ["EarningsPerShareDiluted"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
}
STOCK = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "equity": ["StockholdersEquity"],
    "assets": ["Assets"],
}
_D = datetime.date.fromisoformat


def _days(a, b):
    return (_D(b) - _D(a)).days


def _facts(cf, tags, unit):
    """按标签优先级取第一个有数据的标签;返回该标签下的原始记录。"""
    g = cf.get("facts", {}).get("us-gaap", {})
    best = []
    for t in tags:
        rows = g.get(t, {}).get("units", {}).get(unit)
        if rows and (not best or max(r["end"] for r in rows) > max(r["end"] for r in best)):
            best = rows                                         # 同一指标可能换标签:最新一期更晚的优先,并列时按顺序
    return best


def _dedupe(rows):
    """同一 (start,end) 取最新提交的数值(含重述),公告日取最早提交日。"""
    by = {}
    for r in rows:
        k = (r.get("start"), r["end"])
        cur = by.get(k)
        if cur is None:
            by[k] = dict(r, first=r["filed"])
        else:
            if r["filed"] >= cur["filed"]:
                first = min(cur["first"], r["filed"])
                cur = dict(r, first=first)
                by[k] = cur
            else:
                cur["first"] = min(cur["first"], r["filed"])
    return list(by.values())


def quarters_flow(rows):
    """流量类指标 -> {季末日: (数值, 公告日, 是否推算)}。"""
    rows = _dedupe([r for r in rows if r.get("start")])
    out = {}
    for r in rows:                                              # 1) 直接披露的单季值
        if 80 <= _days(r["start"], r["end"]) <= 125:
            out[r["end"]] = (r["val"], r["first"], False)
    cum = {}
    for r in rows:                                              # 2) 年内累计值(6个月/9个月/全年)
        if _days(r["start"], r["end"]) > 125:
            cum.setdefault(r["start"], {})[r["end"]] = (r["val"], r["first"])
    for s, d in cum.items():
        ends = sorted(d)
        prev_end, prev_val = s, 0.0
        # 起点处若有直接披露的第一季,把它当作累计起点
        first_q = next((e for e in out if 80 <= _days(s, e) <= 125), None)
        if first_q:
            prev_end, prev_val = first_q, out[first_q][0]
        for e in ends:
            gap = _days(prev_end, e)
            if 80 <= gap <= 125 and e not in out:
                out[e] = (d[e][0] - prev_val, d[e][1], True)
            if 80 <= gap <= 125 or prev_end == s:
                prev_end, prev_val = e, d[e][0]
            elif gap > 125:                                     # 缺了中间一期,没法继续推
                prev_end, prev_val = e, d[e][0]
    for s, d in cum.items():                                    # 3) 没有 6/9 个月累计时:全年数 − 已有的三个单季值
        for e, (val, filed) in d.items():
            if e in out or not 350 <= _days(s, e) <= 380:
                continue
            qs = [v for qe, v in out.items() if s < qe < e and not v[2]]
            if len(qs) == 3:
                out[e] = (val - sum(v[0] for v in qs), filed, True)
    return out


def stock_series(rows):
    rows = _dedupe([r for r in rows if not r.get("start")])
    return {r["end"]: (r["val"], r["first"], False) for r in rows}


def annual(rows):
    rows = _dedupe([r for r in rows if r.get("start")])
    return {r["end"]: r["val"] for r in rows if 350 <= _days(r["start"], r["end"]) <= 380}


def build(cf):
    q, ann = {}, {}
    for k, tags in FLOW.items():
        rows = _facts(cf, tags, "USD/shares" if k == "eps" else "USD")
        q[k] = quarters_flow(rows)
        ann[k] = annual(rows)
    for k, tags in STOCK.items():
        q[k] = stock_series(_facts(cf, tags, "USD"))
    ends = sorted(e for e in q["rev"] if e in q["ni"] or e in q["ocf"])
    # 过滤:只留与营收季末对得上的期间
    ends = ends[-40:]
    rows = []
    for e in ends:
        row = {"end": e, "filed": q["rev"][e][1], "est": any(q[k].get(e, (0, 0, False))[2] for k in ("rev", "ni", "ocf", "gp", "oi"))}
        for k in list(FLOW) + list(STOCK):
            v = q[k].get(e)
            row[k] = None if v is None else v[0]
        row["fcf"] = None if row["ocf"] is None or row["capex"] is None else row["ocf"] - abs(row["capex"])
        rows.append(row)
    # 同比 / TTM
    def prior(i, key):
        tgt = _D(rows[i]["end"]) - datetime.timedelta(days=365)
        for j in range(i - 1, -1, -1):
            if abs((_D(rows[j]["end"]) - tgt).days) <= 12:
                return rows[j].get(key)
        return None
    for i, r in enumerate(rows):
        for k in ("rev", "ni", "ocf", "gp", "oi"):
            p = prior(i, k)
            r[k + "_yoy"] = None if not p or r[k] is None or p <= 0 else (r[k] / p - 1) * 100
        r["gm"] = None if not r["rev"] or r["gp"] is None else r["gp"] / r["rev"] * 100
        r["om"] = None if not r["rev"] or r["oi"] is None else r["oi"] / r["rev"] * 100
        r["nm"] = None if not r["rev"] or r["ni"] is None else r["ni"] / r["rev"] * 100
    def ttm(i, key):
        if i < 3:
            return None
        win = rows[i - 3:i + 1]
        if _days(win[0]["end"], win[-1]["end"]) > 330 or any(w[key] is None for w in win):
            return None
        return sum(w[key] for w in win)
    t = {}
    for k in ("rev", "gp", "oi", "ni", "ocf", "fcf", "eps"):
        cur = ttm(len(rows) - 1, k)
        old = ttm(len(rows) - 5, k) if len(rows) >= 8 else None
        t[k] = cur
        t[k + "_yoy"] = None if cur is None or not old or old <= 0 else (cur / old - 1) * 100
    last = rows[-1] if rows else {}
    t["gm"] = None if not t["rev"] or t["gp"] is None else t["gp"] / t["rev"] * 100
    t["om"] = None if not t["rev"] or t["oi"] is None else t["oi"] / t["rev"] * 100
    t["nm"] = None if not t["rev"] or t["ni"] is None else t["ni"] / t["rev"] * 100
    t["end"] = last.get("end")
    return rows, t


def _yahoo_check(sym, rows):
    """用 Yahoo 的最近几季数据核对 SEC 数据。拿不到就返回 None(页面不显示核对结论,不乱标)。"""
    try:
        now = int(time.time())
        types = "quarterlyTotalRevenue,quarterlyNetIncome,quarterlyOperatingCashFlow"
        url = ("https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/" + sym.replace(".", "-") +
               f"?type={types}&period1={now - 86400 * 800}&period2={now + 86400}&merge=false&padTimeSeries=false")
        r = C._yh_open(url)["timeseries"]["result"]
    except Exception as e:
        C.DBG["fin_chk"] = f"{sym}: {type(e).__name__}: {str(e)[:60]}"
        return None
    names = {"quarterlyTotalRevenue": ("rev", "营收"), "quarterlyNetIncome": ("ni", "净利润"), "quarterlyOperatingCashFlow": ("ocf", "经营现金流")}
    mine = {r["end"]: r for r in rows}
    items = []
    for blk in r:
        t = (blk.get("meta", {}).get("type") or [""])[0]
        if t not in names:
            continue
        key, zh = names[t]
        for pt in blk.get(t, []) or []:
            if not pt or not pt.get("reportedValue"):
                continue
            e = pt["asOfDate"]
            m = mine.get(e) or next((x for x in rows if abs(_days(x["end"], e)) <= 6), None)      # 财年末日期两边可能差几天
            if not m or m.get(key) is None:
                continue
            y = pt["reportedValue"]["raw"]
            err = abs(m[key] - y) / abs(m[key]) * 100 if m[key] else None
            if err is None:
                continue
            items.append({"end": e, "name": zh, "sec": m[key], "yahoo": y, "err": round(err, 2)})
    if not items:
        return None
    worst = max(x["err"] for x in items)
    items.sort(key=lambda x: (x["end"], x["name"]), reverse=True)
    return {"level": "ok" if worst <= 1 else "warn" if worst <= 5 else "bad", "worst": worst, "n": len(items), "items": items[:9]}


def fin(sym):
    contact = (os.environ.get("SEC_CONTACT") or "").strip().strip("\"'“”‘’ ")
    if not contact:
        return {"error": "no_contact"}
    if not contact.isascii():
        return {"error": "bad_contact"}
    if sym in C.ALIAS:
        return {"error": "not_stock"}
    h = {"User-Agent": "StocksMonitor " + contact}
    tk = C._get("https://www.sec.gov/files/company_tickers.json", 86400, h)
    cik = next((v["cik_str"] for v in tk.values() if v["ticker"] == sym.replace("-", ".")), None)
    if cik is None:
        return {"error": "no_cik"}                              # ETF、指数等没有公司财报
    cf = C._get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json", 21600, h)
    if "us-gaap" not in cf.get("facts", {}):
        return {"error": "no_us_gaap"}                          # 外国公司(20-F)用国际会计准则,先不支持
    rows, ttm = build(cf)
    if len(rows) < 4:
        return {"error": "too_short"}
    return {"name": cf.get("entityName"), "rows": rows, "ttm": ttm, "check": _yahoo_check(sym, rows),
            "source": "SEC EDGAR 官方财报数据(XBRL companyfacts)", "asof": rows[-1]["end"]}
