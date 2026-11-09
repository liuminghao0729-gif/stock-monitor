"""盘中每小时摘要(个人版):大盘速览、催化剂、资金与异动、持仓雷达、集中度、关注、风险提示。
全部由代码从 Yahoo / Finnhub 取数并计算,不用 AI、不编数字;取不到的栏目写「数据暂缺」或直接省略。
三种版本:完整版(7:30、12:30)、盘中版(10:30,多一个选股关注和板块)、简版(其他整点:大盘一行 + 催化剂 + 持仓雷达)。
简版没有任何异动时不发。「关注」只放通过回测的选股规则选出来的;「风险提示」只写客观事实,不是卖出建议。"""
import datetime, re
from concurrent.futures import ThreadPoolExecutor

import personal as P

BOARD = [("道指", "DJI"), ("标普", "SPX"), ("纳指", "IXIC"), ("罗素2000", "^RUT"), ("费城半导体", "^SOX"), ("标普期货", "ES=F"), ("纳指期货", "NQ=F"),
         ("VIX", "VIX"), ("10年债", "US10Y"), ("美元指数", "DXY"), ("原油", "WTI"), ("黄金", "GOLD"), ("比特币", "BTC")]
SECTORS = [("科技", "XLK"), ("金融", "XLF"), ("能源", "XLE"), ("医疗", "XLV"), ("可选消费", "XLY"), ("必需消费", "XLP"), ("工业", "XLI"),
           ("材料", "XLB"), ("公用事业", "XLU"), ("房地产", "XLRE"), ("通信", "XLC"), ("半导体", "SMH")]
# 杠杆/反向 ETF:代码 -> (标的, 倍数, 所属方向)。倍数为负是反向。不在表里的杠杆 ETF 不会被识别(可以随时补)。
LEV = {"SOXL": ("^SOX", 3, "半导体"), "SOXS": ("^SOX", -3, "半导体"), "TQQQ": ("QQQ", 3, "纳指/科技大盘"), "SQQQ": ("QQQ", -3, "纳指/科技大盘"),
       "QLD": ("QQQ", 2, "纳指/科技大盘"), "UPRO": ("SPY", 3, "标普大盘"), "SPXL": ("SPY", 3, "标普大盘"), "SSO": ("SPY", 2, "标普大盘"),
       "SPXS": ("SPY", -3, "标普大盘"), "SPXU": ("SPY", -3, "标普大盘"), "TECL": ("XLK", 3, "科技"), "TECS": ("XLK", -3, "科技"),
       "NVDL": ("NVDA", 2, "半导体"), "NVDU": ("NVDA", 2, "半导体"), "NVDX": ("NVDA", 2, "半导体"), "AMDL": ("AMD", 2, "半导体"), "MUU": ("MU", 2, "半导体"),
       "TSLL": ("TSLA", 2, "汽车"), "AAPU": ("AAPL", 2, "科技"), "MSFU": ("MSFT", 2, "科技"), "GGLL": ("GOOGL", 2, "通信"), "AMZU": ("AMZN", 2, "电商零售"),
       "METU": ("META", 2, "通信"), "PLTU": ("PLTR", 2, "科技"), "MSTU": ("MSTR", 2, "加密"), "CONL": ("COIN", 2, "加密"), "BITX": ("BTC", 2, "加密"),
       "LABU": ("XBI", 3, "生物科技"), "FAS": ("XLF", 3, "金融"), "ERX": ("XLE", 2, "能源"), "FNGU": (None, 3, "科技")}
ETF_GROUP = {"SMH": "半导体", "SOXX": "半导体", "DRAM": "半导体", "QQQ": "纳指/科技大盘", "VGT": "科技", "IGV": "科技", "XLK": "科技", "SPY": "标普大盘",
             "VOO": "标普大盘", "IVV": "标普大盘", "IWM": "小盘", "IBIT": "加密", "USO": "能源", "EWY": "韩国"}
SECTOR_CN = {"Technology": "科技", "Communication Services": "通信", "Consumer Cyclical": "可选消费", "Consumer Defensive": "必需消费", "Healthcare": "医疗",
             "Financial Services": "金融", "Industrials": "工业", "Energy": "能源", "Utilities": "公用事业", "Real Estate": "房地产", "Basic Materials": "材料"}
CFG = {"move_pct": 3.0, "vol_ratio": 1.8, "concentration": 0.5, "radar_max": 10, "risk_max": 6}


