"""盘前早报 / 每小时盘中摘要 / 选股推送(盘中、盘后)。通过 Telegram 推送到手机。
所有时间按美西时间(America/Los_Angeles)。美股美西 6:30 开盘,13:00 收盘。
环境变量(保密信息,只放在 GitHub Secrets):FINNHUB_KEY、TELEGRAM_BOT_TOKEN、TELEGRAM_CHAT_ID;可选 FRED_KEY(宏观日历)。
用法:
  python3 push/market_push.py gate <brief|hourly|mid|post>   判断现在该不该运行(写入 GITHUB_OUTPUT 的 run=true/false)
  python3 push/market_push.py brief                          盘前早报(美西 6:00 左右)
  python3 push/market_push.py hourly                         每小时摘要(7:30–12:30)
  python3 push/market_push.py mid                            盘中摘要 + 选股更新(10:30)
  python3 push/market_push.py post                           盘后选股推送
  python3 push/market_push.py weekly_summary                 周五总结(美西 15:00 左右)
  python3 push/market_push.py weekly_preview                 周日晚前瞻(美西 17:00 左右)
  加 --dry 只打印不发送;加 --force 忽略时间和休市日检查。
模型信号与信息摘要,不保证收益,请自行判断风险。期权"异常"只是按成交量/未平仓量/金额的粗略规则筛出,不代表方向或内幕。
"""
import datetime, json, os, sys, urllib.request, urllib.parse
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "api"), HERE]
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
PT = ZoneInfo("America/Los_Angeles")
SITE = "https://stock-monitor-kappa-three.vercel.app"

# 纽交所休市日(手写,需要每年更新)。提前收盘日(感恩节次日、平安夜)暂未特殊处理。
HOLIDAYS = {"2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
            "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"}
OPT = {"vol_min": 1000, "etf_vol_min": 5000, "ratio_min": 2.5, "notional_min": 500_000, "etfs": {"VOO", "QQQ", "SPY", "IVV", "VTI", "IWM", "DIA"}, "expiries": 3, "per_symbol": 2}


