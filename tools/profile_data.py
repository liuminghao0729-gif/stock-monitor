"""打印一批股票的写「通俗解读」所需的素材(只读):年报业务描述、收入构成、TTM 财务、在手订单、分析师。
用法: SEC_CONTACT=联系邮箱 python3 tools/profile_data.py SYM1 SYM2 ...(SEC 要求访问者表明身份,所以必须设置 SEC_CONTACT)"""
import os, sys, json, urllib.parse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))
if not os.environ.get("SEC_CONTACT"):
    sys.exit("请先设置环境变量 SEC_CONTACT(联系邮箱)")
import _core as C, _fin as F, _health as H

def b(n):
    return "--" if n is None else (f"{n/1e9:.2f}B" if abs(n) >= 1e9 else f"{n/1e6:.0f}M")

for sym in sys.argv[1:]:
    print("=" * 78); print(sym)
    try:
        r = C._yh_open(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(sym)}?modules=assetProfile,price,financialData")["quoteSummary"]["result"][0]
        ap, pr, fd = r.get("assetProfile") or {}, r.get("price") or {}, r.get("financialData") or {}
        print("名称:", pr.get("longName"), "| 市值:", b((pr.get("marketCap") or {}).get("raw")), "| 员工:", ap.get("fullTimeEmployees"), "|", ap.get("industry"))
        print("简介:", (ap.get("longBusinessSummary") or "")[:900])
        print("分析师目标均价:", (fd.get("targetMeanPrice") or {}).get("raw"), "n=", (fd.get("numberOfAnalystOpinions") or {}).get("raw"), "评级:", fd.get("recommendationKey"))
    except Exception as e:
        print("yahoo err", e)
    try:
        cf, err = H._cf(sym)
        if err:
            print("SEC:", err)
        else:
            rows, t, yrs = F.build(cf)
            print("TTM 营收", b(t.get("rev")), f"同比{t.get('rev_yoy') and round(t['rev_yoy'],1)}%", "| 净利", b(t.get("ni")), f"同比{t.get('ni_yoy') and round(t['ni_yoy'],1)}%", "| 毛利率", t.get("gm") and round(t["gm"], 1), "| 营业利润率", t.get("om") and round(t["om"], 1), "| FCF", b(t.get("fcf")))
            y = yrs[-1]
            print("最近财年", y["end"], "资产负债率", y.get("dr") and round(y["dr"], 1), "现金", b(y.get("cash")), "有息债", b(y.get("debt")), "流动比率", y.get("cr") and round(y["cr"], 2), "| 最近季度营收", [b(r_["rev"]) for r_ in rows[-4:]])
    except Exception as e:
        print("sec err", type(e).__name__, str(e)[:80])
    try:
        sg = F.segments(sym)
        v = (sg.get("views") or [None])[0]
        if v:
            n = len(v["ends"]) - 1; tot = v["total"]
            print("收入构成(", v["axis"], v["ends"][-1], "):", "; ".join(f"{x['name']} {x['vals'][n]/tot*100:.0f}%" for x in sorted(v["items"], key=lambda x: -(x["vals"][n] or 0))[:6]))
    except Exception as e:
        print("seg err", type(e).__name__)
    try:
        bl = C._sec_backlog(sym)
        if bl:
            print("剩余履约义务(RPO):", [(x["end"], b(x["val"])) for x in bl])
    except Exception as e:
        pass