def tier_for(cmd, now):
    if cmd == "mid":
        return "mid"
    return "full" if now.hour in (7, 12) else "light"


def pct(x):
    return "--" if x is None else f"{x:+.2f}%"


def session_fraction(now):
    """美股常规时段(美西 6:30–13:00)已经过去的比例,用来把盘中成交量折算成全天。"""
    m = now.hour * 60 + now.minute - (6 * 60 + 30)
    return min(1.0, max(0.1, m / 390))


# ---------------------------------------------------------------- 共用部分(所有人一样,只算一次)
def board_lines(D, compact=False):
    q = {n: D.quote(s) for n, s in BOARD}
    def one(n):
        x = q.get(n)
        if not x:
            return None
        if n == "10年债":
            return f"{n} {x['price']:.2f}%({pct(x['pct'])})"
        if n == "VIX":
            return f"{n} {x['price']:.1f}({pct(x['pct'])})"
        return f"{n} {pct(x['pct'])}"
    pick = lambda names: "  ".join(s for s in (one(n) for n in names) if s)
    if compact:
        l = pick(["标普", "纳指", "费城半导体", "VIX", "10年债"])
        return [f"【大盘】{l}"] if l else ["【大盘】数据暂缺"]
    a, b = pick(["道指", "标普", "纳指", "罗素2000", "费城半导体"]), pick(["标普期货", "纳指期货", "VIX", "10年债", "美元指数", "原油", "黄金", "比特币"])
    return ["【大盘】" + (a or "数据暂缺")] + ([b] if b else [])


def sector_lines(D):
    rows = [(n, D.quote(s)) for n, s in SECTORS]
    rows = sorted(((n, x["pct"]) for n, x in rows if x and x["pct"] is not None), key=lambda r: -r[1])
    if len(rows) < 6:
        return []
    up, dn = rows[:3], rows[-3:][::-1]
    return ["板块轮动:领涨 " + "、".join(f"{n}{pct(p)}" for n, p in up) + ";落后 " + "、".join(f"{n}{pct(p)}" for n, p in dn)]


def catalyst_shared(D, with_earnings=True):
    out = []
    for h in D.macro_news()[:3]:
        out.append(f"· {h}")
    for e in (D.earnings_today()[:5] if with_earnings else []):
        if e.get("act") is not None and e.get("est") is not None:
            tag = "超预期" if e["act"] > e["est"] else "不及预期" if e["act"] < e["est"] else "符合预期"
            out.append(f"· 财报 {e['sym']}({e['when']}):每股收益 {e['act']:g} 对预期 {e['est']:g},{tag}")
        else:
            out.append(f"· 财报 {e['sym']}:{e['when']}发布")
    return out


def flow_lines(D, options=None):
    lines = sector_lines(D)
    mv = D.movers()
    if mv:
        lines.append("涨幅榜(市值≥20亿):" + "、".join(f"{r['sym']}{pct(r['pct'])}" for r in mv["gainers"][:5]))
        lines.append("跌幅榜:" + "、".join(f"{r['sym']}{pct(r['pct'])}" for r in mv["losers"][:5]))
    lines += list(options or [])
    lines.append("(ETF 资金流入流出没有免费数据;个股放量见持仓雷达)")
    return lines


# ---------------------------------------------------------------- 个人部分
def group_of(sym, info):
    if sym in LEV:
        return LEV[sym][2]
    if sym in ETF_GROUP:
        return ETF_GROUP[sym]
    if (info or {}).get("qtype") == "ETF":
        return "其他ETF"
    if re.search("Semiconductor", (info or {}).get("industry") or ""):
        return "半导体"
    return SECTOR_CN.get((info or {}).get("sector") or "", "其他")


