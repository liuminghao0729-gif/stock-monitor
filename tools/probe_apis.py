"""免费 API 探测脚本:在你自己的终端里运行,看哪些接口的免费 Key 能用。
- 只从环境变量读取 Key(ALPHAVANTAGE_KEY、FMP_KEY、可选 SEC_CONTACT=你的邮箱),不会把 Key 写进任何文件。
- 输出里不包含 Key。你可以把输出整段发给我。
用法:
  export ALPHAVANTAGE_KEY="..." FMP_KEY="..." && python3 tools/probe_apis.py
"""
import json, os, urllib.request, urllib.error

def get(url, headers=None):
    try:
        req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"

def js(t):
    try: return json.loads(t)
    except Exception: return None

def line(name, ok, info):
    print(f"{'✅' if ok else '❌'} {name:<34} {info}")

av, fmp, sec = os.environ.get("ALPHAVANTAGE_KEY"), os.environ.get("FMP_KEY"), os.environ.get("SEC_CONTACT")

print("=== Alpha Vantage ===" if av else "=== Alpha Vantage(未设置 ALPHAVANTAGE_KEY,跳过) ===")
if av:
    c, t = get(f"https://www.alphavantage.co/query?function=OVERVIEW&symbol=AAPL&apikey={av}"); d = js(t) or {}
    note = d.get("Note") or d.get("Information")
    keys = [k for k in d if k.startswith("Analyst")]
    line("公司概览(含分析师目标价/评级人数)", bool(keys), f"含字段:{keys}" if keys else (note or t[:100]))
    if keys: print("      示例:", {k: d[k] for k in keys})
    c, t = get(f"https://www.alphavantage.co/query?function=TOP_GAINERS_LOSERS&apikey={av}"); d = js(t) or {}
    ok = bool(d.get("top_gainers"))
    line("涨幅榜/跌幅榜/最活跃(全市场)", ok, f"涨幅榜 {len(d.get('top_gainers', []))} 只,首只:{d['top_gainers'][0]['ticker'] if ok else ''}" if ok else (d.get("Note") or d.get("Information") or t[:100]))

print("\n=== FMP ===" if fmp else "\n=== FMP(未设置 FMP_KEY,跳过) ===")
if fmp:
    base = "https://financialmodelingprep.com/stable/"
    for name, path in [("目标价共识(高/均/低)", "price-target-consensus?symbol=AAPL"), ("目标价汇总", "price-target-summary?symbol=AAPL"),
                       ("机构评级变动(升降级)", "grades?symbol=AAPL"), ("涨幅榜", "biggest-gainers"), ("跌幅榜", "biggest-losers"),
                       ("成交最活跃", "most-actives"), ("报价", "quote?symbol=AAPL"), ("财报日历", "earnings-calendar?from=2026-11-09&to=2026-11-09")]:
        c, t = get(f"{base}{path}{'&' if '?' in path else '?'}apikey={fmp}"); d = js(t)
        ok = c == 200 and d not in (None, [], {}) and not (isinstance(d, dict) and d.get("Error Message"))
        info = (f"返回 {len(d)} 条" if isinstance(d, list) else f"字段:{list(d)[:6]}") if ok else f"HTTP {c} {(t[:90] if t else '')}"
        line(name, ok, info)
        if ok and isinstance(d, list) and d: print("      示例:", {k: d[0][k] for k in list(d[0])[:6]})

print("\n=== SEC EDGAR(官方、不用 Key,但要求附带联系邮箱) ===" if sec else "\n=== SEC EDGAR(未设置 SEC_CONTACT,跳过) ===")
if sec:
    h = {"User-Agent": f"StocksMonitor {sec}"}
    c, t = get("https://data.sec.gov/api/xbrl/companyconcept/CIK0001341439/us-gaap/RevenueRemainingPerformanceObligation.json", h); d = js(t)
    ok = c == 200 and d
    if ok:
        last = sorted(d["units"]["USD"], key=lambda x: x["end"])[-1]
        line("甲骨文 剩余履约义务(RPO)", True, f"{last['end']} 约 {last['val']/1e9:.0f} 十亿美元")
    else:
        line("甲骨文 剩余履约义务(RPO)", False, f"HTTP {c} {t[:80]}")
print("\n完成。输出里没有任何 Key。")
