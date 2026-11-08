"""短线反弹候选池的分析:
 1) 三种思路并列(超跌反转 R / 企稳放量形态 P / 趋势内回调到下沿 B),各用一组固定条件,对比标普 500;
 2) 消融:每个条件单独拿掉(其他条件仍满足)会多出哪些股票,这些被挡掉的股票后来跑得怎么样——看是哪个条件在把好股票筛出去;
 3) 赢家特征:池子里后来跑赢最多的 20% 和输得最多的 20%,哪些特征差别最大(样本内找,样本外验证);
 4) 贪心搜索:从空条件/三种固定条件出发,逐个加入样本内提升最大的条件、微调阈值,再看样本外;
 5) 随机对照:把收益打乱,同样的搜索能找到多漂亮的样本内结果。
「扣 beta 超额」= 净收益 - beta × 同期标普收益。成本每边 0.10%,入场 T+1 开盘价。样本内 = 2023 年以前,样本外 = 2023 年以后。
通过标准(事先定):样本外扣 beta 超额 > 0、原始超额 > 0、按月 t ≥ 2、样本外事件数 ≥ 150。
运行:python3 tools/rebound_search.py → tools/rebound_search_report.md        仅为研究,不构成投资建议。"""
import gzip, math, os, pickle, random, statistics, sys, time
from array import array
from itertools import compress

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "api")]
import backtest_tune as T
import rebound_pool as RP

HS = RP.HS
COST = 0.001
CUTS = (0.10, 0.20, 0.30, 0.50, 0.70)
nan = float("nan")


def net(g):
    return (1 + g) * (1 - COST) / (1 + COST) - 1


def pc(x, d=2, s=True):
    return "--" if x is None else (f"{x * 100:+.{d}f}%" if s else f"{x * 100:.{d}f}%")


def tt(x):
    return "--" if x is None else f"{x:.1f}"


class Pool:
    def __init__(self):
        Z = pickle.load(gzip.open(RP.OUT, "rb"))
        order = sorted(range(Z["n"]), key=lambda i: Z["date"][i])
        self.n = Z["n"]
        self.date = [Z["date"][i] for i in order]
        self.sym = [Z["sym"][i] for i in order]
        self.f = {k: [Z["cols"][k][i] for i in order] for k in RP.FEATS}
        self.path = Z["path"]
        self.order = order
        beta = self.f["beta"]
        self.ex, self.adj, self.ret, self.valid = {}, {}, {}, {}
        for h in HS:
            R, SP = Z["R"][h], Z["SP"][h]
            ex, ad, rt, v = [nan] * self.n, [nan] * self.n, [nan] * self.n, bytearray(self.n)
            for j, i in enumerate(order):
                r = R[i]
                if r == r:
                    nr = net(r)
                    rt[j], ex[j], ad[j] = nr, nr - SP[i], nr - beta[j] * SP[i]
                    v[j] = 1
            self.ex[h], self.adj[h], self.ret[h], self.valid[h] = ex, ad, rt, bytes(v)
        self.is_flag = bytes(1 if d < T.SPLIT else 0 for d in self.date)
        # 月份切片
        self.months = []
        i = 0
        while i < self.n:
            ym = self.date[i][:7]
            j = i
            while j < self.n and self.date[j][:7] == ym:
                j += 1
            self.months.append((ym, i, j))
            i = j
        self.is_months = [m for m in self.months if m[0] + "-01" < T.SPLIT]
        self.oos_months = [m for m in self.months if m[0] + "-01" >= T.SPLIT]
        self.vint = {h: int.from_bytes(self.valid[h], "big") for h in HS}
        self.full = int.from_bytes(b"\x01" * self.n, "big")
        self.q = {}      # 样本内分位点
        for k in RP.FEATS:
            vals = sorted(x for x, fl in zip(self.f[k], self.is_flag) if fl and x == x)
            self.q[k] = vals

    def mask(self, fn):
        return int.from_bytes(bytes(1 if fn(j) else 0 for j in range(self.n)), "big")

    def ev(self, m, h, which, adj=None, ex=None, min_months=6):
        adj = adj if adj is not None else self.adj[h]
        ex = ex if ex is not None else self.ex[h]
        mb = (m & self.vint[h]).to_bytes(self.n, "big")
        ma, me, n = [], [], 0
        wins = 0
        for ym, a, b in (self.is_months if which == "is" else self.oos_months):
            sl = mb[a:b]
            c = sum(sl)
            if c == 0:
                continue
            xa = list(compress(adj[a:b], sl))
            xe = list(compress(ex[a:b], sl))
            ma.append((sum(xa) / c, c))
            me.append(sum(xe) / c)
            n += c
            wins += sum(1 for x in xe if x > 0)
        if n < 20 or len(ma) < min_months:
            return None
        means = [x for x, _ in ma]
        sd = statistics.stdev(means) if len(means) > 2 else 0
        t = statistics.mean(means) / (sd / math.sqrt(len(means))) if sd else None
        # 事件加权的平均(而不是月份平均)作为主指标
        tot_a = sum(x * c for x, c in ma) / n
        tot_e = sum(e * c for e, (_, c) in zip(me, ma)) / n
        return {"n": n, "adj": tot_a, "raw": tot_e, "t": t, "months": len(ma), "win": wins / n}


