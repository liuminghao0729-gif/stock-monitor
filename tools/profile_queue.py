"""通俗解读写作队列:标普 500 成分股,按市值从大到小。
用法: python3 tools/profile_queue.py            刷新队列文件 tools/profile_queue.json
      python3 tools/profile_queue.py --next 20  打印接下来要写的 20 只(跳过已经写过的)
已写过 = 在 public/profiles.js 里,或在 public/profiles_gen.json 里。成分股名单来自维基百科,市值来自 Yahoo 筛选器,都不需要 Key。"""
import json, os, re, sys, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))
import _core as C

QUEUE = os.path.join(ROOT, "tools", "profile_queue.json")
SKIP = {"GOOG", "NWS", "FOX", "BRK-A"}        # 同一家公司的第二类股票,共用主代码的解读


def constituents():
    u = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({"action": "parse", "page": "List_of_S&P_500_companies", "prop": "text", "section": 1, "format": "json"})
    html = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=C.UA), timeout=30))["parse"]["text"]["*"]
    syms = re.findall(r'<tr>\s*<td><a[^>]*class="external text"[^>]*>([A-Z.\-]{1,6})</a>', html)
    return [s.replace(".", "-") for s in dict.fromkeys(syms)]


def caps(symbols):
    """Yahoo 批量报价取市值,每批 80 只。"""
    out = {}
    for i in range(0, len(symbols), 80):
        batch = symbols[i:i + 80]
        d = C._yh_open("https://query1.finance.yahoo.com/v7/finance/quote?formatted=false&symbols=" + urllib.parse.quote(",".join(batch)))
        for x in d["quoteResponse"]["result"]:
            out[x["symbol"]] = (x.get("marketCap"), x.get("shortName") or x["symbol"])
        time.sleep(0.4)
    return out


def done_set():
    d = set()
    try:
        d |= set(re.findall(r"^  ([A-Z.\-]+): \{", open(os.path.join(ROOT, "public", "profiles.js"), encoding="utf8").read(), re.M))
    except Exception:
        pass
    try:
        d |= set(json.load(open(os.path.join(ROOT, "public", "profiles_gen.json"), encoding="utf8")))
    except Exception:
        pass
    try:                                                  # 正在由人工(对话里)手写、还没合并的代码,夜间任务先跳过,避免撞车
        d |= {x.strip() for x in open(os.path.join(ROOT, "tools", "profile_reserved.txt"), encoding="utf8") if x.strip() and not x.startswith("#")}
    except Exception:
        pass
    return d


def refresh():
    cs = constituents(); cp = caps(cs)
    rows = sorted(((s, cp[s][0] or 0, cp[s][1]) for s in cs if s in cp and s not in SKIP), key=lambda r: -r[1])
    missing = [s for s in cs if s not in cp]
    json.dump({"updated": time.strftime("%Y-%m-%d"), "n_sp500": len(cs), "missing_cap": missing, "queue": [{"sym": s, "cap": c, "name": n} for s, c, n in rows]},
              open(QUEUE, "w", encoding="utf8"), ensure_ascii=False, indent=0)
    print(f"标普成分股 {len(cs)} 只,排好队 {len(rows)} 只,没查到市值 {len(missing)} 只: {missing[:10]}")


ALIAS = {"GOOG": "GOOGL", "BRK-A": "BRK-B", "FOX": "FOXA", "NWS": "NWSA"}   # 和页面上 PROF_ALIAS 一致:第二类股份共用主代码


def priority():
    """用户指定的优先清单(tools/profile_priority.txt),按文件里的顺序。"""
    try:
        return [x.strip().upper().replace(".", "-") for x in open(os.path.join(ROOT, "tools", "profile_priority.txt"), encoding="utf8") if x.strip() and not x.startswith("#")]
    except Exception:
        return []


def next_n(n):
    q = json.load(open(QUEUE, encoding="utf8"))["queue"]
    d = done_set()
    isdone = lambda s: s in d or ALIAS.get(s) in d
    pri = [s for s in dict.fromkeys(priority()) if not isdone(s)]
    print(f"优先清单还剩 {len(pri)} 只(先写这些,按顺序)。")
    rest = [x for x in q if not isdone(x["sym"]) and x["sym"] not in pri]
    print(f"标普 500 队列另有 {len(rest)} 只,优先清单写完后按市值接着写。接下来 {n} 只:")
    for s in pri[:n]:
        print(f"  {s:7s} (优先清单)")
    for x in rest[:max(0, n - len(pri))]:
        print(f"  {x['sym']:7s} {x['cap'] / 1e9:8.0f}B  {x['name']}")


if __name__ == "__main__":
    if "--next" in sys.argv:
        next_n(int(sys.argv[sys.argv.index("--next") + 1]))
    else:
        refresh(); next_n(25)
