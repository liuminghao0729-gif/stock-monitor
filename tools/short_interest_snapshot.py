"""做空趋势快照(FINRA 官方的每半月做空申报,经 OpenBB 的 FINRA 接口取得,Nasdaq 备用)。
用法(必须用装了 openbb 的 Python):
  HOME=$PWD/.tools/openbbhome .tools/openbbvenv/bin/python tools/short_interest_snapshot.py [AAPL NVDA ...]
不带参数时,股票清单 = 自选股 + 每日选股结果里出现的股票(最多 150 只)。
结果写入 public/short_interest.json,每只股票保留最近 12 期。每半月才更新一次,页面上会标出数据日期。
只用免费、无需 Key 的接口;单只失败就跳过,不影响其他股票;全部失败则不覆盖旧文件。"""
import datetime, json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "short_interest.json")
MAX_SYMS, KEEP = 150, 12


def symbols():
    s = []
    try:
        s += json.load(open(os.path.join(ROOT, "push", "config.json")))["watchlist"]
    except Exception:
        pass
    try:
        for p in json.load(open(os.path.join(ROOT, "public", "screener.json")))["presets"]:
            for k in ("confirmed", "others"):
                s += [x["sym"] for x in p.get(k, []) if x.get("sym")]
    except Exception:
        pass
    seen = []
    for x in s:
        if x not in seen:
            seen.append(x)
    return seen[:MAX_SYMS]


def fetch(obb, sym):
    try:                                   # FINRA 覆盖所有美股(含纽交所),Nasdaq 作备用
        rows = obb.finra.equity.shorts.short_interest(symbol=sym).results
    except Exception:
        rows = obb.nasdaq.equity.ownership.short_interest(symbol=sym).results
    rows = sorted(rows, key=lambda r: r.settlement_date)
    out = []
    for i, r in enumerate(rows):          # 两个接口的"变化"口径不同,统一用相邻两期的持仓自己算
        prev = rows[i - 1].current_short_position if i else None
        chg = round(r.current_short_position / prev - 1, 4) if prev else None
        out.append({"d": r.settlement_date.isoformat(), "pos": r.current_short_position, "adv": r.avg_daily_volume,
                    "dtc": round(r.days_to_cover, 2) if r.days_to_cover is not None else None, "chg": chg})
    return out[-KEEP:]


def main():
    from openbb import obb
    syms = [a.upper() for a in sys.argv[1:]] or symbols()
    out, skipped = {}, []
    for s in syms:
        try:
            r = fetch(obb, s)
            if r:
                out[s] = r
            else:
                skipped.append(s)
        except Exception:
            skipped.append(s)            # ETF/指数/新股没有做空申报,正常跳过
        time.sleep(0.15)
    if not out:
        sys.exit("没有取到任何做空数据,不覆盖旧文件")
    latest = max(v[-1]["d"] for v in out.values())
    json.dump({"version": 1, "source": "FINRA 半月做空申报(经 OpenBB/FINRA)", "updated": datetime.date.today().isoformat(),
               "latest": latest, "symbols": out}, open(OUT, "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {len(out)} 只,跳过 {len(skipped)} 只({', '.join(skipped[:10])}),最新申报日 {latest}")


if __name__ == "__main__":
    main()