# =============================== 三种思路的固定条件 ===============================
def concept_rules(P):
    f = P.f
    R0 = [("池子里属于 R(RSI 衰竭后回升)", lambda j: f["baseR"][j] == 1), ("15 日最低 RSI ≤ 35", lambda j: f["rmin15"][j] <= 35), ("当前 RSI ≥ 40", lambda j: f["rsi"][j] >= 40),
          ("深度:区间位置 ≤ 35% 或回撤 ≥ 25%", lambda j: f["rpos"][j] <= .35 or f["dd52"][j] >= .25), ("站上 20 日线", lambda j: f["above20"][j] == 1), ("今日量比 ≥ 1.2", lambda j: f["vr20"][j] >= 1.2)]
    P0 = [("池子里属于 P(企稳放量形态)", lambda j: f["baseP"][j] == 1), ("最低点后 ≥ 5 天不创新低", lambda j: f["dsl"][j] >= 5), ("回调低点高于前低", lambda j: f["hl"][j] >= 0),
          ("回调缩量(≤ 反弹均量 × 0.9)", lambda j: f["shrink"][j] <= 0.9), ("今日放量(≥ 回调均量 × 1.2)", lambda j: f["resume"][j] >= 1.2),
          ("回调占反弹 20%–80%", lambda j: 0.2 <= f["retrace"][j] <= 0.8), ("离 120 日高点回撤 ≥ 25%", lambda j: f["dd120"][j] >= .25)]
    B0 = [("池子里属于 B(趋势内回调)", lambda j: f["baseB"][j] == 1), ("近 5 天触及布林下轨或贴近均线", lambda j: f["touch5"][j] == 1 or f["near5"][j] == 1), ("5 日最低 RSI ≤ 50", lambda j: f["rmin5"][j] <= 50),
          ("RSI 回升 ≥ 3 点", lambda j: f["bounce"][j] >= 3), ("今日上涨", lambda j: f["ret1"][j] > 0)]
    return {"R": ("超跌反转 R", R0), "P": ("企稳放量形态 P", P0), "B": ("趋势内回调到下沿 B", B0)}


