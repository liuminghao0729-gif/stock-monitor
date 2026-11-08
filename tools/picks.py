"""每日推荐:强趋势龙头(中期,持有 30–120 天)。只做这一个组合。
条件(都是「每个交易日、在当时成交额排名前 50% 的股票里」的截面排名,和回测一致):
  入选:离 200 日线的距离 排名前 5%,且 ATR% 排名前 30%,且 3 个月涨幅 排名前 50%。
  保留(防止名单天天换):已经在名单里的股票,只要仍满足放宽后的条件(前 10% / 前 40% / 前 60%)就继续留着。
回测结论(如实):该类条件在样本内外都有正的超额,但组合 beta 约 1.8–1.95,最大回撤约 -37%(标普 -19%),夏普低于同 beta 的杠杆标普;
收益集中在少数年份和主题;幸存者偏差去不掉。不是「稳赢」。仅为条件筛选,不构成投资建议。
用法:python3 tools/picks.py [--session pre|mid|post] [--history rw|ro|off] [--limit N] [--out 文件]"""
import argparse, datetime, json, math, os, sys, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "api"), HERE]
import _core as core
import screener_v2 as S

ENTRY = {"dist200": 0.95, "atrp": 0.70, "mom63": 0.50}       # 排名下限(0–1,越大越靠前)
STAY = {"dist200": 0.90, "atrp": 0.60, "mom63": 0.40}
SHOW = 5
MIN_ADV, MIN_PRICE, MIN_CAP = 20e6, 10.0, 5e9
KEEP_DAYS = 5


def rank_pct(vals):
    n = len(vals)
    order = sorted(range(n), key=lambda i: vals[i])
    out = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = ((i + j) / 2) / (n - 1) if n > 1 else 0.5
        i = j + 1
    return out


def metrics(b, spy_adj):
    """单只股票的指标(只用当天及以前的数据)。历史不足返回 None。"""
    h, l, c, a, v = b["h"], b["l"], b["c"], b["adj"], b["v"]
    n = len(c)
    if n < 260:
        return None
    s50, s200 = S.sma(c, 50), S.sma(c, 200)
    atr = S.wilder_atr_adx(h, l, c)[0][-1]
    if not atr or s200[-1] is None:
        return None
    r = [a[i] / a[i - 1] - 1 for i in range(n - 126, n)]
    s = [spy_adj[i] / spy_adj[i - 1] - 1 for i in range(n - 126, n)]
    mr, ms = sum(r) / 126, sum(s) / 126
    var = sum((x - ms) ** 2 for x in s) / 126
    beta = sum((x - mr) * (y - ms) for x, y in zip(r, s)) / 126 / var if var > 0 else 1.0
    px = c[-1]
    adv = sum(c[i] * v[i] for i in range(n - 60, n)) / 60
    rs = S.rsi_wilder(c, 14)[-1]
    return {"price": px, "adv": adv, "dist200": px / s200[-1] - 1, "atrp": atr / px, "mom63": a[-1] / a[-64] - 1, "mom126": a[-1] / a[-127] - 1,
            "slope50": s50[-1] / s50[-21] - 1, "dd52": 1 - px / max(h[-252:]), "beta": beta, "rsi": rs, "day": px / c[-2] - 1, "date": b["dates"][-1]}


def decide(rows, prev):
    """rows: [{sym, adv, price, dist200, atrp, mom63, ...}](已满足 价格/成交额/市值 的合格股票)。
    返回 (入选列表, 保留列表, 当日排名表)。先取成交额排名前 50% 的股票,再在其中做截面排名。"""
    if len(rows) < 50:
        return [], [], {}
    advr = rank_pct([r["adv"] for r in rows])
    liquid = [r for r, x in zip(rows, advr) if x >= 0.5]
    rk = {k: rank_pct([r[k] for r in liquid]) for k in ENTRY}
    ranks = {}
    entry, stay = [], []
    for i, r in enumerate(liquid):
        rr = {k: rk[k][i] for k in ENTRY}
        ranks[r["sym"]] = rr
        if all(rr[k] >= ENTRY[k] for k in ENTRY):
            entry.append(r["sym"])
        if r["sym"] in prev and all(rr[k] >= STAY[k] for k in STAY):
            stay.append(r["sym"])
    return entry, stay, ranks


def update_state(prev_rec, entry, stay, date, keep_days=KEEP_DAYS):
    """prev_rec: {sym: {first_date, last_date, status, ...}}。名单 = 今天入选 ∪ 仍满足放宽条件的老成员。
    老成员今天不再满足放宽条件 → INVALIDATED(保留 keep_days 天用于展示)。"""
    rec = {k: dict(v) for k, v in prev_rec.items()}
    live_prev = {k for k, v in rec.items() if v.get("status") in ("NEW", "STILL_VALID")}
    today = set(entry) | set(stay)
    d0 = datetime.date.fromisoformat(date)
    for s in today:
        r = rec.get(s, {})
        if s in live_prev:
            r["status"] = "NEW" if r.get("last_date") == date and r.get("status") == "NEW" else "STILL_VALID"     # 同一天重跑不改状态
        else:
            r = {"first_date": date, "status": "NEW"}
        r["last_date"] = date
        rec[s] = r
    for s in live_prev - today:
        rec[s].update(status="INVALIDATED", last_date=date)
    for s, r in list(rec.items()):
        if r.get("status") == "INVALIDATED" and (d0 - datetime.date.fromisoformat(r["last_date"])).days > keep_days:
            del rec[s]
    return rec