def analyze(u, D, now, shared_q, picks=None, cfg=CFG):
    """返回这个人的各栏内容(字典)。shared_q 是 {代码: 行情},里面已经含有他所有股票的行情。"""
    hold, watch = u["hold"], [s for s in u["watch"] if s not in {h["sym"] for h in u["hold"]}]
    held = {h["sym"] for h in hold}
    frac = session_fraction(now)
    news = D.news([s for s in list(held) + watch if s not in ETF_GROUP and s not in LEV][:30])
    earn = {e["sym"]: e for e in D.earnings_today_all()}
    items, tv, tc, day = [], 0.0, 0.0, 0.0
    exposure = {}                                        # 方向 -> 有效敞口(市值 × 杠杆倍数的绝对值)
    gross = eff = 0.0
    risk = []
    for s in list(held) + watch:
        q = shared_q.get(s)
        if not q:
            continue
        p = q["pct"] or 0.0
        h = next((x for x in hold if x["sym"] == s), None)
        hs = D.hist(s) if h else None
        info = D.info(s) if (s not in LEV and s not in ETF_GROUP) else {}
        reasons, score = [], 0.0
        thr = cfg["move_pct"]
        if abs(p) >= thr:
            reasons.append(("大涨" if p > 0 else "大跌") + f" {p:+.1f}%"); score += abs(p) / thr
        if hs and len(hs["vol"]) > 21:
            avg = sum(hs["vol"][-21:-1]) / 20
            vol = (q.get("volume") or 0) / frac
            if avg > 0 and vol / avg >= cfg["vol_ratio"]:
                reasons.append(f"放量约 {vol / avg:.1f} 倍(对比 20 日均量)"); score += 1
        if s in LEV and LEV[s][0]:
            u_, f_, _g = LEV[s]
            uq = shared_q.get(u_) or D.quote(u_)
            if uq and uq["pct"] is not None and abs(uq["pct"]) >= thr / 2:
                reasons.append(f"跟踪 {u_.lstrip('^')}({f_:+g}倍)标的 {uq['pct']:+.1f}%,约带动 {uq['pct'] * f_:+.0f}%"); score += 0.5
        if s in earn:
            e = earn[s]
            reasons.append(f"财报({e['when']})" + (f" 每股收益 {e['act']:g} 对预期 {e['est']:g}" if e.get("act") is not None and e.get("est") is not None else "")); score += 2
        g = [x for x in (info.get("grades") or []) if x["date"] >= (now.date() - datetime.timedelta(days=2)).isoformat() and x.get("action") in ("upgrade", "downgrade", "initialize")]
        if g:
            x = g[0]
            reasons.append(f"评级:{x.get('firm') or '机构'}{ {'upgrade': '上调', 'downgrade': '下调', 'initialize': '首次覆盖'}[x['action']]}" + (f"至 {x['to']}" if x.get("to") else "")); score += 1.5
        if news.get(s):
            reasons.append("新闻:" + news[s][0]); score += 1.2
        if h:
            v, c = h["qty"] * q["price"], h["qty"] * h["cost"]
            prev = q["price"] / (1 + p / 100) if p > -100 else q["price"]
            d = h["qty"] * (q["price"] - prev)
            tv += v; tc += c; day += d
            fac = abs(LEV[s][1]) if s in LEV else 1
            gross += v; eff += v * fac
            grp = group_of(s, info); exposure[grp] = exposure.get(grp, 0) + v * fac
            money = f"({P.usd(d, True)})"
            # 风险提示:客观事实
            if hs and len(hs["close"]) >= 50:
                cl, px = hs["close"], q["price"]
                ma50 = sum(cl[-50:]) / 50
                below50 = px < ma50
                if s in LEV and LEV[s][1] > 0 and below50:
                    risk.append((0, f"{s} 是 {LEV[s][1]} 倍杠杆 ETF,现价在 50 日均线下方 {(1 - px / ma50) * 100:.1f}%:趋势走弱时,杠杆 ETF 的日内反复涨跌损耗会加大"))
                if len(cl) >= 200 and px < sum(cl[-200:]) / 200:
                    risk.append((1, f"{s} 现价低于 200 日均线"))
                hi20 = max(cl[-20:])
                if px / hi20 - 1 <= -0.10:
                    risk.append((2, f"{s} 距 20 日高点回落 {(1 - px / hi20) * 100:.0f}%"))
                if len(cl) > 6 and px / cl[-6] - 1 <= -0.08:
                    risk.append((3, f"{s} 近 5 个交易日下跌 {(1 - px / cl[-6]) * 100:.0f}%"))
                if below50 and not (s in LEV and LEV[s][1] > 0):
                    risk.append((4, f"{s} 现价在 50 日均线下方 {(1 - px / ma50) * 100:.1f}%"))
        else:
            money = ""
        if reasons:
            items.append((score, f"· {s}{'(自选)' if not h else ''} {q['price']:,.2f}({p:+.2f}%){money} — " + ";".join(reasons)))
    items.sort(key=lambda r: -r[0])
    out = {"radar": [t for _, t in items[:cfg["radar_max"]]], "n_items": len(items), "tv": tv, "tc": tc, "day": day, "risk": [t for _, t in sorted(risk)][:cfg["risk_max"]]}
    # 集中度
    conc = []
    if eff > 0:
        top = max(exposure.items(), key=lambda kv: kv[1])
        share = top[1] / eff
        if share >= cfg["concentration"]:
            conc.append(f"{top[0]}方向占你有效敞口的 {share * 100:.0f}%(杠杆 ETF 按倍数计算):同一方向一起回调时,整体回撤会被放大")
        if gross > 0 and eff / gross >= 1.3:
            conc.append(f"杠杆 ETF 把整体敞口放大到市值的 {eff / gross:.1f} 倍")
        if not any(s in LEV and LEV[s][1] < 0 for s in held):
            conc.append("持仓里没有反向 ETF(期权对冲不在统计内)")
    out["conc"] = conc
    # 关注:只来自通过回测的选股规则
    watchl = []
    if picks and picks.get("version") in (2, 3):
        mine = held | set(watch)
        for pr in picks["presets"]:
            top = pr["confirmed"][:5]
            if top:
                watchl.append(f"{pr['name']}:" + "、".join(r["sym"] + ("★" if r["sym"] in mine else "") for r in top))
    out["watch"] = watchl or ["今天没有满足全部条件的(无明确信号)"]
    return out


