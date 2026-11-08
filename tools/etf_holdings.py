"""ETF 完整持仓(来自 SEC 的 N-PORT 季度披露,官方数据,只用标准库)。
用法: SEC_CONTACT=你的邮箱 python3 tools/etf_holdings.py [VOO QQQ ...]
结果写入 public/etf_holdings.json(每只 ETF 保留前 100 大持仓)。N-PORT 每季度披露一次,滞后约 2 个月,
所以这个文件每季度更新一次就够了;页面上会标出数据截止日期。"""
import json, os, re, sys, time, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "etf_holdings.json")
DEFAULT = ["VOO", "QQQ"]


def get(url):
    contact = (os.environ.get("SEC_CONTACT") or "").strip()
    if not contact:
        sys.exit("请先设置 SEC_CONTACT(你的联系邮箱),SEC 要求请求带联系方式")
    req = urllib.request.Request(url, headers={"User-Agent": "StocksMonitor " + contact})
    return urllib.request.urlopen(req, timeout=60).read()


def series_of(sym):
    mf = json.loads(get("https://www.sec.gov/files/company_tickers_mf.json"))
    for cik, sid, _cls, s in mf["data"]:
        if s == sym:
            return cik, sid
    return None, None


def find_filing(cik, sid, limit=150):
    """在同一家基金公司的 N-PORT 里,从最新往回找属于该基金(series)的那一份。"""
    sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))
    r = sub["filings"]["recent"]
    acc = [(r["filingDate"][i], r["accessionNumber"][i]) for i in range(len(r["form"])) if r["form"][i] == "NPORT-P"][:limit]

    def probe(x):
        d, a = x
        try:
            b = get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{a.replace('-', '')}/primary_doc.xml")
        except Exception:
            return None
        m = re.search(rb"<seriesId>(S\d+)", b[:6000])
        return (d, a, b) if m and m.group(1).decode() == sid else None

    for i in range(0, len(acc), 8):                       # 8 个一批并发找,找到就停
        with ThreadPoolExecutor(8) as ex:
            for hit in ex.map(probe, acc[i:i + 8]):
                if hit:
                    return hit
    return None


def parse(xml_bytes):
    root = ET.fromstring(xml_bytes)
    ns = {"n": root.tag.split("}")[0][1:]}
    q = lambda e, p: (e.findtext(p, namespaces=ns) or "").strip()
    rep = q(root, ".//n:repPdDate")
    items = []
    for h in root.iterfind(".//n:invstOrSec", ns):
        try:
            pct = float(q(h, "n:pctVal"))
        except ValueError:
            continue
        tk = h.find(".//n:identifiers/n:ticker", ns)
        items.append({"name": q(h, "n:name"), "ticker": tk.get("value") if tk is not None else None, "pct": round(pct, 4)})
    items.sort(key=lambda x: -x["pct"])
    return rep, len(items), items


def main():
    syms = [s.upper() for s in sys.argv[1:]] or DEFAULT
    try:
        out = json.load(open(OUT))
    except Exception:
        out = {}
    for s in syms:
        cik, sid = series_of(s)
        if not cik:
            print(s, "在 SEC 基金代码表里找不到,跳过"); continue
        t0 = time.time()
        hit = find_filing(cik, sid)
        if not hit:
            print(s, "没找到 N-PORT,跳过"); continue
        filed, acc, raw = hit
        rep, n, items = parse(raw)
        out[s] = {"asof": rep, "filed": filed, "n": n, "top": items[:100], "src": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/",
                  "updated": time.strftime("%Y-%m-%d")}
        print(f"{s}: 截止 {rep},共 {n} 项持仓,前三 {[(x['ticker'] or x['name'][:12], x['pct']) for x in items[:3]]},用时 {time.time() - t0:.0f}s")
    json.dump(out, open(OUT, "w"), ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
