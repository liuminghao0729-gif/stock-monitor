"""跟进:把"高波动/高 beta"因子的超额收益拆开——扣掉承担市场风险(beta × SPY 收益)之后还剩多少?
每个观测:调整后超额 = 股票收益 - beta126 × 同期 SPY 收益。再看最高 20% 和全体的平均。运行:python3 tools/factor_followup.py"""
import gzip, os, pickle, statistics, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "api")]
import backtest_tune as T
import factor_study as FS

Z = pickle.load(gzip.open(FS.DATA, "rb"))
dates, date_i, F, R, SP = Z["dates"], Z["date"], Z["F"], Z["R"], Z["SP"]
names = [c for c, _ in FS.FACTORS]
kb = names.index("beta126")
groups = {}
for o in range(len(date_i)):
    groups.setdefault(date_i[o], []).append(o)
gs = [g for g, v in groups.items() if len(v) >= 150]
lines = ["\n## 4. 追加检验:把高波动/高 beta 的超额收益拆开(扣掉 beta × 标普收益后还剩多少)\n",
         "调整后超额 = 股票收益 - 该股 126 日 beta × 同期标普收益。如果某个变量的最高 20% 只是承担了更高的市场风险,扣掉之后应该接近 0。\n",
         "| 变量(最高 20%) | 持有 | 时期 | 平均 beta | 原始超 SPY | **扣掉 beta 后** | 全体股票扣掉 beta 后 |\n|---|---|---|---|---|---|---|"]
for fac in ("beta126", "vol60", "atrp", "dvol"):
    k = names.index(fac)
    sgn = -1 if fac == "dvol" else 1
    for h in (60, 120):
        for per, sel in (("样本内", [g for g in gs if dates[g] < T.SPLIT]), ("样本外", [g for g in gs if dates[g] >= T.SPLIT])):
            raw, adj, bet, uni = [], [], [], []
            for g in sel:
                idx = [o for o in groups[g] if R[h][o] == R[h][o]]
                if len(idx) < 100:
                    continue
                vals = sorted(idx, key=lambda o: sgn * F[k][o])
                top = vals[int(len(vals) * 0.8):]
                raw.append(statistics.mean(R[h][o] - SP[h][o] for o in top))
                adj.append(statistics.mean(R[h][o] - F[kb][o] * SP[h][o] for o in top))
                bet.append(statistics.mean(F[kb][o] for o in top))
                uni.append(statistics.mean(R[h][o] - F[kb][o] * SP[h][o] for o in idx))
            f = lambda a: f"{statistics.mean(a) * 100:+.2f}%"
            lines.append(f"| {fac}{'(越小)' if fac == 'dvol' else ''} | {h} 天 | {per} | {statistics.mean(bet):.2f} | {f(raw)} | **{f(adj)}** | {f(uni)} |")
lines.append("\n解读:扣掉 beta 之后,高波动/高 beta 变量的超额收益缩小多少,就说明有多少是「承担了更高的市场风险」。剩下的部分里,还混着幸存者偏差(波动大的股票里破产、退市的不在样本中)和用今天市值筛选的前视偏差(今天市值 ≥ 50 亿的股票里,包含了历史上从小公司涨上来的赢家)。\n")
open(os.path.join(HERE, "factor_report.md"), "a", encoding="utf-8").write("\n".join(lines))
print("\n".join(lines))

# ---- 5. 只看当时最活跃的那一半股票(成交额排名前 50%),检验"高波动溢价"是否还在 ----
kd = names.index("dvol")
lines2 = ["\n## 5. 对照检验:只保留「当时成交额排名前 50%」的股票(最不可能是今天才涨上来的小公司)\n",
          "股票池是「今天市值 ≥ 50 亿」的股票,其中有些在历史上只是小公司,后来涨起来才进入今天的名单——这是前视偏差,会让「波动大、成交额小」的股票看起来特别好。只看当时成交额靠前的一半,可以削弱这个偏差(但不能消除,退市股仍然不在里面)。\n",
          "| 变量(最高 20%) | 持有 | 时期 | 平均 beta | 原始超 SPY | **扣掉 beta 后** | 这一半股票整体扣掉 beta 后 |\n|---|---|---|---|---|---|---|"]
for fac in ("vol60", "atrp"):
    k = names.index(fac)
    for h in (60, 120):
        for per, sel in (("样本内", [g for g in gs if dates[g] < T.SPLIT]), ("样本外", [g for g in gs if dates[g] >= T.SPLIT])):
            raw, adj, bet, uni = [], [], [], []
            for g in sel:
                idx = [o for o in groups[g] if R[h][o] == R[h][o]]
                if len(idx) < 200:
                    continue
                idx = sorted(idx, key=lambda o: F[kd][o])[len(idx) // 2:]
                vals = sorted(idx, key=lambda o: F[k][o])
                top = vals[int(len(vals) * 0.8):]
                raw.append(statistics.mean(R[h][o] - SP[h][o] for o in top))
                adj.append(statistics.mean(R[h][o] - F[kb][o] * SP[h][o] for o in top))
                bet.append(statistics.mean(F[kb][o] for o in top))
                uni.append(statistics.mean(R[h][o] - F[kb][o] * SP[h][o] for o in idx))
            f = lambda a: f"{statistics.mean(a) * 100:+.2f}%"
            lines2.append(f"| {fac} | {h} 天 | {per} | {statistics.mean(bet):.2f} | {f(raw)} | **{f(adj)}** | {f(uni)} |")
open(os.path.join(HERE, "factor_report.md"), "a", encoding="utf-8").write("\n".join(lines2))
print("\n".join(lines2))
