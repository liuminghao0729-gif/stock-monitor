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
    "liab": ["Liabilities"],
    "ca": ["AssetsCurrent"],
    "cl": ["LiabilitiesCurrent"],
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
    return {r["end"]: (r["val"], r["first"]) for r in rows if 350 <= _days(r["start"], r["end"]) <= 380}


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
        _bs(row)
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
    return rows, t, _annual_rows(ann, q)


def _bs(row):
    """资产负债表比率:资产负债率 = 总负债 / 总资产;流动比率 = 流动资产 / 流动负债。没有披露「总负债」时用 总资产 − 股东权益 估算。"""
    liab = row.get("liab")
    if liab is None and row.get("assets") and row.get("equity") is not None:
        liab = row["assets"] - row["equity"]
    row["dr"] = None if liab is None or not row.get("assets") else liab / row["assets"] * 100
    row["cr"] = None if not row.get("cl") or row.get("ca") is None else row["ca"] / row["cl"]


def _annual_rows(ann, q):
    """年度报表:取全年数(10-K 直接披露,不是四季相加);最近 6 个财年。"""
    ends = sorted(ann["rev"])[-6:]
    out = []
    for e in ends:
        row = {"end": e, "filed": ann["rev"][e][1]}
        for k in FLOW:
            v = ann[k].get(e)
            row[k] = None if v is None else v[0]
        row["fcf"] = None if row["ocf"] is None or row["capex"] is None else row["ocf"] - abs(row["capex"])
        for k in ("cash", "debt", "equity", "assets", "liab", "ca", "cl"):
            v = q[k].get(e)
            row[k] = None if v is None else v[0]
        _bs(row)
        row["gm"] = None if not row["rev"] or row["gp"] is None else row["gp"] / row["rev"] * 100
        row["om"] = None if not row["rev"] or row["oi"] is None else row["oi"] / row["rev"] * 100
        row["nm"] = None if not row["rev"] or row["ni"] is None else row["ni"] / row["rev"] * 100
        out.append(row)
    return out


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
    rows, ttm, years = build(cf)
    if len(rows) < 4:
        return {"error": "too_short"}
    return {"name": cf.get("entityName"), "rows": rows, "years": years, "ttm": ttm, "check": _yahoo_check(sym, rows),
            "source": "SEC EDGAR 官方财报数据(XBRL companyfacts)", "asof": rows[-1]["end"]}


# ---------- 收入构成(按产品 / 业务分部 / 地区):读取最新 10-K 的 XBRL 原文 ----------
import re
import xml.etree.ElementTree as ET

AXES = {"ProductOrServiceAxis": "按产品 / 服务", "StatementBusinessSegmentsAxis": "按业务分部", "StatementGeographicalAxis": "按地区"}
ZH = {"IPhone": "iPhone", "IPad": "iPad", "Mac": "Mac", "WearablesHomeandAccessories": "可穿戴/家居/配件", "Service": "服务", "Product": "硬件产品",
      "Americas": "美洲", "Europe": "欧洲", "GreaterChina": "大中华区", "Japan": "日本", "RestOfAsiaPacific": "亚太其他", "OtherCountries": "其他国家",
      "UnitedStates": "美国", "US": "美国", "CN": "中国", "ForeignCountries": "海外", "Domestic": "美国", "International": "海外",
      "DataCenter": "数据中心", "Gaming": "游戏", "ProfessionalVisualization": "专业可视化", "Automotive": "汽车", "OEMAndOther": "OEM 及其他",
      "ComputeAndNetworking": "计算与网络", "Graphics": "图形",
      "Subscription": "订阅", "Advertising": "广告", "Compute": "算力芯片", "Networking": "网络",
      "TW": "台湾", "HK": "香港", "JP": "日本", "GB": "英国", "DE": "德国", "SG": "新加坡", "KR": "韩国", "IN": "印度", "FR": "法国", "CA": "加拿大", "IE": "爱尔兰",
      "NonUs": "美国以外/其他", "ServiceOther": "服务及其他", "ServerProductsAndCloudServices": "服务器产品与云服务",
      "MicrosoftThreeSixFiveCommercialProductsAndCloudServices": "Microsoft 365 商业版", "XBOX": "Xbox", "LinkedInCorporation": "LinkedIn",
      "WindowsAndDevices": "Windows 与设备", "SearchAndNewsAdvertising": "搜索与新闻广告", "EnterpriseAndPartnerServices": "企业与合作伙伴服务",
      "ProductivityAndBusinessProcesses": "生产力与业务流程", "IntelligentCloud": "智能云", "MorePersonalComputing": "更多个人计算",
      "CloudInfrastructure": "云基础设施(OCI)", "CloudApplications": "云应用", "SoftwareSupport": "软件支持", "SoftwareLicense": "软件许可",
      "Hardware": "硬件", "Services": "服务", "CloudRevenues": "云收入(合计)", "SoftwareRevenues": "软件收入(合计)",
      "DRAMProducts": "DRAM 内存", "NANDProducts": "NAND 闪存", "OtherProductSales": "其他"}
_AGG = {"Product", "Total", "Consolidated"}


def _label(member):
    name = member.split(":")[-1]
    name = re.sub(r"Member$", "", name)
    if name in ZH:
        return ZH[name]
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)           # 没有中文对照就显示英文原名(驼峰拆开)