# =============================== 贪心搜索 ===============================
class Greedy:
    def __init__(self, P):
        self.P = P
        self.cands = []
        for k in RP.FEATS:
            if k in ("baseR", "baseP", "baseB"):
                continue
            col = P.f[k]
            vals = P.q[k]
            if len(vals) < 500:
                continue
            binary = set(vals) <= {0.0, 1.0}
            if binary:
                for val in (1.0, 0.0):
                    self.cands.append((k, "eq", val, P.mask(lambda j, col=col, val=val: col[j] == val)))
                continue
            for x in CUTS:
                lo_t, hi_t = vals[int(x * (len(vals) - 1))], vals[int((1 - x) * (len(vals) - 1))]
                self.cands.append((k, "high", x, P.mask(lambda j, col=col, t_=hi_t: col[j] >= t_)))
                self.cands.append((k, "low", x, P.mask(lambda j, col=col, t_=lo_t: col[j] <= t_)))
        self.evals = 0

    def name(self, c):
        k, d, x = c[:3]
        if d == "eq":
            return f"{k}={'是' if x == 1.0 else '否'}"
        return f"{k}{'最高' if d == 'high' else '最低'}{int(x * 100)}%"

    def ev(self, m, h, which, adj=None, ex=None):
        self.evals += 1
        return self.P.ev(m, h, which, adj, ex, min_months=12 if which == "is" else 6)

    def run(self, h, seed_mask=None, adj=None, ex=None, max_add=3, min_n=500):
        cur = seed_mask if seed_mask is not None else self.P.full
        chosen, best_is = [], -9.0
        base = self.ev(cur, h, "is", adj, ex)
        if base and base["n"] >= min_n:
            best_is = base["adj"]
        for step in range(max_add):
            best = None
            for c in self.cands:
                if any(c[0] == z[0] for z in chosen):
                    continue
                r = self.ev(cur & c[3], h, "is", adj, ex)
                if r and r["n"] >= min_n and (best is None or r["adj"] > best[1]["adj"]):
                    best = (c, r)
            if not best or best[1]["adj"] < best_is + 0.0005:
                break
            chosen.append(best[0]); cur &= best[0][3]; best_is = best[1]["adj"]
        for _ in range(2):                                   # 微调阈值
            for i in range(len(chosen)):
                others = seed_mask if seed_mask is not None else self.P.full
                for j, z in enumerate(chosen):
                    if j != i:
                        others &= z[3]
                best = (chosen[i], self.ev(others & chosen[i][3], h, "is", adj, ex))
                for c in self.cands:
                    if c[0] == chosen[i][0] and c[1] == chosen[i][1] and c[2] != chosen[i][2]:
                        r = self.ev(others & c[3], h, "is", adj, ex)
                        if r and r["n"] >= min_n and (best[1] is None or r["adj"] > best[1]["adj"]):
                            best = (c, r)
                chosen[i] = best[0]
        cur = seed_mask if seed_mask is not None else self.P.full
        for z in chosen:
            cur &= z[3]
        return chosen, cur


