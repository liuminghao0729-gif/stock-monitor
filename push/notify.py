"""新闻推送程序:抓取 Finnhub 新闻 -> 判断重要性 -> 通过 ntfy 推送到手机。
环境变量(都是保密信息,绝不写进代码):
  FINNHUB_KEY  Finnhub API Key
  NTFY_TOPIC   你的 ntfy 主题名(相当于你的专属频道,别人知道就能给你发消息,要保密)
  DRY_RUN=1    只打印,不真的推送
用法:python3 push/notify.py            正常运行
      python3 push/notify.py --selftest  用样例新闻测试判断逻辑(不联网)
"""
import datetime, json, os, sys, time, urllib.request, urllib.parse
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
STATE = os.path.join(HERE, "sent.json")
COUNT_STATE = os.path.join(HERE, "state.json")      # 每天已推送条数(按美西日期)
PT = ZoneInfo("America/Los_Angeles")
MAX_PER_RUN = CFG.get("max_per_run", 5)


def score(title, summary, keywords):
    text = (title + " " + summary).lower()
    return sum(1 for k in keywords if k.lower() in text)


def pick(macro, company, seen):
    """macro: 全球新闻列表;company: {代码: 新闻列表}。返回要推送的 [(分数, 标签, 新闻)]"""
    out = []
    for a in macro:
        if a["id"] in seen: continue
        s = score(a["headline"], a.get("summary", ""), CFG["macro_keywords"])
        if s >= CFG["macro_min_score"]:
            out.append((s + 1, "宏观", a))
    for sym, arts in company.items():
        for a in arts:
            if a["id"] in seen: continue
            # 个股新闻:标题里直接点名该股票或公司,且命中重要关键词
            s = score(a["headline"], "", CFG["stock_keywords"])
            if s >= 1 and (sym.lower() in a["headline"].lower() or sym.lower() in a.get("related", "").lower().split(",")):
                out.append((s + 2, sym, a))
    out.sort(key=lambda x: (-x[0], -x[2]["datetime"]))
    uniq, ids = [], set()
    for sc, tag, a in out:        # 同一条新闻只推一次
        if a["id"] in ids: continue
        ids.add(a["id"]); uniq.append((sc, tag, a))
    return uniq


def fh(path, **params):
    key = os.environ["FINNHUB_KEY"]
    url = "https://finnhub.io/api/v1/" + path + "?" + urllib.parse.urlencode(dict(params, token=key))
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "stock-push"}), timeout=20) as r:
        return json.loads(r.read().decode())


def send(title, message, click="", priority=3):
    if os.environ.get("DRY_RUN"):
        print("[DRY]", title, "|", message[:80]); return
    body = json.dumps({"topic": os.environ["NTFY_TOPIC"], "title": title, "message": message, "click": click, "priority": priority}).encode()
    urllib.request.urlopen(urllib.request.Request("https://ntfy.sh/", data=body, headers={"Content-Type": "application/json"}), timeout=20).read()


def in_quiet(t, cfg=CFG):
    """夜间静音:美西 quiet_start 到 quiet_end(跨午夜)。"""
    hm = lambda x: int(x[:2]) * 60 + int(x[3:])
    m = t.hour * 60 + t.minute
    a, b = hm(cfg["quiet_start"]), hm(cfg["quiet_end"])
    return (m >= a or m < b) if a > b else (a <= m < b)


def select(cand, now_ts, state, cfg=CFG, now=None):
    """从候选里选出这次要推送的:周末只推重大宏观;静音时段不推;只推最近 fresh_minutes 分钟内的新闻;
    每天最多 daily_max 条,其中非自选股的宏观新闻最多 macro_daily_max 条(给自选股留名额)。返回 (要推送的列表, 新状态)。"""
    t = now or datetime.datetime.fromtimestamp(now_ts, PT)
    day = t.strftime("%Y-%m-%d")
    st = dict(state) if state.get("date") == day else {"date": day, "total": 0, "macro": 0}
    if in_quiet(t, cfg):
        return [], st
    weekend = t.weekday() >= 5
    out = []
    for sc, tag, a in cand:
        if a["datetime"] < now_ts - cfg["fresh_minutes"] * 60:
            continue
        if weekend and not (tag == "宏观" and sc - 1 >= cfg["weekend_macro_min_score"]):
            continue
        if st["total"] >= cfg["daily_max"]:
            break
        if tag == "宏观" and st["macro"] >= cfg["macro_daily_max"]:
            continue
        out.append((sc, tag, a))
        st["total"] += 1
        st["macro"] += tag == "宏观"
        if len(out) >= MAX_PER_RUN:
            break
    return out, st


def main():
    seen = set(json.load(open(STATE))) if os.path.exists(STATE) else None
    first = seen is None
    seen = seen or set()
    day = time.strftime("%Y-%m-%d", time.gmtime())
    yday = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400))
    macro = fh("news", category="general")
    company = {}
    for sym in CFG["watchlist"]:
        try: company[sym] = fh("company-news", symbol=sym, **{"from": yday, "to": day})
        except Exception as e: print("跳过", sym, e)
    cand = pick(macro, company, seen)
    all_ids = {a["id"] for a in macro} | {a["id"] for l in company.values() for a in l}
    if first:   # 第一次运行:只记录现有新闻,不推送一堆旧闻
        send("美股推送已启动", "之后只会推送新出现的重要新闻。")
        print("首次运行,已记录", len(all_ids), "条现有新闻")
    else:
        state = json.load(open(COUNT_STATE)) if os.path.exists(COUNT_STATE) else {}
        chosen, state = select(cand, time.time(), state)
        for sc, tag, a in chosen:
            send(f"[{tag}] {a['headline'][:90]}", (a.get("summary") or a["headline"])[:200], a.get("url", ""), 4 if sc >= 3 else 3)
        json.dump(state, open(COUNT_STATE, "w"))
        print("推送", len(chosen), "条,候选", len(cand), "| 今天已推", state["total"], "/", CFG["daily_max"])
    seen |= all_ids
    json.dump(sorted(seen)[-5000:], open(STATE, "w"))


def selftest():
    now = int(time.time())
    macro = [{"id": 1, "headline": "Fed's Powell signals rate cut as CPI cools", "summary": "inflation", "datetime": now},
             {"id": 2, "headline": "Local bakery opens new store", "summary": "", "datetime": now}]
    company = {"NVDA": [{"id": 3, "headline": "Nvidia (NVDA) price target raised after earnings beat", "related": "NVDA", "datetime": now},
                        {"id": 4, "headline": "5 stocks to buy now including NVDA", "related": "NVDA", "datetime": now}]}
    for sc, tag, a in pick(macro, company, set()):
        print(sc, tag, a["headline"])


def test_push():
    send("美股推送测试", "收到这条说明:GitHub → ntfy → 手机 这条链路是通的。")
    print("已发送测试推送")


if __name__ == "__main__":
    if "--selftest" in sys.argv: selftest()
    elif "--test" in sys.argv: test_push()
    else: main()
