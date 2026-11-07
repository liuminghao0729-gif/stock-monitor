"""把 tools/backtest_results.json 整理成可读的报告 tools/backtest_report.md。运行:python3 tools/backtest_report.py"""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(HERE, "backtest_results.json")))
pc = lambda x, s=True: "--" if x is None else (f"{x * 100:+.1f}%" if s else f"{x * 100:.0f}%")
f2 = lambda x: "--" if x is None else f"{x:.2f}"
T = d["tests"]
out = [f"# 选股技术信号回测报告(V1.0 对比 V2.0)\n\n生成日期 {d['asof']} · 数据区间 {d['period'][0]} 到 {d['period'][1]} · 股票 {d['stocks']} 只 · 含交易成本(每边 {d['cost_per_side'] * 100:.1f}%)\n"]
out.append("""## 先读这里:这份回测能说明什么、不能说明什么
- **只测了技术条件**(均线、RSI、MACD、布林带、成交量、相对强度)。营收增长、自由现金流等**基本面条件没有测**:免费数据没有"当时已公布的财报"(只有季度截止日,没有公告日期),硬测会有前视偏差。所以这里的"V2.0"是 **V2.0 的技术条件**,不等于完整的 V2.0 选股。
- **幸存者偏差:** 股票池是今天的成分股,历史上退市、被收购、跌出名单的公司不在里面。所有数字(包括基准)都会偏好看。
- **市值前视:** 筛选范围用今天的市值(历史市值拿不到)。
- **样本只有约 5 年**,基本是一个牛市为主的周期;同一天触发的信号彼此高度相关,样本的有效数量比"事件数"小得多,小的差异(1% 左右)不能当作显著。
- 入场:信号 T 日收盘后确认 → **T+1 开盘价**入场 → 持有 20/60/120 个交易日后按收盘价出场;复权价;同一只股票同一策略 20 个交易日内不重复计入。
- **"超基准"才是关键:** 基准 = 同一批股票、同样流动性条件下,随便哪天入场的平均收益。信号要有价值,必须比它好。
""")
b = d["baseline"]
out.append("## 基准(随便哪天入场)\n\n| 持有 | 基准平均收益 | 同期 SPY | 样本 |\n|---|---|---|---|")
for hh, v in b.items():
    out.append(f"| {hh} 天 | {pc(v['mean'])} | {pc(v['spy'])} | {v['n']:,} |")
for hh in ("20", "60", "120"):
    out.append(f"\n## 持有 {hh} 个交易日(含成本)\n\n| 组合 | 版本 | 事件数 | 胜率 | 平均收益 | 中位收益 | 超 SPY | **超基准** | 盈亏比 | 夏普 | 组合最大回撤 | 单笔平均最大浮亏 | 最差一笔 |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for k, t in T.items():
        a = t["all"][hh]
        if a:
            out.append(f"| {t['name']} | {t['version']} | {a['n']:,} | {pc(a['win'], False)} | {pc(a['mean'])} | {pc(a['median'])} | {pc(a['excess_spy'])} | **{pc(a['excess_base'])}** | {f2(a['pf'])} | {f2(a['sharpe'])} | {pc(a['mdd'])} | {pc(a['mae_avg'])} | {pc(a['worst'])} |")
out.append("\n夏普 = 单笔收益均值 / 标准差 × √(252/持有天数),是粗略口径。组合最大回撤 = 每天持仓的所有交易等权平均后的权益曲线回撤。\n")
out.append("## 不同市场环境(持有 60 天;环境按入场日的 SPY 判断)\n\n| 组合 | 版本 | 牛市(事件/超基准) | 中性 | 熊市 |\n|---|---|---|---|---|")
for k, t in T.items():
    cells = []
    for rg in ("BULL", "NEUTRAL", "BEAR"):
        a = t["regime"][rg]["60"]
        cells.append(f"{a['n']:,} / {pc(a['excess_base'])}" if a else "--")
    out.append(f"| {t['name']} | {t['version']} | " + " | ".join(cells) + " |")
out.append("\n## 样本内 / 样本外(持有 60 天,以 2024-11-01 划分;数字为 事件数 / 超基准)\n\n| 组合 | 版本 | 样本内 | 样本外 |\n|---|---|---|---|")
for k, t in T.items():
    i, o = t["in_sample"]["60"], t["out_sample"]["60"]
    out.append(f"| {t['name']} | {t['version']} | " + (f"{i['n']:,} / {pc(i['excess_base'])}" if i else "--") + " | " + (f"{o['n']:,} / {pc(o['excess_base'])}" if o else "--") + " |")
out.append("\n## 按年份(持有 60 天;数字为 事件数 / 超基准)\n\n| 组合 | 版本 | " + " | ".join(sorted({y for t in T.values() for y in t["by_year"]})) + " |\n|---|---|" + "---|" * len({y for t in T.values() for y in t["by_year"]}))
years = sorted({y for t in T.values() for y in t["by_year"]})
for k, t in T.items():
    out.append(f"| {t['name']} | {t['version']} | " + " | ".join((f"{t['by_year'][y]['n']:,} / {pc(t['by_year'][y]['excess_base'])}" if t["by_year"].get(y) else "--") for y in years) + " |")
out.append("""
## 读结果的方式(我的解读,不是投资建议)
1. **激进成长(趋势 + 相对强度):在这批数据里没有显示出优势。** 持有 20、60、120 天,V1.0 和 V2.0 的收益都**低于随便哪天入场的基准**(超基准为负),按年份看多数年份也是负的。牛市里"追强势股"没有比随机买更好。
2. **强势回调:V1.0 略好于基准,V2.0 基本等于基准。** V2.0 的信号数量是 V1.0 的约 2 倍(条件放宽、加了止跌确认),但每个信号的平均质量下降,样本外(近两年)超基准转为小幅为负。这是 V2.0 技术条件放宽的**取舍**:信号多了,优势被稀释。
3. **超跌反转:有正的超额,但样本很小、波动大。** V1.0 只有一百来个事件,超基准看起来很大,但小样本很可能是运气;V2.0 有 600 多个事件,超基准小得多(约 +1%),而且样本外转负。这类信号在**熊市和中性市场**里相对更好,在牛市里反而不如随便买。
4. **整体判断:** 这些技术条件**没有在 5 年样本里显示出稳定、显著的选股优势**。它们更适合当"过滤和提醒",不应该被当作能预测涨跌的信号。V2.0 的真正新增价值在于财务安全(自由现金流等)和风险提示,这部分没法用免费数据回测。
5. **取舍(你要的"不只看胜率"):** 看胜率,三个组合在 60 天上大约 55% 到 70%,但这主要是整个市场这 5 年向上;胜率高不等于有优势,要看"超基准"。回撤方面 V2.0 的组合最大回撤普遍比 V1.0 小一点或持平,没有明显恶化。

## 还没做、做了才更可信的事
- 加入退市股票(需要付费的历史成分数据),消除幸存者偏差。
- 用历史市值而不是今天的市值。
- 基本面条件的回测(需要带公告日期的财报数据)。
- 对 V2.0 的个别参数做敏感性测试,并且只在样本内调、在样本外验证,防止过拟合。
""")
open(os.path.join(HERE, "backtest_report.md"), "w", encoding="utf-8").write("\n".join(out))
print("已生成 tools/backtest_report.md")
