"""周日下周前瞻 + 周末新闻回顾的离线测试(不联网、不发消息)。以后改 push/market_push.py 前后都要跑:python3 tools/test_weekly_preview.py"""
import datetime, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "push"), os.path.join(ROOT, "api")]
import market_push as M

PT = M.PT
NOW = datetime.datetime(2026, 11, 8, 17, 0, tzinfo=PT)          # 周日 17:00 美西


def ts(d, h, m):
    return datetime.datetime(2026, 11, d, h, m, tzinfo=PT).timestamp()


GEN = [
    {"id": 1, "headline": "Explosion at refinery in Texas halts output, oil prices jump", "summary": "", "datetime": ts(7, 9, 10), "source": "Reuters"},
    {"id": 2, "headline": "Fed's Powell says rate cut possible in December", "summary": "", "datetime": ts(8, 11, 0), "source": "CNBC"},
    {"id": 3, "headline": "Fed's Powell says rate cut possible in December - report", "summary": "", "datetime": ts(8, 11, 5), "source": "MarketWatch"},
    {"id": 4, "headline": "Celebrity chef opens new restaurant", "summary": "", "datetime": ts(7, 12, 0), "source": "X"},
    {"id": 5, "headline": "Old news before Friday close: China tariff talks", "summary": "", "datetime": ts(6, 9, 0), "source": "X"},
    {"id": 6, "headline": "Cyberattack hits major airline, flights grounded", "summary": "", "datetime": ts(8, 8, 0), "source": "AP"},
]
CO = [{"id": 9, "headline": "Nvidia (NVDA) faces antitrust probe over export deal", "related": "NVDA", "datetime": ts(7, 15, 0), "source": "WSJ"}]


class Fake:
    mode = "ok"

    @staticmethod
    def _fh(path, params, ttl):
        if Fake.mode == "nokey":
            return None
        return GEN if path == "news" else (CO if params.get("symbol") == "NVDA" else [])

    @staticmethod
    def _zh(t):
        return t


M.core = lambda: Fake
M.picks_section = lambda P, title="": ["【" + title + "】"]

# 1) 正常:重大事件入选;周五收盘前的旧新闻、无关新闻被排除;相似标题合并
wk = M.weekend_news(NOW, ["AAPL", "NVDA", "VOO", "QQQ"])
heads = [h for _, _, h, _ in wk["items"]]
assert wk["ok"] and len(wk["items"]) == 4, heads
assert any("Explosion" in h for h in heads) and any("Cyberattack" in h for h in heads) and any("Nvidia" in h for h in heads)
assert not any("chef" in h or "Old news" in h for h in heads), heads
assert sum("Powell" in h for h in heads) == 1, "相似标题应去重"

mon = datetime.date(2026, 11, 9)
ctx = {"indices": ([("标普期货", {"pct": 0.3, "price": 1})], []), "watch": ["AAPL"], "macro_events": [(datetime.date(2026, 11, 12), "CPI 通胀数据")],
       "levels": [("VIX", {"price": 25.6})], "picks": None, "macro_snapshot": ["10年债 4.86%"], "weekend": wk,
       "earnings": {mon + datetime.timedelta(days=i): ([{"sym": "WMT", "when": "盘前"}] if i == 2 else []) for i in range(5)}}
t, m = M.build_weekly_preview(datetime.date(2026, 11, 8), ctx)
for must in ("【周末发生了什么", "周六 09:10", "【财报", "WMT盘前", "【当前宏观】", "【本周宏观数据发布】", "【需要注意】"):
    assert must in m, must
assert len(m) < 3500, len(m)                                      # Telegram 单条上限 4096

# 2) 没有新闻 / 取不到数据 都有明确提示,不报错
ctx["weekend"] = {"items": [], "ok": True}
assert "没有抓到符合条件" in M.build_weekly_preview(datetime.date(2026, 11, 8), ctx)[1]
ctx["weekend"] = {"items": [], "ok": False}
assert "暂时取不到周末新闻" in M.build_weekly_preview(datetime.date(2026, 11, 8), ctx)[1]
Fake.mode = "nokey"
assert M.weekend_news(NOW, ["NVDA"]) == {"items": [], "ok": False}

# 3) 提前收盘提醒只在当周出现
ctx["weekend"] = wk
assert "提前收盘" in M.build_weekly_preview(datetime.date(2026, 11, 22), ctx)[1]
assert "提前收盘" not in M.build_weekly_preview(datetime.date(2026, 11, 8), ctx)[1]

# 4) 发送时间判断:周日 17:00 美西运行,周六、周日 15:00 不运行
assert M.gate("weekly_preview", datetime.datetime(2026, 11, 8, 17, 0, tzinfo=PT))
assert not M.gate("weekly_preview", datetime.datetime(2026, 11, 7, 17, 0, tzinfo=PT))
assert not M.gate("weekly_preview", datetime.datetime(2026, 11, 8, 15, 0, tzinfo=PT))
# 5) 本周总结:周日手动触发时,「本周」是刚结束的周一到周五
assert M.last_friday(datetime.date(2026, 11, 8)) == datetime.date(2026, 11, 6)       # 周日 → 周五
assert M.last_friday(datetime.date(2026, 11, 6)) == datetime.date(2026, 11, 6)       # 周五 → 当天
assert M.last_friday(datetime.date(2026, 11, 9)) == datetime.date(2026, 11, 6)       # 周一 → 上周五
assert M.week_dates(M.last_friday(datetime.date(2026, 11, 8)))[0] == datetime.date(2026, 11, 2)
sctx = {"indices": [("标普", 1.2), ("纳指", -0.4)], "watch": [("AAPL", 2.0), ("NVDA", -3.0)], "levels": ["VIX 26.40", "10年债 4.86%"], "earnings": [], "macro_snapshot": ["10年债 4.86%"],
        "news": [], "picks_changes": {}, "picks": None,
        "sectors": [(n, v) for n, v in [("科技", -1.0), ("金融", 2.0), ("能源", 3.0), ("医疗", 0.5), ("可选消费", -0.5), ("必需消费", 0.2), ("工业", 1.0), ("材料", 0.1)]]}
st, sm = M.build_weekly_summary(datetime.date(2026, 11, 6), sctx)
for must in ("本周总结 11/02–11/06", "【指数本周】标普 +1.20%", "【板块本周】领涨 能源+3.00%", "落后 科技-1.00%", "【波动与利率】VIX 26.40", "【自选本周】", "【宏观最新值】"):
    assert must in sm, (must, sm)
print("下周前瞻 + 周末回顾 + 本周总结:全部通过")
