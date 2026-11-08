"""条件搜索:先看哪个变量最重要,再从单个条件开始,逐步加条件、微调阈值,看能不能找到跑赢标普 500 的组合。
为了尽量不被偏差骗:
  1) 只在"样本内"(2023 年以前)选条件、调阈值;样本外(2023 年以后)只用来检验,不回头改。
  2) 股票池只用「当时成交额排名前 50%」的股票(削弱"今天才涨上来的小公司"的前视偏差)。
  3) 优先看"扣掉 beta 后"的超额(股票收益 - beta × 同期标普收益),因为单纯多承担市场风险不算跑赢。同时也给原始超额。
  4) 跑一遍"随机打乱收益"的对照:同样的搜索流程在没有任何信号的数据上能找到多漂亮的样本内结果,用来衡量过拟合有多严重。
成本每边 0.10%;入场 T+1 开盘,持有 h 天 = 到 T+1+h 日收盘;幸存者偏差无法去掉(没有退市股)。
运行:python3 tools/signal_search.py → tools/signal_report.md   仅为研究,不构成投资建议。"""
import gzip, itertools, math, os, pickle, random, statistics, sys, time
from array import array
from itertools import compress

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "api")]
import backtest_tune as T
import factor_study as FS

HS = FS.HS
NAMES = [c for c, _ in FS.FACTORS]
DESC = dict(FS.FACTORS)
CUTS = (0.05, 0.10, 0.20, 0.30, 0.50)
COST = FS.COST
nan = float("nan")


def load():
    Z = pickle.load(gzip.open(FS.DATA, "rb"))
    dates, date_i, F, R, SP = Z["dates"], Z["date"], Z["F"], Z["R"], Z["SP"]
    N = len(date_i)
    kd, kb = NAMES.index("dvol"), NAMES.index("beta126")
    groups = {}
    for o in range(N):
        groups.setdefault(date_i[o], []).append(o)
    uidx, slices = [], []
    for g in sorted(groups):
        idx = groups[g]
        if len(idx) < 150:
            continue
        rk = FS.rank_pct([F[kd][o] for o in idx])
        mem = [o for o, r in zip(idx, rk) if r >= 0.5]          # 当时成交额前 50%
        a = len(uidx)
        uidx += mem
        slices.append((g, a, len(uidx)))
    n = len(uidx)
    RK = []
    for k in range(len(NAMES)):
        col = array("f", [0.0]) * n
        for g, a, b in slices:
            r = FS.rank_pct([F[k][uidx[j]] for j in range(a, b)])
            for j, x in zip(range(a, b), r):
                col[j] = x
        RK.append(col)
    adj, ex, raw, valid = {}, {}, {}, {}
    for h in HS:
        ad, e, v = array("f", [nan]) * n, array("f", [nan]) * n, bytearray(n)
        for j, o in enumerate(uidx):
            r = R[h][o]
            if r == r:
                nr = FS.net(r)
                e[j] = nr - SP[h][o]
                ad[j] = nr - F[kb][o] * SP[h][o]
                v[j] = 1
        adj[h], ex[h], valid[h] = ad, e, bytes(v)
    return {"dates": dates, "slices": slices, "n": n, "RK": RK, "adj": adj, "ex": ex, "valid": valid, "uidx": uidx, "F": F, "R": R, "SP": SP}


def month_t(by):
    m = [sum(v) / len(v) for v in by.values()]
    if len(m) < 3:
        return None, len(m), None
    sd = statistics.stdev(m)
    return (statistics.mean(m) / (sd / math.sqrt(len(m))) if sd else None), len(m), sum(1 for x in m if x > 0) / len(m)