def build_user(now, u, shared, per, tier, bench=None):
    """拼一个人的消息。返回 (标题, 正文) 或 None(简版没有任何内容时不发)。"""
    tn = {"full": "完整版", "mid": "盘中版", "light": "简版"}[tier]
    lines = [f"我的盘中摘要 {now.strftime('%H:%M')} 美西({tn})"]
    lines += shared["board"]
    cat = shared["catalyst"]
    if cat:
        lines.append("【催化剂】")
        lines += cat[:6 if tier != "light" else 3]
    if tier in ("full", "mid") and shared.get("flow"):
        lines.append("【资金与异动】")
        lines += shared["flow"] if tier == "full" else shared["flow"][:1]
    lines.append("【持仓雷达】" + ("" if per["radar"] else "本时段没有大涨大跌、放量、新闻、财报或评级变化的持仓"))
    lines += per["radar"]
    if per["tv"] > 0:
        d = per["day"]
        base = per["tv"] - d
        tail = ""
        if bench and base > 0:
            tail = f",标普 {pct(bench.get('SPX'))}、纳指 {pct(bench.get('IXIC'))}" if bench.get("SPX") is not None else ""
        lines.append(f"【持仓合计】今日 {P.usd(d, True)}" + (f"({d / base * 100:+.2f}%)" if base > 0 else "") + tail + f",总市值 {P.usd(per['tv'])},累计盈亏 {P.usd(per['tv'] - per['tc'], True)}({(per['tv'] / per['tc'] - 1) * 100:+.1f}%)")
    if tier == "light":
        if not per["radar"] and not cat:
            return None
    else:
        if per["conc"]:
            lines.append("【集中度】")
            lines += [f"· {c}" for c in per["conc"]]
        lines.append("【关注】来自通过回测的选股规则(★ 表示在你的持仓或自选里)")
        lines += [f"· {w}" for w in per["watch"]]
        if per["risk"]:
            lines.append("【风险提示】只列客观事实,不是卖出建议")
            lines += [f"· {r}" for r in per["risk"]]
    lines.append("基于公开信息的观点参考,不是个人投资建议;模型信号不保证收益,可能亏损,请自行判断风险")
    lines.append("数据:行情 Yahoo、新闻 Finnhub(英文新闻机器翻译);取不到的栏目省略")
    return f"我的盘中摘要 {now.strftime('%H:%M')}", "\n".join(lines)