def regime(spy):
    c = spy["c"]
    s50, s200 = S.sma(c, 50), S.sma(c, 200)
    if c[-1] > s200[-1] and s50[-1] > s50[-21]:
        return "BULL"
    if c[-1] < s200[-1] and s200[-1] < s200[-21]:
        return "BEAR"
    return "NEUTRAL"


def run(limit=0, out_path=None, history="rw", session="post"):
    t0 = time.time()
    print("1/3 股票池…")
    uni = [u for u in S.get_universe() if u["type_ok"] and u["cap"] >= MIN_CAP]
    if limit:
        uni = uni[:limit]
    spy = S.get_bars("SPY")
    spy_by = dict(zip(spy["dates"], spy["adj"]))
    print(f"    候选 {len(uni)} 只")

    def one(u):
        try:
            b = S.get_bars(u["sym"])
            al, last = [], spy["adj"][0]
            for d in b["dates"]:
                last = spy_by.get(d, last)
                al.append(last)
            m = metrics(b, al)
            return (u, m) if m else None
        except Exception:
            return None
    print("2/3 行情与指标…")
    with ThreadPoolExecutor(8) as ex:
        got = [x for x in ex.map(one, uni) if x]
    rows = []
    for u, m in got:
        if m["price"] >= MIN_PRICE and m["adv"] >= MIN_ADV:
            rows.append(dict(m, sym=u["sym"], name=u["name"], cap=u["cap"]))
    print(f"    合格股票 {len(rows)} 只,用时 {time.time() - t0:.0f} 秒")
    hist_path = os.path.join(ROOT, "public", "picks_history.json")
    prev = {}
    if history in ("rw", "ro") and os.path.exists(hist_path):
        try:
            prev = json.load(open(hist_path)).get("records", {})
        except Exception:
            prev = {}
    live_prev = {k for k, v in prev.items() if v.get("status") in ("NEW", "STILL_VALID")}
    entry, stay, ranks = decide(rows, live_prev)
    date = max(r["date"] for r in rows)
    rec = update_state(prev, entry, stay, date)
    by = {r["sym"]: r for r in rows}
    listed = [s for s, v in rec.items() if v["status"] in ("NEW", "STILL_VALID") and s in by]
    listed.sort(key=lambda s: -by[s]["dist200"])
    def row(s):
        r, rr = by[s], ranks.get(s, {})
        return {"sym": s, "name": r["name"], "price": round(r["price"], 2), "cap": r["cap"], "day": round(r["day"] * 100, 2), "status": rec[s]["status"], "since": rec[s]["first_date"],
                "dist200": round(r["dist200"], 4), "mom63": round(r["mom63"], 4), "mom126": round(r["mom126"], 4), "atrp": round(r["atrp"], 4), "beta": round(r["beta"], 2),
                "rsi": round(r["rsi"], 1), "dd52": round(r["dd52"], 4), "slope50": round(r["slope50"], 4), "ranks": {k: round(v, 3) for k, v in rr.items()}}
    inval = [{"sym": s, "name": by[s]["name"] if s in by else s, "date": v["last_date"]} for s, v in rec.items() if v["status"] == "INVALIDATED"]
    out = {"version": 3, "session": session, "intraday": session == "mid", "asof": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "dataDate": date, "regime": regime(spy),
           "universe": len(rows), "rules": {"entry": ENTRY, "stay": STAY},
           "presets": [{"id": "trend", "name": "强趋势龙头(中期)", "confirmed": [row(s) for s in listed[:SHOW]], "confirmedTotal": len(listed), "others": listed[SHOW:SHOW + 30], "invalidated": inval[:8]}]}
    path = out_path or os.path.join(ROOT, "public", "screener.json")
    json.dump(out, open(path, "w"), ensure_ascii=False)
    if history == "rw":
        json.dump({"records": rec, "updated": date}, open(hist_path, "w"), ensure_ascii=False)
    print(f"3/3 完成:名单 {len(listed)} 只(入选 {len(entry)},保留 {len(set(stay) - set(entry))}),前 {SHOW}:{listed[:SHOW]};用时 {time.time() - t0:.0f} 秒 → {path}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--history", choices=["rw", "ro", "off"], default="rw")
    ap.add_argument("--session", choices=["pre", "mid", "post"], default="post")
    a = ap.parse_args()
    run(a.limit, a.out, a.history, a.session)