def _latest_10k(h, cik):
    sub = C._get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", 21600, h)["filings"]["recent"]
    for i, f in enumerate(sub["form"]):
        if f == "10-K":
            acc, doc = sub["accessionNumber"][i].replace("-", ""), sub["primaryDocument"][i]
            return {"url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc.rsplit('.', 1)[0]}_htm.xml",
                    "filed": sub["filingDate"][i], "doc": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}"}
    return None


def parse_segments(xml_bytes):
    ns = {"x": "http://www.xbrl.org/2003/instance", "d": "http://xbrl.org/2006/xbrldi"}
    root = ET.fromstring(xml_bytes)
    ctx = {}
    for c in root.findall("x:context", ns):
        p = c.find("x:period", ns)
        s, e = p.find("x:startDate", ns), p.find("x:endDate", ns)
        if s is None or e is None or c.findall(".//d:typedMember", ns):
            continue
        dims = [(m.get("dimension").split(":")[-1], m.text) for m in c.findall(".//d:explicitMember", ns)]
        if len(dims) == 1 and 350 <= _days(s.text, e.text) <= 380:
            ctx[c.get("id")] = (dims[0][0], dims[0][1], e.text)
    revtags = {t for tags in [FLOW["rev"]] for t in tags}
    total = {}                                                   # 无维度的总营收(用来判断各项加起来是否等于总数)
    for c in root.findall("x:context", ns):
        p = c.find("x:period", ns)
        s_, e_ = p.find("x:startDate", ns), p.find("x:endDate", ns)
        if s_ is not None and e_ is not None and not c.findall(".//d:explicitMember", ns) and 350 <= _days(s_.text, e_.text) <= 380:
            total[c.get("id")] = e_.text
    tot = {}
    for el in root:
        if el.tag.split("}")[-1] in revtags and el.get("contextRef") in total and el.text:
            tot.setdefault(total[el.get("contextRef")], float(el.text))
    data = {}
    for el in root:
        tag = el.tag.split("}")[-1]
        if tag not in revtags or el.get("contextRef") not in ctx or not el.text:
            continue
        axis, mem, end = ctx[el.get("contextRef")]
        if axis in AXES:
            data.setdefault(axis, {}).setdefault(mem, {})[end] = float(el.text)
    out = []
    for axis, label in AXES.items():
        mems = data.get(axis)
        if not mems:
            continue
        ends = sorted({e for m in mems.values() for e in m})[-3:]
        names = {m: _label(m) for m in mems}
        if axis == "ProductOrServiceAxis" and len([m for m in mems if m.split(":")[-1] not in ("ProductMember", "ServiceMember")]) >= 2:
            mems = {m: v for m, v in mems.items() if m.split(":")[-1] != "ProductMember"}      # 去掉「硬件产品」这个合计,避免重复计算
        items = [{"name": names[m], "vals": [v.get(e) for e in ends]} for m, v in mems.items() if v.get(ends[-1])]
        items = [i for i in items if i["vals"][-1] > 0]
        if len(items) < 2:
            continue
        items.sort(key=lambda i: -i["vals"][-1])
        T = tot.get(ends[-1])
        pick, overlap = _pick_partition(items[:14], T) if T else (items[:8], True)
        if len(pick) < 2:
            continue
        out.append({"axis": label, "ends": ends, "items": pick, "total": T, "overlap": overlap})
    return out


def _pick_partition(items, total):
    """成员之间可能有包含关系(如「数据中心」包含「算力」和「网络」,「EMEA」包含「英国」)。
    找一组互不重叠、加起来最接近总营收的成员(误差≤1.5%);误差差不多时取成员更多的。找不到就返回前几项并标注「可能重叠」。"""
    from itertools import combinations
    best, key = None, None
    for n in range(2, len(items) + 1):
        for combo in combinations(items, n):
            err = abs(sum(i["vals"][-1] for i in combo) - total) / total
            if err <= 0.015:
                k = (round(err / 0.002), -n)
                if key is None or k < key:
                    best, key = list(combo), k
    if best:
        return sorted(best, key=lambda i: -i["vals"][-1]), False
    return items[:8], True


def segments(sym):
    contact = (os.environ.get("SEC_CONTACT") or "").strip().strip("\"'“”‘’ ")
    if not contact or not contact.isascii() or sym in C.ALIAS:
        return {"error": "no_contact"}
    h = {"User-Agent": "StocksMonitor " + contact}
    tk = C._get("https://www.sec.gov/files/company_tickers.json", 86400, h)
    cik = next((v["cik_str"] for v in tk.values() if v["ticker"] == sym.replace("-", ".")), None)
    if cik is None:
        return {"error": "no_cik"}
    k = _latest_10k(h, cik)
    if not k:
        return {"error": "no_10k"}
    key = "seg:" + k["url"]
    hit = C._cache.get(key)
    if hit and time.time() - hit[0] < 86400:
        return hit[1]
    req = C.urllib.request.Request(k["url"], headers=h)
    try:
        with C.urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
    except Exception:
        return {"error": "no_instance"}
    res = {"views": parse_segments(raw), "filed": k["filed"], "doc": k["doc"], "source": "SEC 最新年报(10-K)原文"}
    C._cache[key] = (time.time(), res)
    return res
