"""盘中每小时摘要(个人版)的离线测试:不联网、不发消息。python3 tools/test_digest.py"""
import datetime, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "push"), os.path.join(ROOT, "api")]
import digest as G

PT = datetime.timezone(datetime.timedelta(hours=-8))
T_FULL = datetime.datetime(2026, 11, 9, 7, 30, tzinfo=PT)
T_LIGHT = datetime.datetime(2026, 11, 9, 9, 30, tzinfo=PT)
T_MID = datetime.datetime(2026, 11, 9, 10, 30, tzinfo=PT)

Q = {"DJI": (51000, -0.5), "SPX": (7300, 0.3), "IXIC": (24500, -1.1), "^RUT": (2500, 0.2), "^SOX": (5200, -3.0), "ES=F": (7310, 0.2), "NQ=F": (24600, -0.9),
     "VIX": (26.4, 8.0), "US10Y": (4.86, 0.4), "DXY": (102.3, 0.0), "WTI": (90.8, 0.3), "GOLD": (4075, -0.9), "BTC": (75000, -0.1),
     "XLK": (200, -1.5), "XLF": (50, 0.8), "XLE": (90, 1.2), "XLV": (140, 0.1), "XLY": (190, -0.2), "XLP": (80, 0.5), "XLI": (130, 0.4), "XLB": (85, 0.3),
     "XLU": (75, 0.9), "XLRE": (40, -0.1), "XLC": (95, -0.7), "SMH": (250, -3.2),
     "NVDA": (200, -4.0), "MU": (120, 5.0), "AAPL": (190, 0.2), "SOXL": (30, -9.2), "QQQ": (500, -1.1), "VOO": (600, 0.3), "TSLA": (300, 1.0)}
HIST = {}
for s in ("NVDA", "MU", "AAPL", "SOXL", "QQQ", "VOO"):
    HIST[s] = {"close": [100 + i * 0.5 for i in range(220)], "vol": [1000] * 220}      # 一路上涨的假历史
HIST["SOXL"]["close"] = [40 - i * 0.05 for i in range(220)]                              # 杠杆 ETF:一路下跌,现价在 50 日线下方
HIST["MU"]["vol"] = [1000] * 219 + [2000]


class Fake:
    def quote(self, s):
        return {"price": Q[s][0], "pct": Q[s][1], "volume": 900_000 if s == "MU" else 100} if s in Q else None

    def quotes(self, syms):
        return {s: self.quote(s) for s in syms if s in Q}

    def hist(self, s):
        return HIST.get(s)

    def info(self, s):
        d = {"NVDA": {"sector": "Technology", "industry": "Semiconductors", "grades": [{"date": "2026-11-08", "firm": "Morgan Stanley", "to": "Overweight", "action": "upgrade"}]},
             "MU": {"sector": "Technology", "industry": "Semiconductors", "grades": []}, "AAPL": {"sector": "Technology", "industry": "Consumer Electronics", "grades": []}}
        return d.get(s, {})

    def news(self, syms):
        return {"NVDA": ["英伟达被调查(示例)"]} if "NVDA" in syms else {}

    def macro_news(self):
        return ["美联储官员称 12 月可能降息(示例)"]

    def earnings_today_all(self):
        return [{"sym": "NVDA", "when": "盘后", "act": 1.3, "est": 1.2}]

    earnings_today = earnings_today_all

    def movers(self):
        return {"gainers": [{"sym": "AAA", "pct": 20.0}] * 5, "losers": [{"sym": "BBB", "pct": -15.0}] * 5}


PICKS = {"version": 3, "presets": [{"id": "trend", "name": "强趋势龙头(中期)", "confirmed": [{"sym": "MU"}, {"sym": "ZZZ"}]}]}
U1 = {"chat": "111111", "watch": ["QQQ"], "hold": [{"sym": "NVDA", "qty": 100, "cost": 150}, {"sym": "MU", "qty": 50, "cost": 100}, {"sym": "SOXL", "qty": 300, "cost": 40}, {"sym": "AAPL", "qty": 10, "cost": 150}]}
U_EMPTY = {"chat": "222222", "watch": [], "hold": []}
U_QUIET = {"chat": "333333", "watch": [], "hold": [{"sym": "VOO", "qty": 10, "cost": 500}]}
users = [{"tg_chat_id": u["chat"], "watch": u["watch"], "holdings": u["hold"]} for u in (U1, U_EMPTY, U_QUIET)]


def go(now, cmd):
    sent = []
    served = G.run(now, cmd, Fake(), users, PICKS, options=["期权异常:NVDA 示例"], send_fn=lambda t, m, c: sent.append((t, m, c)))
    return served, sent