# ---------------------------------------------------------------- 入口
def run(now, cmd, D, users, picks=None, options=None, send_fn=None, dry=False):
    """给每个填了股票的用户发一条个人摘要。返回已收到个人版的聊天编号集合(共用摘要不再发给他们)。
    简版没有内容时不发,但这个人仍然算已服务(不再收共用摘要)。"""
    tier = tier_for(cmd, now)
    people = [p for p in (P.clean(x) for x in users) if p]
    syms = sorted({s for p in people for s in p["watch"] + [h["sym"] for h in p["hold"]]})
    extra = {LEV[s][0] for s in syms if s in LEV and LEV[s][0]}
    shared_q = D.quotes(sorted(set(syms) | extra))
    shared = {"board": board_lines(D, compact=(tier == "light")), "catalyst": catalyst_shared(D, with_earnings=(tier != "light"))}
    if tier in ("full", "mid"):
        shared["flow"] = flow_lines(D, options)
    bench = {k: (D.quote(k) or {}).get("pct") for k in ("SPX", "IXIC")}
    served, nsent = set(), 0
    for p in people:
        try:
            if not (p["watch"] or p["hold"]):
                continue
            served.add(p["chat"])
            per = analyze(p, D, now, shared_q, picks)
            r = build_user(now, p, shared, per, tier, bench)
            if not r:
                continue
            if dry:
                print("====", r[0], "→ chat", p["chat"][:3] + "***", "====\n" + r[1] + "\n")
            else:
                (send_fn or P._send)(r[0], r[1], p["chat"])
            nsent += 1
        except Exception as e:
            served.discard(p["chat"])
            print("个人摘要失败(这个人改收共用摘要):", type(e).__name__, str(e)[:100])
    print(f"个人摘要({tier}):{len(people)} 人开启,实际发送 {nsent} 条")
    return served


# ---------------------------------------------------------------- 真实数据源(测试里换成假的)
class RealData:
    def __init__(self, core, fresh_news, zh, earnings_fn, macro_fn):
        self.c, self._fresh, self._zh, self._earn, self._macro = core, fresh_news, zh, earnings_fn, macro_fn
        self._q, self._h, self._i, self._e = {}, {}, {}, None

    def quote(self, s):
        if s not in self._q:
            try:
                x = self.c.quote(s)
                self._q[s] = {"price": x["price"], "pct": x["pct"], "volume": x.get("volume") or 0}
            except Exception:
                self._q[s] = None
        return self._q[s]

    def quotes(self, syms):
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(self.quote, syms))
        return {s: self._q[s] for s in syms if self._q.get(s)}

    def hist(self, s):
        if s not in self._h:
            try:
                r = self.c._chart(s, "6mo", "1d", 600)
                q = r["indicators"]["quote"][0]
                rows = [(c, v or 0) for c, v in zip(q["close"], q["volume"]) if c is not None]
                self._h[s] = {"close": [c for c, _ in rows], "vol": [v for _, v in rows]}
            except Exception:
                self._h[s] = None
        return self._h[s]

    def info(self, s):
        if s not in self._i:
            try:
                import urllib.parse
                d = self.c._yh_open(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(s)}?modules=assetProfile,upgradeDowngradeHistory,quoteType")
                r = d["quoteSummary"]["result"][0]
                ap = r.get("assetProfile") or {}
                act = {"up": "upgrade", "down": "downgrade", "main": "maintain", "init": "initialize", "reit": "reiterate"}
                import time
                g = [{"date": time.strftime("%Y-%m-%d", time.gmtime(x["epochGradeDate"])), "firm": x.get("firm"), "to": x.get("toGrade"), "action": act.get(x.get("action"), x.get("action"))}
                     for x in (r.get("upgradeDowngradeHistory") or {}).get("history", [])[:6]]
                self._i[s] = {"sector": ap.get("sector"), "industry": ap.get("industry"), "qtype": (r.get("quoteType") or {}).get("quoteType"), "grades": g}
            except Exception:
                self._i[s] = {}
        return self._i[s]

    def news(self, syms):
        out = {}
        try:
            for sc, tag, a in self._fresh(60, syms):
                if tag in syms:
                    out.setdefault(tag, []).append(self._zh(a["headline"])[:40])
        except Exception:
            pass
        return out

    def macro_news(self):
        try:
            return [self._zh(a["headline"])[:60] for sc, tag, a in self._fresh(60, []) if tag == "宏观"][:3]
        except Exception:
            return []

    def earnings_today_all(self):
        if self._e is None:
            try:
                self._e = self._earn()
            except Exception:
                self._e = []
        return self._e

    def earnings_today(self):
        return self.earnings_today_all()

    def movers(self):
        try:
            m = self.c.movers()
            return {"gainers": m["gainers"]["items"], "losers": m["losers"]["items"]} if m["gainers"]["items"] else None
        except Exception:
            return None