def main():
    t0 = time.time()
    P = Pool()
    G = Greedy(P)
    print(f"池子事件 {P.n:,};候选条件 {len(G.cands)};样本内月份 {len(P.is_months)},样本外 {len(P.oos_months)};用时 {time.time() - t0:.0f} 秒", flush=True)
    out = ["# 短线反弹:三种思路并列回测、消融、赢家特征、贪心搜索(对比标普 500)\n"]
    w = out.append
    w(f"数据:10 年日线;候选池 {P.n:,} 个事件(同一只股票 10 天内不重复;当时估计市值 ≥ 50 亿、价格 ≥ 10、成交额 ≥ 2000 万),样本内 = 2023 年以前({len(P.is_months)} 个月),样本外 = 2023 年以后({len(P.oos_months)} 个月)。\n")
    w("入场 T+1 开盘价,持有 1、3、5、10、30、60、120 天,成本每边 0.10%。「扣 beta 超额」= 净收益 - beta × 同期标普收益;「原始超额」= 净收益 - 同期标普收益。\n")
    w("**偏差(会让数字偏好看):** 幸存者偏差(退市股不在里面,对「买下跌的股票」影响最大)。通过标准(事先定):样本外扣 beta 超额 > 0、原始超额 > 0、按月 t ≥ 2、样本外事件数 ≥ 150。\n")
    rules = concept_rules(P)
    masks = {}
    for key, (nm, comps) in rules.items():
        m = P.full
        for _, fn in comps:
            m &= P.mask(fn)
        masks[key] = m
    # ---------- 1. 并列 ----------
    w("## 1. 三种思路各用一组固定条件,并列对比\n")
    w("| 思路 | 持有 | 时期 | 事件数 | 平均净收益 | **原始超额(对标普)** | **扣 beta 超额** | 胜标普 | 按月 t |\n|---|---|---|---|---|---|---|---|---|")
    for key, (nm, comps) in rules.items():
        for h in HS:
            for per in ("is", "oos"):
                r = P.ev(masks[key], h, per)
                if r:
                    ret = None
                    w(f"| {nm} | {h} 天 | {'样本内' if per == 'is' else '样本外'} | {r['n']:,} | -- | **{pc(r['raw'])}** | **{pc(r['adj'])}** | {pc(r['win'], 0, False)} | {tt(r['t'])} |")
    w("\n对照:池子里的全部事件(不加任何条件)——\n\n| 持有 | 时期 | 事件数 | 原始超额 | 扣 beta 超额 | 按月 t |\n|---|---|---|---|---|---|")
    for h in (1, 5, 10, 30, 60):
        for per in ("is", "oos"):
            r = P.ev(P.full, h, per)
            if r:
                w(f"| {h} 天 | {'样本内' if per == 'is' else '样本外'} | {r['n']:,} | {pc(r['raw'])} | {pc(r['adj'])} | {tt(r['t'])} |")
    # ---------- 2. 消融 ----------
    w("\n## 2. 消融:每个条件被挡掉的股票后来表现如何\n")
    w("对每个条件:取「其他条件都满足、只有这一个条件不满足」的事件(也就是被这一个条件挡在门外的股票),看它们的扣 beta 超额(样本内 → 样本外)。**如果被挡掉的股票比入选的股票更好,说明这个条件在把好股票筛出去。**\n")
    for key, (nm, comps) in rules.items():
        cm = [P.mask(fn) for _, fn in comps]
        w(f"\n### {nm}\n\n| 被挡在门外的原因(只因这个条件不满足) | 事件数(样本内) | 5 天 样本内→样本外 | 10 天 | 30 天 |\n|---|---|---|---|---|")
        sel = {h: (P.ev(masks[key], h, "is"), P.ev(masks[key], h, "oos")) for h in (5, 10, 30)}
        w("| **(对照)入选的股票** | " + f"{P.ev(masks[key], 5, 'is')['n'] if P.ev(masks[key], 5, 'is') else 0:,}" + " | " + " | ".join(f"{pc(sel[h][0]['adj']) if sel[h][0] else '--'} → {pc(sel[h][1]['adj']) if sel[h][1] else '--'}" for h in (5, 10, 30)) + " |")
        for i, (cname, _) in enumerate(comps[1:], 1):
            others = P.full
            for j, m_ in enumerate(cm):
                if j != i:
                    others &= m_
            only = others & ~cm[i] & P.full
            r5 = P.ev(only, 5, "is")
            if not r5:
                continue
            cells = []
            for h in (5, 10, 30):
                a, b = P.ev(only, h, "is"), P.ev(only, h, "oos")
                cells.append(f"{pc(a['adj']) if a else '--'} → {pc(b['adj']) if b else '--'}")
            w(f"| 不满足:{cname} | {r5['n']:,} | " + " | ".join(cells) + " |")
    # ---------- 3. 赢家特征 ----------
    w("\n## 3. 赢家和输家的特征差别\n")
    w("在整个候选池里,把「扣 beta 超额」最高的 20%(赢家)和最低的 20%(输家)比较:每个特征的平均排名(0–1,按样本内分布换算)差 = 赢家 - 输家。正数 = 赢家的这个特征更大。样本内找、样本外验证(两边符号一致才可信)。波动大的股票两头都多,所以用「赢家 - 输家」来抵消这个影响。\n")
    for h in (5, 10, 30):
        def ranks(idx_list, k):
            vals = P.q[k]
            import bisect
            return [bisect.bisect_left(vals, P.f[k][j]) / len(vals) for j in idx_list if P.f[k][j] == P.f[k][j]]
        eff = {}
        for per in ("is", "oos"):
            idx = [j for j in range(P.n) if P.valid[h][j] and (P.is_flag[j] == 1) == (per == "is")]
            idx.sort(key=lambda j: P.adj[h][j])
            q = len(idx) // 5
            lo, hi = idx[:q], idx[-q:]
            for k in RP.FEATS:
                if k in ("baseR", "baseP", "baseB") or len(P.q[k]) < 500:
                    continue
                a, b = ranks(hi, k), ranks(lo, k)
                if len(a) > 200 and len(b) > 200:
                    eff.setdefault(k, {})[per] = statistics.mean(a) - statistics.mean(b)
        top = sorted((k for k in eff if "is" in eff[k] and "oos" in eff[k]), key=lambda k: -abs(eff[k]["is"]))[:10]
        w(f"\n### 持有 {h} 天\n\n| 特征 | 样本内 赢家-输家 排名差 | 样本外 排名差 | 符号一致 |\n|---|---|---|---|")
        for k in top:
            w(f"| {k} | {eff[k]['is']:+.3f} | {eff[k]['oos']:+.3f} | {'是' if eff[k]['is'] * eff[k]['oos'] > 0 else '否'} |")
    # ---------- 4. 贪心搜索 ----------
    w("\n## 4. 贪心搜索:从空条件/三种固定条件出发,逐个加条件、微调阈值(只用样本内选)\n")
    w("**样本内选条件,样本外检验。** 起点:「空」= 池子里所有事件;R/P/B = 先用对应思路的固定条件,再继续加条件。\n")
    w("| 起点 | 持有 | 加入的条件 | 样本内 事件/扣beta/按月t | **样本外 事件/扣beta/原始/按月t** | 通过 |\n|---|---|---|---|---|---|")
    finals = {}
    for seed_name, seed_m in (("空", None), ("R", masks["R"]), ("P", masks["P"]), ("B", masks["B"])):
        for h in HS:
            chosen, cur = G.run(h, seed_m)
            ri, ro = G.ev(cur, h, "is"), G.ev(cur, h, "oos")
            names = " 且 ".join(G.name(c) for c in chosen) or "(无)"
            ok = bool(ro and ri and ro["adj"] > 0 and ro["raw"] > 0 and ro["t"] is not None and ro["t"] >= 2 and ro["n"] >= 150)
            finals[(seed_name, h)] = (chosen, cur, ri, ro, ok)
            w(f"| {seed_name} | {h} 天 | {names} | " + (f"{ri['n']:,} / {pc(ri['adj'])} / {tt(ri['t'])}" if ri else "--") + " | " + (f"{ro['n']:,} / **{pc(ro['adj'])}** / {pc(ro['raw'])} / {tt(ro['t'])}" if ro else "--") + f" | {'**通过**' if ok else '未通过'} |")
            print(f"起点 {seed_name} 持有 {h} 天:{names} 样本内 {pc(ri['adj']) if ri else '--'} 样本外 {pc(ro['adj']) if ro else '--'} {'通过' if ok else ''}  评估 {G.evals} 用时 {time.time() - t0:.0f} 秒", flush=True)
    # ---------- 5. 随机对照 ----------
    w("\n## 5. 过拟合对照:把收益在事件之间随机打乱,同样的「空起点」搜索(持有 10 天)\n\n| 次数 | 样本内 扣beta超额 | 样本外 扣beta超额 |\n|---|---|---|")
    rng = random.Random(5)
    for rep in range(5):
        h = 10
        idx = [j for j in range(P.n) if P.valid[h][j]]
        vals = [(P.adj[h][j], P.ex[h][j]) for j in idx]
        rng.shuffle(vals)
        adj_p, ex_p = list(P.adj[h]), list(P.ex[h])
        for j, (x, y) in zip(idx, vals):
            adj_p[j], ex_p[j] = x, y
        chosen, cur = G.run(h, None, adj_p, ex_p)
        ri, ro = G.ev(cur, h, "is", adj_p, ex_p), G.ev(cur, h, "oos", adj_p, ex_p)
        w(f"| {rep + 1} | {pc(ri['adj']) if ri else '--'} | {pc(ro['adj']) if ro else '--'} |")
    w(f"\n总共评估 {G.evals:,} 次。\n")
    pickle.dump({"finals": {k: ([G.name(c) for c in v[0]], v[2], v[3], v[4]) for k, v in finals.items()}}, open(os.path.join(HERE, ".cache", "rebound_finals.pkl"), "wb"))
    open(os.path.join(HERE, "rebound_search_report.md"), "w", encoding="utf-8").write("\n".join(out))
    print(f"已生成 tools/rebound_search_report.md,总用时 {time.time() - t0:.0f} 秒")


if __name__ == "__main__":
    main()
