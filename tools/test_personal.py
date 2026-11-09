"""按人推送(盘中每小时摘要里「我的持仓与自选」)的离线测试:不联网、不发消息。python3 tools/test_personal.py"""
import datetime, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "push"), os.path.join(ROOT, "api")]
import personal as P

T = datetime.datetime(2026, 11, 9, 8, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=-8)))
Q = {"NVDA": {"price": 210.0, "pct": 2.0}, "AAPL": {"price": 190.0, "pct": -1.0}, "MU": {"price": 120.0, "pct": 5.0}, "VOO": {"price": 600.0, "pct": 0.5}}
users = [
    {"tg_chat_id": "123456789", "watch": ["AAPL", "VOO"], "holdings": [{"sym": "NVDA", "qty": 100, "cost": 150}, {"sym": "MU", "qty": 50, "cost": 100}, {"sym": "ZZZZ", "qty": 10, "cost": 5}]},
    {"tg_chat_id": "-987654321", "watch": ["AAPL"], "holdings": []},
    {"tg_chat_id": "abc", "watch": ["AAPL"], "holdings": []},                       # 不合法的 Id:跳过
    {"tg_chat_id": "555555555", "watch": [], "holdings": []},                       # 什么都没填:不发
    {"tg_chat_id": "777777777", "watch": ["AAPL"], "holdings": [{"sym": "NVDA", "qty": -5, "cost": 100}]},   # 非法持仓被过滤,仍发自选
]
asked = []
sent = []


def quote(s):
    asked.append(s)
    return Q.get(s)


news = lambda syms: {"NVDA": ["英伟达获新订单(示例)"]}
served = P.run(T, quote, news, send_fn=lambda t, m, c: sent.append((t, m, c)), users=users, head=["【指数】标普 +0.3%"], extra=["【选股更新】示例"])
assert served == {"123456789", "-987654321", "777777777"} and [c for _, _, c in sent] == ["123456789", "-987654321", "777777777"], sent
assert all("【指数】标普 +0.3%" in m and "【选股更新】示例" in m for _, m, _ in sent), "共用的指数和选股行每人都要有"
assert len(asked) == len(set(asked)), "每只股票只应查一次"
m = sent[0][1]
# NVDA:+2% → 前收 205.88,100 股 → 今日 +$411.8;MU +5% → 50 股 → +$285.7;合计 +$697;累计:NVDA +40%,MU +20%
for must in ("【持仓合计】今日 +$697(+2.65%)", "NVDA 210.00(+2.00%)", "MU 120.00(+5.00%)", "累计 +40.0%", "没取到报价:ZZZZ", "【自选】AAPL 190.00(-1.00%)  VOO 600.00(+0.50%)", "英伟达获新订单", "不是买卖建议"):
    assert must in m, (must, m)
assert "云端已同步:自选 2 只、持仓 3 只" in m
assert "云端还没有你的自选股" in P.build(T, {"chat": "1", "watch": [], "hold": [{"sym": "NVDA", "qty": 1, "cost": 1}]}, Q)[1]
assert "自选股都已在上面的持仓里" in P.build(T, {"chat": "1", "watch": ["NVDA"], "hold": [{"sym": "NVDA", "qty": 1, "cost": 1}]}, Q)[1]
assert P.build(T, {"chat": "1", "watch": ["AAPL"], "hold": []}, {"AAPL": {"price": 1.0, "pct": None}}) is not None     # 涨跌幅取不到不报错
assert "【持仓】" not in sent[1][1] and "【持仓合计】" not in sent[1][1] and "【自选】AAPL" in sent[1][1]
assert "NVDA" not in sent[2][1].split("【自选】")[0] and "【自选】AAPL" in sent[2][1]
# 只看异动(阈值 3%):MU +5% 入选;NVDA +2%、AAPL -1%、VOO +0.5% 不列;没有异动的人不发,但也不再收共用摘要
sent2 = []
served2 = P.run(T, quote, news, send_fn=lambda t, m, c: sent2.append((t, m, c)), users=users, min_pct=3.0)
assert served2 == {"123456789", "-987654321", "777777777"}, served2
assert [c for _, _, c in sent2] == ["123456789"], sent2
t2, m2, _c2 = sent2[0]
assert t2.startswith("我的持仓异动") and "超过 ±3%" in m2 and "MU 120.00(+5.00%)" in m2 and "NVDA 210.00" not in m2 and "AAPL" not in m2 and "VOO" not in m2, m2
assert "【持仓合计】今日 +$697" in m2 and "没取到报价:ZZZZ" in m2
assert "英伟达获新订单" not in m2, "要闻只列异动股票的"
big_w = P.build(T, {"chat": "1", "watch": ["AAPL", "MU"], "hold": []}, Q, min_pct=3.0)
assert "【自选异动】MU 120.00(+5.00%)" in big_w[1] and "AAPL" not in big_w[1]
none = P.build(T, {"chat": "1", "watch": ["AAPL"], "hold": []}, Q, min_pct=3.0)
assert none is None, "没有异动就不发"
quiet = P.build(T, {"chat": "1", "watch": ["AAPL"], "hold": []}, Q, extra=["【选股更新】示例"], min_pct=3.0)
assert quiet and "都没有超过 ±3%" in quiet[1] and "【选股更新】示例" in quiet[1], "10:30 带选股更新时,没异动也要发选股"
down = P.build(T, {"chat": "1", "watch": [], "hold": [{"sym": "AAPL", "qty": 10, "cost": 200}]}, {"AAPL": {"price": 180.0, "pct": -4.0}}, min_pct=3.0)
assert "AAPL 180.00(-4.00%)" in down[1], "大跌也要列出"
# 一个人发送失败,不影响其他人
calls = []
def flaky(t, m, c):
    calls.append(c)
    if c == "123456789":
        raise RuntimeError("boom")
assert P.run(T, quote, news, send_fn=flaky, users=users) == {"-987654321", "777777777"} and len(calls) == 3
# 没配置时什么都不做
os.environ.pop("SUPABASE_URL", None); os.environ.pop("SUPABASE_SERVICE_KEY", None)
assert P.run(T, quote, None) == set()
# 共用摘要只发给还没收到个人版的人
assert P.remaining_chats("111, 123456789 ,222", {"123456789"}) == "111,222"
assert P.remaining_chats("123456789", {"123456789"}) == ""
assert P.remaining_chats("111,222", set()) == "111,222" and P.remaining_chats(None, {"1"}) == ""
print("按人推送:全部通过\n\n--- 示例(第一位用户收到的消息)---\n" + sent[0][0] + "\n" + m)