class Search:
    def __init__(self, D):
        self.D = D
        self.n = D["n"]
        self.is_s = [s for s in D["slices"] if D["dates"][s[0]] < T.SPLIT]
        self.oos_s = [s for s in D["slices"] if D["dates"][s[0]] >= T.SPLIT]
        self.ym = {s[0]: D["dates"][s[0]][:7] for s in D["slices"]}
        self.cands = []          # (变量序号, 方向, 阈值, 掩码整数)
        for k in range(len(NAMES)):
            rk = D["RK"][k]
            for dr in ("high", "low"):
                for x in CUTS:
                    m = bytes((1 if (r >= 1 - x if dr == "high" else r <= x) else 0) for r in rk)
                    self.cands.append((k, dr, x, int.from_bytes(m, "big")))
        self.full = int.from_bytes(b"\x01" * self.n, "big")
        self.vint = {h: int.from_bytes(D["valid"][h], "big") for h in HS}
        self.evals = 0

    def ev(self, mask_int, h, which, adj=None, ex=None):
        """在样本内/外评价一个掩码:按日取平均,再对月份聚类。返回 dict。"""
        self.evals += 1
        adj = adj if adj is not None else self.D["adj"][h]
        ex = ex if ex is not None else self.D["ex"][h]
        mb = (mask_int & self.vint[h]).to_bytes(self.n, "big")
        by_a, by_e, n_obs, nd = {}, {}, 0, 0
        for g, a, b in (self.is_s if which == "is" else self.oos_s):
            m = mb[a:b]
            c = sum(m)
            if c < 8:
                continue
            by_a.setdefault(self.ym[g], []).append(sum(compress(adj[a:b], m)) / c)
            by_e.setdefault(self.ym[g], []).append(sum(compress(ex[a:b], m)) / c)
            n_obs += c
            nd += 1
        if nd < 12:
            return None
        ta, months, pos = month_t({k: [sum(v) / len(v)] for k, v in by_a.items()})
        da = [x for v in by_a.values() for x in v]
        de = [x for v in by_e.values() for x in v]
        return {"adj": statistics.mean(da), "raw": statistics.mean(de), "t": ta, "n": n_obs, "dates": nd, "months": months, "pos": pos}

    def cond_name(self, c):
        k, dr, x = c[:3]
        return f"{NAMES[k]}({DESC[NAMES[k]]}){'最高' if dr == 'high' else '最低'}{int(x * 100)}%"

    def run(self, h, adj=None, ex=None, max_conds=3, min_obs=3000, verbose=False):
        """贪心:每一步加入"样本内扣 beta 后超额"提升最大的条件,最后对每个阈值做微调。"""
        chosen, cur, best_is = [], self.full, -9.0
        stages = []
        for step in range(max_conds):
            best = None
            for c in self.cands:
                if any(c[0] == z[0] for z in chosen):
                    continue
                r = self.ev(cur & c[3], h, "is", adj, ex)
                if r and r["n"] >= min_obs and (best is None or r["adj"] > best[1]["adj"]):
                    best = (c, r)
            if not best or best[1]["adj"] < best_is + 0.0005:
                break
            chosen.append(best[0]); cur &= best[0][3]; best_is = best[1]["adj"]
            stages.append(self._snap(chosen, cur, h, adj, ex))
        for _ in range(2):          # 微调:逐个条件尝试所有阈值(其他条件不变)
            for i in range(len(chosen)):
                others = self.full
                for j, z in enumerate(chosen):
                    if j != i:
                        others &= z[3]
                best = (chosen[i], self.ev(others & chosen[i][3], h, "is", adj, ex))
                for c in self.cands:
                    if c[0] == chosen[i][0] and c[1] == chosen[i][1] and c[2] != chosen[i][2]:
                        r = self.ev(others & c[3], h, "is", adj, ex)
                        if r and r["n"] >= min_obs and (best[1] is None or r["adj"] > best[1]["adj"]):
                            best = (c, r)
                chosen[i] = best[0]
        cur = self.full
        for z in chosen:
            cur &= z[3]
        final = self._snap(chosen, cur, h, adj, ex)
        return chosen, stages, final

    def _snap(self, chosen, cur, h, adj, ex):
        return {"conds": [self.cond_name(c) for c in chosen], "is": self.ev(cur, h, "is", adj, ex), "oos": self.ev(cur, h, "oos", adj, ex), "mask": cur}


def pc(x, d=2, s=True):
    return "--" if x is None else (f"{x * 100:+.{d}f}%" if s else f"{x * 100:.{d}f}%")


def tt(x):
    return "--" if x is None else f"{x:.1f}"