# 完整版:所有栏目都在
served, sent = go(T_FULL, "hourly")
assert served == {"111111", "333333"}, served                        # 没填股票的人不算已服务,继续收共用摘要
assert [c for _, _, c in sent] == ["111111", "333333"], sent        # 完整版每人都发
m = dict((c, m) for _, m, c in sent)["111111"]
for must in ("(完整版)", "【大盘】道指 -0.50%", "费城半导体 -3.00%", "VIX 26.4", "10年债 4.86%", "【催化剂】", "美联储官员称", "财报 NVDA(盘后):每股收益 1.3 对预期 1.2,超预期",
             "【资金与异动】", "板块轮动:领涨 能源", "涨幅榜", "期权异常", "ETF 资金流入流出没有免费数据",
             "【持仓雷达】", "MU 120.00(+5.00%)", "放量约", "NVDA 200.00(-4.00%)", "评级:Morgan Stanley上调至 Overweight", "新闻:英伟达被调查",
             "SOXL 30.00(-9.20%)", "跟踪 SOX(+3倍)标的 -3.0%,约带动 -9%", "【持仓合计】今日", "标普 +0.30%、纳指 -1.10%",
             "【集中度】", "半导体方向占你有效敞口的", "杠杆 ETF 把整体敞口放大到市值的", "持仓里没有反向 ETF",
             "【关注】", "MU★、ZZZ", "【风险提示】只列客观事实,不是卖出建议", "3 倍杠杆 ETF,现价在 50 日均线下方", "基于公开信息的观点参考,不是个人投资建议"):
    assert must in m, (must, m)
assert "AAPL" not in m.split("【持仓雷达】")[1].split("【持仓合计】")[0], "没有异动的持仓不上雷达"
assert len(m) < 3800, len(m)
# 安静的人(只有 VOO,没异动):完整版仍然发,雷达写明没有异动
mq = dict((c, m) for _, m, c in sent)["333333"]
assert "本时段没有大涨大跌、放量、新闻、财报或评级变化的持仓" in mq

# 简版:大盘一行,没有板块和风险提示;安静的人有催化剂也发,但没催化剂就不发
served, sent = go(T_LIGHT, "hourly")
ml = dict((c, m) for _, m, c in sent)["111111"]
assert "(简版)" in ml and "【资金与异动】" not in ml and "【风险提示】" not in ml and "【关注】" not in ml and "【持仓雷达】" in ml
assert ml.count("【大盘】") == 1 and "道指" not in ml and "标普 +0.30%" in ml
assert "财报 NVDA(盘后)" not in ml.split("【持仓雷达】")[0], "简版催化剂不重复列财报"


class NoNews(Fake):
    def macro_news(self):
        return []


sent2 = []
G.run(T_LIGHT, "hourly", NoNews(), users, PICKS, send_fn=lambda t, m, c: sent2.append(c))
assert sent2 == ["111111"], "简版:没有异动也没有催化剂的人不发,但仍不再收共用摘要"

# 10:30 盘中版:有关注、板块,没有完整的涨跌榜
served, sent = go(T_MID, "mid")
mm = dict((c, m) for _, m, c in sent)["111111"]
assert "(盘中版)" in mm and "板块轮动" in mm and "涨幅榜" not in mm and "【关注】" in mm

# 取不到数据时不崩:什么都没有的假数据源
class Empty(Fake):
    def quote(self, s): return None
    def quotes(self, syms): return {}
    def hist(self, s): return None
    def info(self, s): return {}
    def news(self, syms): return {}
    def macro_news(self): return []
    def earnings_today_all(self): return []
    earnings_today = earnings_today_all
    def movers(self): return None


sent3 = []
G.run(T_FULL, "hourly", Empty(), users, None, send_fn=lambda t, m, c: sent3.append((t, m)))
assert len(sent3) == 2 and "数据暂缺" in sent3[0][1] and "无明确信号" in sent3[0][1]
# 一个人出错 → 这个人改收共用摘要,其他人不受影响
def boom(t, m, c):
    if c == "111111":
        raise RuntimeError("x")
sent4 = G.run(T_FULL, "hourly", Fake(), users, PICKS, send_fn=boom)
assert sent4 == {"333333"} or sent4 == {"111111", "333333"} - {"111111"}, sent4
# 发送函数里会把过长消息拆开
import personal as P
parts = P.split_message("行\n" * 3000, 3800)
assert len(parts) >= 2 and all(len(x) <= 3800 for x in parts) and "".join(parts) == "行\n" * 3000
print("每小时摘要(个人版):全部通过\n\n---- 完整版示例(第一位用户)----\n" + dict((c, m) for _, m, c in go(T_FULL, "hourly")[1])["111111"])