# =============================== 时间 / 休市日 / 闸门 ===============================
def now_pt(now=None):
    return (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(PT)


def is_trading_day(d):
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS


def minutes(t):
    return t.hour * 60 + t.minute


def gate(slot, now=None):
    """现在该不该运行这个任务。用 UTC 的两个候选时间触发(冬令时、夏令时各一个),再用美西时间判断哪个是对的,所以夏令时切换时不用改。"""
    t = now_pt(now)
    m = minutes(t)
    if slot == "weekly_preview":                                   # 周日 17:00 前后(美西)
        return t.weekday() == 6 and 16 * 60 + 55 <= m <= 17 * 60 + 40
    if not is_trading_day(t.date()):
        return False
    if slot == "weekly_summary":                                   # 周五收盘后 15:00 前后;周五休市则不发
        return t.weekday() == 4 and 14 * 60 + 55 <= m <= 15 * 60 + 40
    if slot == "brief":
        return 5 * 60 + 40 <= m <= 6 * 60 + 50
    if slot == "hourly":
        return 7 <= t.hour <= 12 and 15 <= t.minute <= 55 and t.hour != 10          # 10:30 那次由盘中选股任务一起发
    if slot == "mid":
        return 10 * 60 + 15 <= m <= 11 * 60 + 20
    if slot == "post":
        return m >= 13 * 60 + 30
    raise ValueError(slot)


# =============================== 数据 ===============================
def core():
    import _core
    return _core


def pct_str(p, d=2):
    return "--" if p is None else f"{p:+.{d}f}%"


def quote(sym):
    try:
        q = core().quote(sym)
        return {"sym": sym, "price": q["price"], "pct": q["pct"]}
    except Exception:
        return None


def index_line(items):
    return "  ".join(f"{n} {pct_str(q['pct'])}" for n, q in items if q)


def premarket_indices():
    futs = [("标普期货", "ES=F"), ("纳指期货", "NQ=F"), ("道指期货", "YM=F")]
    others = [("VIX", "VIX"), ("10年债", "US10Y"), ("美元", "DXY"), ("黄金", "GOLD"), ("原油", "WTI"), ("比特币", "BTC")]
    f = [(n, quote(s)) for n, s in futs]
    o = []
    for n, s in others:
        q = quote(s)
        if q:
            px = q["price"]
            o.append(f"{n} {px:,.0f}({pct_str(q['pct'], 1)})" if px >= 1000 else (f"{n} {px:.2f}({pct_str(q['pct'], 1)})"))
    return f, o


def live_indices():
    return [(n, quote(s)) for n, s in [("标普", "SPX"), ("纳指", "IXIC"), ("道指", "DJI")]] + [("VIX", quote("VIX"))]


def watch_lines(syms):
    out = []
    for s in syms:
        q = quote(s)
        if q:
            out.append(f"{s} {q['price']:,.2f}({pct_str(q['pct'])})")
    return out


def options_unusual(sym, now=None):
    """粗略的期权异常:单个合约成交量大、远超未平仓量、成交金额大。数据来自 Yahoo,有延迟。"""
    c = core()
    out = []
    try:
        base = c._yh_open(f"https://query2.finance.yahoo.com/v7/finance/options/{urllib.parse.quote(sym)}?x=1")["optionChain"]["result"][0]
        exps = base["expirationDates"][:OPT["expiries"]]
        chains = [base["options"][0]] + [c._yh_open(f"https://query2.finance.yahoo.com/v7/finance/options/{urllib.parse.quote(sym)}?date={e}")["optionChain"]["result"][0]["options"][0] for e in exps[1:]]
    except Exception:
        return out
    vmin = OPT["etf_vol_min"] if sym in OPT["etfs"] else OPT["vol_min"]
    for ch in chains:
        exp = datetime.datetime.fromtimestamp(ch["expirationDate"], datetime.timezone.utc).strftime("%m/%d")
        for kind, arr in (("看涨", ch.get("calls", [])), ("看跌", ch.get("puts", []))):
            for x in arr:
                vol, oi, last = x.get("volume") or 0, x.get("openInterest") or 0, x.get("lastPrice") or 0
                if vol >= vmin and vol >= OPT["ratio_min"] * max(oi, 1) and vol * last * 100 >= OPT["notional_min"]:
                    out.append({"sym": sym, "exp": exp, "kind": kind, "strike": x.get("strike"), "vol": vol, "oi": oi, "notional": vol * last * 100})
    out.sort(key=lambda r: -r["notional"])
    return out[:OPT["per_symbol"]]


def money(n):
    return f"${n / 1e6:.1f}M" if n >= 1e6 else f"${n / 1e3:.0f}K"


def short(n):
    return f"{n / 1e3:.1f}k" if n >= 1000 else str(int(n))


def option_line(r):
    oi = f"未平仓 {short(r['oi'])},{r['vol'] / r['oi']:.1f}倍" if r["oi"] >= 10 else "几乎全是新开仓"
    return f"{r['sym']} {r['exp']} {r['strike']:g}{r['kind']} 成交 {short(r['vol'])}({oi})约 {money(r['notional'])}"


def news_scoring():
    import notify as N
    return N


def fresh_news(minutes_back, watch):
    """最近 minutes_back 分钟内的重要新闻:返回 (宏观列表, {代码: 列表})。已按重要性排序。"""
    c, N = core(), news_scoring()
    import time
    cut = time.time() - minutes_back * 60
    today = datetime.date.today()
    try:
        macro = [a for a in (c._fh("news", {"category": "general"}, 120) or []) if a["datetime"] >= cut]
    except Exception:
        macro = []
    company = {}
    for s in watch:
        try:
            company[s] = [a for a in (c._fh("company-news", {"symbol": s, "from": str(today - datetime.timedelta(days=2)), "to": str(today)}, 120) or []) if a["datetime"] >= cut]
        except Exception:
            company[s] = []
    cand = N.pick(macro, company, set())
    return [(sc, tag, a) for sc, tag, a in cand if sc > 0]


def zh(text):
    try:
        return core()._zh(text) or text
    except Exception:
        return text


def earnings_today(d):
    try:
        r = core().earnings(d.isoformat())
        return r.get("items", []) if not r.get("error") else []
    except Exception:
        return []


def macro_today(d):
    try:
        r = core().macro()
        return [x["name"] for x in r.get("calendar", []) if x["date"] == d.isoformat()]
    except Exception:
        return []


# =============================== 选股摘要 ===============================
def load_picks(path=None):
    try:
        return json.load(open(path or os.path.join(ROOT, "public", "screener.json")))
    except Exception:
        return None


def picks_section(P, prev=None, title="选股"):
    if not P or P.get("version") not in (2, 3):
        return [f"【{title}】暂无数据"]
    lines = [f"【{title}】行情日期 {P['dataDate']},市场环境 {P['regime']}"]
    prev_syms = {p["id"]: [r["sym"] for r in p["confirmed"]] for p in (prev or {}).get("presets", [])} if prev else None
    for p in P["presets"]:
        top = p["confirmed"][:5]
        names = "、".join(f"{r['sym']}{'(新)' if r['status'] == 'NEW' else ''}" for r in top) or "今天没有满足全部条件的"
        s = f"{p['name']}(确认 {p['confirmedTotal']}):{names}"
        if prev_syms is not None:
            now_s, old_s = [r["sym"] for r in top], prev_syms.get(p["id"], [])
            if now_s == old_s:
                s += " ← 与上次相同"
            else:
                add, rem = [x for x in now_s if x not in old_s], [x for x in old_s if x not in now_s]
                s += " ← " + (f"新进 {'、'.join(add)}" if add else "") + (" " if add and rem else "") + (f"退出 {'、'.join(rem)}" if rem else "") + ("" if add or rem else "排序有变化")
        lines.append(s)
    return lines


# =============================== 消息 ===============================
def build_brief(d, ctx):
    lines = [f"盘前早报 {d.strftime('%m/%d')} 周{'一二三四五六日'[d.weekday()]}(美西 6:30 开盘)"]
    f, o = ctx["indices"]
    lines.append("【盘前指数】" + (index_line(f) or "暂无") + (" | " + " ".join(o) if o else ""))
    e = ctx["earnings"]
    pre, post = [x for x in e if x["when"] == "盘前"], [x for x in e if x["when"] == "盘后"]
    lines.append("【今日财报(市值>50亿美元)】" + ("盘前:" + "、".join(x["sym"] for x in pre[:8]) + (f" 等{len(pre)}家" if len(pre) > 8 else "") if pre else "盘前:无") +
                 " | " + ("盘后:" + "、".join(x["sym"] for x in post[:8]) + (f" 等{len(post)}家" if len(post) > 8 else "") if post else "盘后:无"))
    macro = ctx["macro_events"]
    mnews = [x for x in ctx["news"] if x[1] == "宏观"][:3]
    lines.append("【今日宏观】" + ("数据发布:" + "、".join(macro) if macro else "今天没有重要数据发布") + ("" if not mnews else ""))
    for sc, tag, a in mnews:
        lines.append(f"· {zh(a['headline'])[:60]}")
    wn = [x for x in ctx["news"] if x[1] != "宏观"]
    seen, picked = set(), []
    for sc, tag, a in wn:
        if tag not in seen:
            seen.add(tag); picked.append((tag, a))
    lines.append("【自选股要闻】" + ("无" if not picked else ""))
    for tag, a in picked[:5]:
        lines.append(f"· {tag}:{zh(a['headline'])[:56]}")
    lines += picks_section(ctx["picks"], title="今日选股(昨日收盘后更新)")
    lines.append("模型信号与信息摘要,不保证收益,请自行判断风险")
    return f"盘前早报 {d.strftime('%m/%d')}", "\n".join(lines)


def build_hourly(t, ctx, with_picks=False):
    lines = [f"盘中 {t.strftime('%H:%M')} 美西"]
    lines.append("【指数】" + index_line(ctx["indices"]))
    lines.append("【自选】" + "  ".join(ctx["watch"]))
    opts = ctx["options"]
    lines.append("【期权异常】" + ("无" if not opts else ""))
    lines += [f"· {option_line(r)}" for r in opts[:4]]
    n = ctx["news"][:3]
    if n:
        lines.append("【过去 1 小时要闻】")
        lines += [f"· [{tag}] {zh(a['headline'])[:56]}" for sc, tag, a in n]
    if with_picks:
        lines += picks_section(ctx["picks"], ctx.get("prev_picks"), title="选股更新(盘中,未收盘)")
    lines.append("期权异常为按成交量/未平仓量/金额的粗略筛选,不代表方向;请自行判断风险")
    return f"盘中摘要 {t.strftime('%H:%M')}" + ("·选股" if with_picks else ""), "\n".join(lines)


def build_post(ctx):
    P = ctx["picks"]
    lines = picks_section(P, ctx.get("prev_picks"), title="盘后最终选股")
    lines.append("模型信号,不保证收益,请自行判断风险")
    return f"盘后选股 {P['dataDate'] if P else ''}", "\n".join(lines)



# =============================== 每周:周五总结 / 周日前瞻 ===============================
def week_change(sym, ref_date):
    """本周涨跌:最新收盘价对比"上周五"(ref_date 往前 7 天)的收盘价。"""
    try:
        r = core()._chart(sym, "1mo", "1d", 300)
        ts, cl = r["timestamp"], r["indicators"]["quote"][0]["close"]
        rows = [(datetime.datetime.fromtimestamp(t, datetime.timezone.utc).date(), c) for t, c in zip(ts, cl) if c]
        base_d = ref_date - datetime.timedelta(days=7)
        base = [c for d, c in rows if d <= base_d]
        return (rows[-1][1] / base[-1] - 1) * 100 if base else (rows[-1][1] / rows[0][1] - 1) * 100
    except Exception:
        return None


def week_dates(friday):
    mon = friday - datetime.timedelta(days=4)
    return [mon + datetime.timedelta(days=i) for i in range(5)]


def earnings_surprises(dates, min_cap=5e9, top=6):
    """本周已发财报(市值>50 亿美元)的 EPS 超预期情况,按市值排序。"""
    c = core()
    rows = []
    for d in dates:
        try:
            for x in (c._fh("calendar/earnings", {"from": str(d), "to": str(d)}, 600) or {}).get("earningsCalendar", []):
                if x.get("epsActual") is not None and x.get("epsEstimate") not in (None, 0) and abs(x["epsEstimate"]) > 0.01:
                    rows.append({"sym": x["symbol"], "sur": (x["epsActual"] / x["epsEstimate"] - 1) * 100 if x["epsEstimate"] > 0 else None})
        except Exception:
            pass
    caps = c._yh_caps([r["sym"] for r in rows]) if rows else {}
    rows = [dict(r, cap=caps.get(r["sym"], {}).get("cap", 0)) for r in rows]
    return sorted([r for r in rows if r["cap"] >= min_cap], key=lambda r: -r["cap"])[:top]


def history_changes(monday, path=None):
    """本周「强趋势龙头」名单的变化:本周新入选的、本周失效的。"""
    try:
        recs = json.load(open(path or os.path.join(ROOT, "public", "picks_history.json")))["records"]
    except Exception:
        return {}
    new = [k for k, v in recs.items() if v.get("first_date", "") >= str(monday) and v.get("status") in ("NEW", "STILL_VALID")]
    inv = [k for k, v in recs.items() if v.get("status") == "INVALIDATED" and v.get("last_date", "") >= str(monday)]
    return {"trend": {"new": new, "inv": inv}}


NAMES = {"trend": "强趋势龙头", "growth": "激进成长", "pullback": "强势回调", "reversal": "超跌反转"}


def build_weekly_summary(friday, ctx):
    ds = week_dates(friday)
    lines = [f"本周总结 {ds[0].strftime('%m/%d')}–{ds[-1].strftime('%m/%d')}"]
    lines.append("【指数本周】" + "  ".join(f"{n} {pct_str(p)}" for n, p in ctx["indices"] if p is not None))
    w = [(s, p) for s, p in ctx["watch"] if p is not None]
    if w:
        best, worst = max(w, key=lambda x: x[1]), min(w, key=lambda x: x[1])
        lines.append("【自选本周】" + "  ".join(f"{s} {pct_str(p)}" for s, p in w) + f"(最强 {best[0]},最弱 {worst[0]})")
    e = ctx["earnings"]
    lines.append("【本周财报(市值>50亿美元)】" + ("无" if not e else "、".join(f"{r['sym']}({'超预期 ' + format(r['sur'], '+.0f') + '%' if r['sur'] is not None else '亏损基数'})" for r in e)))
    snap = ctx["macro_snapshot"]
    if snap:
        lines.append("【宏观最新值】" + "  ".join(snap))
    n = ctx["news"][:5]
    if n:
        lines.append("【本周要闻】")
        lines += [f"· {zh(a['headline'])[:56]}" for sc, tag, a in n]
    ch = ctx["picks_changes"]
    if ch:
        lst = lambda a: ("、".join(a[:5]) + (f" 等{len(a)}只" if len(a) > 5 else "")) if a else "无"
        lines.append("【本周选股变化】" + ";".join(f"{NAMES.get(k, k)}:新入选 {lst(v['new'])} / 失效 {lst(v['inv'])}" for k, v in ch.items()))
    lines += picks_section(ctx["picks"], title="当前选股 Top5")
    lines.append("模型信号与信息总结,不保证收益,请自行判断风险")
    return f"本周总结 {friday.strftime('%m/%d')}", "\n".join(lines)


def build_weekly_preview(sunday, ctx):
    mon = sunday + datetime.timedelta(days=1)
    ds = [mon + datetime.timedelta(days=i) for i in range(5)]
    lines = [f"下周前瞻 {ds[0].strftime('%m/%d')}–{ds[-1].strftime('%m/%d')}"]
    f, o = ctx["indices"]
    lines.append("【期货(周日晚已开盘)】" + (index_line(f) or "暂无") + (" | " + " ".join(o) if o else ""))
    wk = "一二三四五"
    lines.append("【财报(市值>50亿美元)】")
    busiest = (None, 0)
    for i, d in enumerate(ds):
        e = ctx["earnings"].get(d, [])
        if len(e) > busiest[1]:
            busiest = (i, len(e))
        lines.append(f"· 周{wk[i]}:" + ("、".join(x["sym"] for x in e[:5]) + (f" 等{len(e)}家" if len(e) > 5 else "") if e else "无"))
    mine = [(wk[i], x["sym"], x["when"]) for i, d in enumerate(ds) for x in ctx["earnings"].get(d, []) if x["sym"] in ctx["watch"]]
    if mine:
        lines.append("【你的自选股财报】" + "、".join(f"{s} 周{w}{wh}" for w, s, wh in mine))
    ev = ctx["macro_events"]
    lines.append("【宏观数据】" + ("无" if not ev else ""))
    lines += [f"· {d.strftime('%m/%d')} 周{'一二三四五六日'[d.weekday()]} {n}" for d, n in ev]
    hol = [d for d in ds if d.isoformat() in HOLIDAYS]
    notes = []
    if hol:
        notes.append("休市:" + "、".join(d.strftime('%m/%d') for d in hol))
    if busiest[0] is not None and busiest[1] >= 8:
        notes.append(f"财报最密集:周{wk[busiest[0]]}({busiest[1]}家大公司)")
    for n, q in ctx.get("levels", []):
        if n == "VIX" and q and q["price"] >= 25:
            notes.append(f"VIX {q['price']:.1f} 偏高,波动可能较大")
    notes.append("提前收盘日(感恩节次日、平安夜)请自行留意")
    lines.append("【需要注意】" + ";".join(notes))
    lines += picks_section(ctx["picks"], title="当前选股(上周五收盘后)")
    lines.append("模型信号与信息前瞻,不保证收益,请自行判断风险")
    return f"下周前瞻 {ds[0].strftime('%m/%d')}", "\n".join(lines)


def macro_snapshot():
    try:
        m = core().macro()
        names = {"DGS10": "10年债", "FEDFUNDS": "联邦基金利率", "CPIAUCSL": "CPI同比", "UNRATE": "失业率"}
        return [f"{names[x['id']]} {x['value']:.2f}%" for x in m.get("items", []) if x["id"] in names]
    except Exception:
        return []


def macro_events_between(d0, d1):
    try:
        r = core().macro()
        out = []
        for x in r.get("calendar", []):
            d = datetime.date.fromisoformat(x["date"])
            if d0 <= d <= d1:
                out.append((d, x["name"]))
        return out
    except Exception:
        return []


# =============================== 发送 / 入口 ===============================
def send(title, message, click="", dry=False):
    if dry or os.environ.get("DRY_RUN"):
        print("====", title, "====\n" + message + "\n")
        return
    import tg
    if not tg.configured():
        print("没有设置 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID,跳过推送")
        return
    tg.send_tg(title, message, click or SITE)
    print("已推送:", title)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    dry, force = "--dry" in argv, "--force" in argv
    now = now_pt()
    if cmd == "gate":
        ok = gate(argv[2])
        print(f"{argv[2]} 现在美西 {now.strftime('%Y-%m-%d %H:%M')} → {'运行' if ok else '跳过'}")
        if os.environ.get("GITHUB_OUTPUT"):
            open(os.environ["GITHUB_OUTPUT"], "a").write(f"run={'true' if ok else 'false'}\n")
        return
    if not force and not gate(cmd):
        print(f"{cmd}:现在不是推送时间或今天休市,跳过(美西 {now.strftime('%H:%M')})")
        return
    watch = CFG["watchlist"]
    prev = load_picks(os.environ.get("PREV_SCREENER"))
    if cmd == "brief":
        ctx = {"indices": premarket_indices(), "earnings": earnings_today(now.date()), "macro_events": macro_today(now.date()),
               "news": fresh_news(15 * 60, watch), "picks": load_picks()}
        t, m = build_brief(now.date(), ctx)
    elif cmd in ("hourly", "mid"):
        opts = []
        for s in watch:
            opts += options_unusual(s)
        opts.sort(key=lambda r: -r["notional"])
        ctx = {"indices": live_indices(), "watch": watch_lines(watch), "options": opts, "news": fresh_news(60, watch), "picks": load_picks(), "prev_picks": prev}
        t, m = build_hourly(now, ctx, with_picks=(cmd == "mid"))
    elif cmd == "post":
        t, m = build_post({"picks": load_picks(), "prev_picks": prev})
    elif cmd == "weekly_summary":
        d = now.date()
        ctx = {"indices": [(n, week_change(s, d)) for n, s in [("标普", "SPX"), ("纳指", "IXIC"), ("道指", "DJI")]], "watch": [(s, week_change(s, d)) for s in watch],
               "earnings": earnings_surprises(week_dates(d)), "macro_snapshot": macro_snapshot(), "news": fresh_news(5 * 24 * 60, watch),
               "picks_changes": history_changes(week_dates(d)[0]), "picks": load_picks()}
        t, m = build_weekly_summary(d, ctx)
    elif cmd == "weekly_preview":
        d = now.date()
        mon = d + datetime.timedelta(days=1)
        days = [mon + datetime.timedelta(days=i) for i in range(5)]
        ctx = {"indices": premarket_indices(), "earnings": {x: earnings_today(x) for x in days}, "watch": watch, "macro_events": macro_events_between(days[0], days[-1]),
               "levels": [("VIX", quote("VIX"))], "picks": load_picks()}
        t, m = build_weekly_preview(d, ctx)
    else:
        print(__doc__)
        return
    send(t, m, SITE + ("/#picks" if cmd in ("mid", "post") else ""), dry)


if __name__ == "__main__":
    main(sys.argv)
