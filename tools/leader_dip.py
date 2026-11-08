"""强趋势龙头里的「回调买点」:你说的「趋势内的超跌反弹」。
思路:先用「强趋势龙头」条件(离 200 日线最高 5%、ATR% 最高 30%、3 个月涨幅最高 50%)圈出一批股票,
再看在这批股票里,「刚回调/超卖/触及下沿」的时点买入,是否比「不管什么时点买入」更好(都扣成本、扣 beta、对比标普)。
只用样本内选加什么条件,样本外检验。运行:python3 tools/leader_dip.py → tools/leader_dip_report.md     仅为研究,不构成投资建议。"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "api")]
import signal_search as SS

pc, tt = SS.pc, SS.tt
DIP_VARS = {"dd20", "rmin5", "rsi14", "pctb", "bb_low", "ret5", "mom21", "cons_down", "clv", "gap", "rng", "macd_hn", "macd_x3", "vr20", "updn20", "dist50", "near_high", "ll20", "ret5"}


def main():
    t0 = time.time()
    D = SS.load()
    S_ = SS.Search(D)
    nm = SS.NAMES
    seed = S_.full
    for k, dr, x in (("dist200", "high", 0.05), ("atrp", "high", 0.30), ("mom63", "high", 0.50)):
        c = next(c for c in S_.cands if nm[c[0]] == k and c[1] == dr and c[2] == x)
        seed &= c[3]
    seed_vars = {nm.index(k) for k in ("dist200", "atrp", "mom63")}
    allowed = {nm.index(k) for k in DIP_VARS if k in nm}
    exclude = tuple(i for i in range(len(nm)) if i not in allowed)
    out = ["# 强趋势龙头里的回调买点(趋势内的超跌反弹)\n"]
    w = out.append
    w("先圈出「强趋势龙头」(离 200 日线最高 5% 且 ATR% 最高 30% 且 3 个月涨幅最高 50%),再看在其中加「回调/超卖/触及下沿」类条件,是否让买点更好。只在样本内选条件,样本外检验;成本每边 0.10%;「扣 beta 超额」= 净收益 - beta × 同期标普收益。\n")
    w("**偏差:** 幸存者偏差(退市股不在里面);样本外 2023 年起基本是牛市。通过标准(事先定):样本外扣 beta 超额 > 0、原始超额 > 0、按月 t ≥ 2,并且**要比「只用龙头条件不挑买点」更好**。\n")
    w("| 持有 | 买点条件 | 样本内 扣beta/按月t/观测 | **样本外 扣beta超额** | 样本外 原始超额 | 样本外 按月t | 样本外观测 | 对照:只用龙头条件(样本外扣beta/原始) | 通过 |\n|---|---|---|---|---|---|---|---|---|")
    for h in SS.HS:
        base_o = S_.ev(seed, h, "oos")
        chosen, stages, fin = S_.run(h, seed=seed, exclude=exclude, min_obs=1200)
        ri, ro = fin["is"], fin["oos"]
        beat = bool(ro and base_o and ro["adj"] > base_o["adj"])
        ok = bool(ro and ro["adj"] > 0 and ro["raw"] > 0 and ro["t"] is not None and ro["t"] >= 2 and beat)
        w(f"| {h} 天 | {' 且 '.join(fin['conds']) or '(没有找到提升)'} | " + (f"{pc(ri['adj'])} / {tt(ri['t'])} / {ri['n']:,}" if ri else "--") + " | " + (f"**{pc(ro['adj'])}** | {pc(ro['raw'])} | {tt(ro['t'])} | {ro['n']:,}" if ro else "-- | -- | -- | --")
          + f" | {(pc(base_o['adj']) + ' / ' + pc(base_o['raw'])) if base_o else '--'} | {'**通过**' if ok else '未通过'} |")
        print(f"持有 {h} 天:{fin['conds']} 样本内 {pc(ri['adj']) if ri else '--'} 样本外 {pc(ro['adj']) if ro else '--'} 对照 {pc(base_o['adj']) if base_o else '--'} {'通过' if ok else ''}  用时 {time.time() - t0:.0f} 秒", flush=True)
    open(os.path.join(HERE, "leader_dip_report.md"), "w", encoding="utf-8").write("\n".join(out))
    print("已生成 tools/leader_dip_report.md")


if __name__ == "__main__":
    main()
