"""跟进检验:不再从网格里挑最好的,而是只用样本内诊断得到的"一个"简单假设(相对强度 RS63 排在样本内前 20%),
在样本外检验它,并且算出组合层面的 beta 和 alpha(扣掉承担市场风险带来的收益)。运行:python3 tools/backtest_followup.py"""
import gzip, math, os, pickle, statistics, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "api")]
import backtest_tune as T

E = pickle.load(gzip.open(T.CACHE_EV, "rb"))
spy = pickle.load(gzip.open(T.CACHE_BARS, "rb"))["spy"]
sidx = {d: i for i, d in enumerate(spy["d"])}


def series(evs, d0, d1, hold=60):
    day = {}
    for e in evs:
        i0 = sidx.get(e["date"])
        if i0 is None:
            continue
        p = e["path"]
        L = min(len(p), hold + 1)
        for k in range(L):
            r = p[k] - (T.COST if k == 0 else 0) - (T.COST if k == L - 1 and len(p) >= hold + 1 else 0)
            day.setdefault(i0 + 1 + k, []).append(r)
    idx = [i for i in range(len(spy["d"])) if d0 <= spy["d"][i] <= d1]
    return [(sum(day[i]) / len(day[i])) if i in day else 0.0 for i in idx], [spy["a"][i] / spy["a"][i - 1] - 1 for i in idx]


def report(name, evs):
    r, s = series(evs, T.SPLIT, spy["d"][-1])
    mr, ms = statistics.mean(r), statistics.mean(s)
    cov = sum((a - mr) * (b - ms) for a, b in zip(r, s)) / len(r)
    var = statistics.pvariance(s)
    beta = cov / var
    alpha = (mr - beta * ms) * 252
    eq = peak = 1.0
    mdd = 0.0
    for x in r:
        eq *= 1 + x
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    yrs = len(r) / 252
    sd = statistics.pstdev(r)
    print(f"{name:34} 年化 {(eq ** (1 / yrs) - 1) * 100:+6.1f}%  回撤 {mdd * 100:+6.1f}%  夏普 {mr / sd * math.sqrt(252):4.2f}  beta {beta:4.2f}  年化alpha {alpha * 100:+5.1f}%  事件 {len(evs)}")


print(f"SPY 买入持有(样本外 {T.SPLIT} 起):")
r, s = series([], T.SPLIT, spy["d"][-1])
eq = peak = 1.0
mdd = 0.0
for x in s:
    eq *= 1 + x
    peak = max(peak, eq)
    mdd = min(mdd, eq / peak - 1)
print(f"{'SPY':34} 年化 {(eq ** (252 / len(s)) - 1) * 100:+6.1f}%  回撤 {mdd * 100:+6.1f}%  夏普 {statistics.mean(s) / statistics.pstdev(s) * math.sqrt(252):4.2f}  beta 1.00  年化alpha +0.0%")
for fam in ("growth", "pullback"):
    IS = [e for e in E["events"][fam] if e["date"] < T.SPLIT and e["f"].get("rs63") is not None]
    thr = sorted(e["f"]["rs63"] for e in IS)[int(len(IS) * 0.8)]
    OOS = [e for e in E["events"][fam] if e["date"] >= T.SPLIT]
    hi = [e for e in OOS if e["f"].get("rs63") is not None and e["f"]["rs63"] > thr]
    lo = [e for e in OOS if e["f"].get("rs63") is not None and e["f"]["rs63"] <= thr]
    s1, s2 = T.summ(hi), T.summ(lo)
    print(f"\n{T.NAMES_ZH[fam]}:样本内 RS63 前 20% 的门槛 = {thr:.2f}")
    print(f"  样本外 RS63>{thr:.2f}:{s1['n']} 个事件,60 天超 SPY {s1['excess'] * 100:+.1f}%,按月 t={s1['t']:.2f},平均 ATR% {s1['atrp'] * 100:.1f}")
    print(f"  样本外 RS63≤{thr:.2f}:{s2['n']} 个事件,60 天超 SPY {s2['excess'] * 100:+.1f}%,按月 t={s2['t']:.2f},平均 ATR% {s2['atrp'] * 100:.1f}")
    report(f"{T.NAMES_ZH[fam]} RS63 前20%", hi)
    report(f"{T.NAMES_ZH[fam]} 家族全体", OOS)
rev = E["events"]["reversal"]
OOSr = [e for e in rev if e["date"] >= T.SPLIT]
print()
report("超跌反转 家族全体", OOSr)
bear_in = [e for e in rev if e["date"] < T.SPLIT]
print(f"\n超跌反转 样本内 按环境(60天超SPY):", {rg: (len(v), round(T.summ(v)['excess'] * 100, 1)) for rg in ('BULL', 'NEUTRAL', 'BEAR') for v in [[e for e in bear_in if e['reg'] == rg]] if v})
print(f"超跌反转 样本外 按环境(60天超SPY):", {rg: (len(v), round(T.summ(v)['excess'] * 100, 1)) for rg in ('BULL', 'NEUTRAL', 'BEAR') for v in [[e for e in OOSr if e['reg'] == rg]] if v})
