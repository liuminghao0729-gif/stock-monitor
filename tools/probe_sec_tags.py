"""SEC 财报标签探测脚本:找出为什么有些公司(银行、公用事业、XOM 等)的财报数据「停更」或「缺收入」。
思路:这些公司在 SEC 财报里换了「收入」等指标的标签,我们的程序(api/_fin.py 里的 FLOW 表)不认识新标签,
所以数据停在旧年份。本脚本列出每家公司实际在用的标签和最新一期日期,告诉我该往 FLOW 表里补哪些标签。

用法(在你自己的终端里运行,联系邮箱只从环境变量读取,脚本不会显示、不会写进任何文件):
  export SEC_CONTACT="你的邮箱"
  python3 tools/probe_sec_tags.py C DUK XOM GS        # 指定代码
  python3 tools/probe_sec_tags.py                     # 不带参数 = 默认的问题公司清单
然后把输出整段发给我。输出里没有邮箱。"""
import datetime, json, os, re, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "api"))
import _core as C
import _fin as F

DEFAULT = "C MS WFC BNY JD DUK SO AEP XOM CBRS QURE GS BABA SONY WIX OKLO".split()
# 各指标要找的「候选标签」:名字里出现这些词的标签都列出来,供我挑选补进 FLOW 表
CANDIDATES = {
    "收入": re.compile(r"(Revenue|Revenues|Sales|InterestAndDividendIncome|InterestIncome|NoninterestIncome|OperatingRevenue|UtilityRevenue)", re.I),
    "净利润": re.compile(r"^(NetIncomeLoss|ProfitLoss|NetIncomeLossAvailable|IncomeLossFromContinuingOperations(?!Before))", re.I),
    "每股盈利": re.compile(r"^EarningsPerShare(Diluted|Basic)", re.I),
}
_D = datetime.date.fromisoformat


def days(r):
    try:
        return (_D(r["end"]) - _D(r["start"])).days if r.get("start") else None
    except Exception:
        return None


def tag_summary(g, name, unit):
    """某个标签在某个单位下:最新一期(季度口径优先)的结束日、最新数值、最近两年的季度条数、最新一次提交日。"""
    rows = g.get(name, {}).get("units", {}).get(unit) or []
    if not rows:
        return None
    q = [r for r in rows if days(r) is not None and 60 <= days(r) <= 120]
    a = [r for r in rows if days(r) is not None and 330 <= days(r) <= 400]
    pick = q + a or rows                       # 第四季度常常只以全年数字披露,所以季度和全年一起找最新的
    last = max(pick, key=lambda r: (r["end"], r.get("filed", "")))
    two_years = (datetime.date.today() - datetime.timedelta(days=730)).isoformat()
    return {"tag": name, "latest_end": last["end"], "val": last.get("val"), "kind": "季度" if last in q else ("年度" if last in a else "其他"),
            "n_q_2y": sum(1 for r in q if r["end"] >= two_years), "filed": last.get("filed")}


def candidates(cf, label, unit):
    g = cf.get("facts", {}).get("us-gaap", {})
    out = [s for s in (tag_summary(g, t, unit) for t in g if CANDIDATES[label].search(t)) if s]
    out.sort(key=lambda s: (s["latest_end"], s["n_q_2y"]), reverse=True)
    return out


def money(v, unit):
    if not isinstance(v, (int, float)):
        return "--"
    return f"{v:.2f}" if unit == "USD/shares" else (f"{v / 1e9:.2f}B" if abs(v) >= 1e9 else f"{v / 1e6:.1f}M")


def report(sym, cf):
    """对一家公司的 companyfacts 生成一段文字报告(纯函数,可离线测试)。"""
    L = [f"===== {sym}  {cf.get('entityName', '?')} ====="]
    facts = cf.get("facts", {})
    L.append("会计准则命名空间:" + "、".join(sorted(facts)) + ("" if "us-gaap" in facts else "   ← 没有 us-gaap(外国公司,用国际会计准则),我们的程序目前不支持"))
    if "us-gaap" not in facts:
        return "\n".join(L)
    rows, ttm, years = F.build(cf)
    flag = "   ← 数据太旧" if rows and F.is_stale(rows[-1]["end"]) else ("   ← 数据缺失(没有可用的季度收入)" if not rows or not (ttm or {}).get("rev") else "")
    L.append(f"我们的程序现在的结果:季度 {len(rows)} 期,最新一期 {rows[-1]['end'] if rows else '无'},最近 12 个月收入 {money(ttm.get('rev'), 'USD') if ttm and ttm.get('rev') else '无'}" + flag)
    used = {k: [t for t in F.FLOW[k]] for k in ("rev", "ni", "eps")}
    for label, key, unit in (("收入", "rev", "USD"), ("净利润", "ni", "USD"), ("每股盈利", "eps", "USD/shares")):
        L.append(f"-- {label}:我们现在认的标签 {used[key]}")
        g = facts["us-gaap"]
        known = [s for s in (tag_summary(g, t, unit) for t in F.FLOW[key]) if s]
        L.append("   我们认的标签里有数据的:" + ("; ".join(f"{s['tag']} 最新 {s['latest_end']}({s['kind']})" for s in known) if known else "没有任何一个"))
        newest_known = max([s["latest_end"] for s in known], default="0000-00-00")
        cand = [s for s in candidates(cf, label, unit) if s["tag"] not in F.FLOW[key]][:6]
        better = [s for s in cand if s["latest_end"] > newest_known]
        L.append(f"   {'★ 发现更新的候选标签(建议补进 FLOW 表):' if better else '其他候选标签(都不比现有的新):'}")
        for s in (better or cand)[:6]:
            L.append(f"      {s['tag']:<62} 最新 {s['latest_end']}({s['kind']}) 近2年季度 {s['n_q_2y']} 条  值 {money(s['val'], unit)}")
    return "\n".join(L)


def fetch(url, contact):
    req = urllib.request.Request(url, headers={"User-Agent": "StocksMonitor " + contact})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    contact = (os.environ.get("SEC_CONTACT") or "").strip().strip("\"'“”‘’ ")
    if not contact or not contact.isascii():
        sys.exit("请先在终端设置联系邮箱(只能是英文字符):export SEC_CONTACT=\"你的邮箱\"\n(SEC 要求请求里带联系方式;脚本不会显示它,也不会写进任何文件)")
    syms = [a.upper() for a in sys.argv[1:]] or DEFAULT
    print(f"SEC_CONTACT 已设置(不会显示)。探测 {len(syms)} 家:{' '.join(syms)}\n")
    tk = fetch("https://www.sec.gov/files/company_tickers.json", contact)
    for s in syms:
        time.sleep(0.3)                                         # SEC 限速每秒 10 次,这里远低于
        cik = C.sec_cik(tk, s)
        if cik is None:
            print(f"===== {s} =====\n在 SEC 代码表里找不到(ETF、指数或代码写法不同)\n")
            continue
        try:
            cf = fetch(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json", contact)
        except urllib.error.HTTPError as e:
            print(f"===== {s} =====\nSEC 返回 HTTP {e.code}(没有财报数据)\n")
            continue
        except Exception as e:
            print(f"===== {s} =====\n取数失败:{type(e).__name__}\n")
            continue
        print(report(s, cf) + "\n")


if __name__ == "__main__":
    main()