def main():
    t0 = time.time()
    D = load()
    S_ = Search(D)
    print(f"股票池观测 {D['n']:,};候选条件 {len(S_.cands)};样本内抽样日 {len(S_.is_s)},样本外 {len(S_.oos_s)};准备用时 {time.time() - t0:.0f} 秒", flush=True)
    out = ["# 条件搜索报告:找出最重要的变量,逐步加条件、微调,和标普 500 对比\n"]
    w = out.append
    w(f"数据:10 年日线,股票池 = 当时成交额排名前 50% 的股票(今天市值 ≥ 50 亿美元、股价 ≥ 10 美元),每 5 个交易日抽样,{D['n']:,} 个观测。样本内 = 2023 年以前({len(S_.is_s)} 个抽样日),样本外 = 2023 年以后({len(S_.oos_s)} 个)。\n")
    w("入场 T+1 开盘价,持有 h 天 = 到 T+1+h 日收盘;成本每边 0.10%。**「扣 beta 超额」= 股票收益 - 该股 beta × 同期标普收益**(单纯多承担市场风险不算跑赢);「原始超额」= 股票收益 - 同期标普收益。**只在样本内选条件和调阈值,样本外只检验。**\n")
    w("**偏差(会让数字偏好看):** 幸存者偏差(没有退市股)、今天的市值筛选;样本外 2023 年起基本是牛市。\n")
    # ---------- 1. 单个条件排行 ----------
    w("## 1. 单个变量哪个最重要(每个持有期,样本内「扣 beta 超额」最高的 6 个单条件及其样本外表现)\n")
    w("条件写法:变量「最高 20%」= 每个抽样日里该变量排名前 20% 的股票。样本外表现是用样本内选出的同一个条件去检验。\n")
    importance = {}
    for h in HS:
        res = []
        for c in S_.cands:
            r = S_.ev(c[3], h, "is")
            if r and r["n"] >= 3000:
                res.append((r["adj"], c, r))
        res.sort(key=lambda x: -x[0])
        w(f"\n### 持有 {h} 天\n\n| 排名 | 单个条件 | 样本内 扣beta超额 | 样本内 按月t | **样本外 扣beta超额** | 样本外 原始超额 | 样本外 按月t |\n|---|---|---|---|---|---|---|")
        seen = set()
        k_ = 0
        for adjv, c, r in res:
            if c[0] in seen:
                continue
            seen.add(c[0])
            o = S_.ev(c[3], h, "oos")
            k_ += 1
            importance.setdefault(NAMES[c[0]], []).append((h, o["adj"] if o else None))
            w(f"| {k_} | {S_.cond_name(c)} | {pc(r['adj'])} | {tt(r['t'])} | **{pc(o['adj']) if o else '--'}** | {pc(o['raw']) if o else '--'} | {tt(o['t']) if o else '--'} |")
            if k_ >= 6:
                break
    w("\n### 变量重要性小结(样本内最好的单条件,在各持有期的样本外扣 beta 超额;只统计进过前 6 名的)\n\n| 变量 | 说明 | 进前 6 的持有期 | 样本外扣beta超额(各持有期) | 样本外为正的次数 |\n|---|---|---|---|---|")
    for nm, lst in sorted(importance.items(), key=lambda kv: -sum(1 for _, v in kv[1] if v and v > 0)):
        w(f"| {nm} | {DESC[nm]} | {len(lst)} | " + ", ".join(f"{h}天 {pc(v)}" for h, v in lst) + f" | {sum(1 for _, v in lst if v and v > 0)}/{len(lst)} |")
    # ---------- 2. 逐步加条件 ----------
    w("\n## 2. 从最好的单条件开始,逐步加条件(最多 3 个)并微调阈值——每个持有期各一个组合\n")
    w("流程:第 1 步选样本内扣 beta 超额最高的单条件;第 2、3 步在已选条件上再加一个提升最大的条件(提升不足 0.05% 就停);最后对每个条件的阈值再做微调。**整个流程只看样本内。**\n")
    w("| 持有 | 条件组合 | 样本内 扣beta超额 | 样本内 按月t | 样本内 观测数 | **样本外 扣beta超额** | 样本外 原始超额 | 样本外 按月t | 样本外 观测数 | 是否通过 |\n|---|---|---|---|---|---|---|---|---|---|")
    finals = {}
    for h in HS:
        chosen, stages, fin = S_.run(h)
        finals[h] = (chosen, stages, fin)
        i_, o_ = fin["is"], fin["oos"]
        ok = bool(o_ and o_["adj"] > 0 and o_["raw"] > 0 and o_["t"] is not None and o_["t"] >= 2)
        w(f"| {h} 天 | {' 且 '.join(fin['conds']) or '(没有找到)'} | {pc(i_['adj']) if i_ else '--'} | {tt(i_['t']) if i_ else '--'} | {i_['n']:,} | **{pc(o_['adj']) if o_ else '--'}** | {pc(o_['raw']) if o_ else '--'} | {tt(o_['t']) if o_ else '--'} | {o_['n']:,} | {'**通过**' if ok else '未通过'} |" if (i_ and o_) else f"| {h} 天 | {' 且 '.join(fin['conds']) or '(没有找到)'} | -- | -- | -- | -- | -- | -- | -- | 未通过 |")
        print(f"持有 {h} 天:{fin['conds']} 样本内 {pc(i_['adj']) if i_ else '--'} 样本外 {pc(o_['adj']) if o_ else '--'}  评估次数 {S_.evals} 用时 {time.time() - t0:.0f} 秒", flush=True)
    w("\n「通过」的标准(事先定好,不事后改):样本外扣 beta 超额 > 0、原始超额 > 0、按月 t ≥ 2。\n")
    w("\n### 逐步加条件的过程(样本内 → 样本外,扣 beta 超额)\n")
    for h in HS:
        chosen, stages, fin = finals[h]
        for si, st in enumerate(stages, 1):
            w(f"- {h} 天 第 {si} 步:{' 且 '.join(st['conds'])} → 样本内 {pc(st['is']['adj']) if st['is'] else '--'},样本外 {pc(st['oos']['adj']) if st['oos'] else '--'}")
    # ---------- 3. 随机对照 ----------
    w("\n## 3. 过拟合对照:把收益随机打乱(没有任何信号),同样的搜索流程能找到多漂亮的样本内结果\n")
    w("在每个抽样日里把股票的收益随机互换(变量和收益之间不再有关系),跑和上面完全相同的搜索(60 天持有)。如果在**没有任何信号**的数据上,搜索流程也能找到样本内 +X% 的条件,而样本外是 0,说明样本内的数字有多少是运气。\n")
    w("| 次数 | 样本内 扣beta超额(搜索找到的最好条件) | 样本外 扣beta超额 |\n|---|---|---|")
    rng = random.Random(7)
    ins, oos = [], []
    for rep in range(6):
        h = 60
        adj_p, ex_p = array("f", D["adj"][h]), array("f", D["ex"][h])
        for g, a, b in D["slices"]:
            ids = [j for j in range(a, b) if D["valid"][h][j]]
            vals = [(adj_p[j], ex_p[j]) for j in ids]
            rng.shuffle(vals)
            for j, (x, y) in zip(ids, vals):
                adj_p[j], ex_p[j] = x, y
        chosen, stages, fin = S_.run(h, adj_p, ex_p)
        ins.append(fin["is"]["adj"] if fin["is"] else 0)
        oos.append(fin["oos"]["adj"] if fin["oos"] else 0)
        w(f"| {rep + 1} | {pc(ins[-1])} | {pc(oos[-1])} |")
        print(f"随机对照 {rep + 1}:样本内 {pc(ins[-1])} 样本外 {pc(oos[-1])}", flush=True)
    w(f"\n平均:样本内 {pc(statistics.mean(ins))},样本外 {pc(statistics.mean(oos))}。\n")
    w(f"总共评估了 {S_.evals:,} 次条件组合。\n")
    open(os.path.join(HERE, "signal_report.md"), "w", encoding="utf-8").write("\n".join(out))
    print(f"已生成 tools/signal_report.md,总用时 {time.time() - t0:.0f} 秒")


if __name__ == "__main__":
    main()
