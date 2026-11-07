"""推送系统的自动化测试(不联网):时间闸门(冬令时/夏令时)、休市日、新闻保护规则、名单稳定性、消息内容。
运行:python3 tools/test_push.py"""
import datetime, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "push"), os.path.join(ROOT, "api")]
import market_push as M
import notify as N
import screener_v2 as S

U = lambda y, mo, d, h, mi: datetime.datetime(y, mo, d, h, mi, tzinfo=datetime.timezone.utc)


class Gate(unittest.TestCase):
    def test_brief_both_seasons(self):
        self.assertTrue(M.gate("brief", U(2026, 11, 9, 14, 0)))      # 冬令时:UTC 14:00 = 美西 06:00
        self.assertFalse(M.gate("brief", U(2026, 11, 9, 13, 0)))     # 冬令时:UTC 13:00 = 05:00,应跳过
        self.assertTrue(M.gate("brief", U(2026, 6, 8, 13, 0)))       # 夏令时:UTC 13:00 = 06:00
        self.assertFalse(M.gate("brief", U(2026, 6, 8, 14, 0)))      # 夏令时:UTC 14:00 = 07:00,应跳过
        self.assertTrue(M.gate("brief", U(2026, 11, 9, 14, 40)))     # 晚 40 分钟仍在容忍窗口内

    def test_exactly_one_cron_fires_per_slot(self):
        for day in (U(2026, 11, 9, 0, 0), U(2026, 6, 8, 0, 0)):      # 一个冬令时周一,一个夏令时周一
            for slot, crons in {"brief": [(13, 0), (14, 0)], "mid": [(17, 30), (18, 30)]}.items():
                n = sum(M.gate(slot, day.replace(hour=h, minute=mi)) for h, mi in crons)
                self.assertEqual(n, 1, f"{slot} {day.date()}")

    def test_hourly_covers_each_hour_once(self):
        for day in (U(2026, 11, 9, 0, 0), U(2026, 6, 8, 0, 0)):
            hits = [M.now_pt(day.replace(hour=h, minute=30)).hour for h in range(14, 21) if M.gate("hourly", day.replace(hour=h, minute=30))]
            self.assertEqual(hits, [7, 8, 9, 11, 12])                 # 10 点那次交给盘中选股任务

    def test_mid_post_and_weekly(self):
        self.assertTrue(M.gate("mid", U(2026, 11, 9, 18, 30)))
        self.assertTrue(M.gate("mid", U(2026, 6, 8, 17, 30)))
        self.assertTrue(M.gate("post", U(2026, 11, 9, 22, 30)))
        self.assertTrue(M.gate("post", U(2026, 6, 8, 22, 30)))
        self.assertFalse(M.gate("post", U(2026, 6, 8, 19, 0)))        # 还没收盘
        self.assertTrue(M.gate("weekly_summary", U(2026, 11, 6, 23, 0)))
        self.assertFalse(M.gate("weekly_summary", U(2026, 11, 6, 22, 0)))
        self.assertTrue(M.gate("weekly_summary", U(2026, 6, 12, 22, 0)))
        self.assertFalse(M.gate("weekly_summary", U(2026, 6, 12, 23, 0)))
        self.assertTrue(M.gate("weekly_preview", U(2026, 11, 9, 1, 0)))     # 周日 17:00 美西 = 周一 01:00 UTC
        self.assertFalse(M.gate("weekly_preview", U(2026, 11, 9, 0, 0)))
        self.assertTrue(M.gate("weekly_preview", U(2026, 6, 8, 0, 0)))
        self.assertFalse(M.gate("weekly_preview", U(2026, 6, 8, 1, 0)))

    def test_weekend_and_holidays_skip(self):
        self.assertFalse(M.gate("brief", U(2026, 11, 7, 14, 0)))      # 周六
        self.assertFalse(M.gate("hourly", U(2026, 11, 8, 16, 30)))    # 周日
        self.assertFalse(M.gate("brief", U(2026, 11, 26, 14, 0)))     # 感恩节
        self.assertFalse(M.gate("weekly_summary", U(2026, 4, 3, 22, 0)))   # 耶稣受难日(周五休市)
        self.assertFalse(M.gate("post", U(2026, 12, 25, 22, 30)))     # 圣诞节


def art(i, ts, title="x"):
    return {"id": i, "headline": title, "datetime": ts}


class NewsRules(unittest.TestCase):
    now = U(2026, 11, 9, 18, 0)                      # 周一美西 10:00
    ts = now.timestamp()

    def test_quiet_hours(self):
        cand = [(5, "宏观", art(1, self.ts - 60))]
        out, _ = N.select(cand, self.ts, {}, now=M.now_pt(U(2026, 11, 9, 10, 0)))     # 美西 02:00,静音
        self.assertEqual(out, [])
        out, _ = N.select(cand, self.ts, {}, now=M.now_pt(U(2026, 11, 9, 14, 20)))    # 美西 06:20,静音已结束
        self.assertEqual(len(out), 1)

    def test_weekend_only_major_macro(self):
        sat = M.now_pt(U(2026, 11, 7, 20, 0))
        cand = [(2, "宏观", art(1, self.ts)), (5, "宏观", art(2, self.ts)), (6, "NVDA", art(3, self.ts))]
        out, _ = N.select(cand, self.ts, {}, now=sat)
        self.assertEqual([a["id"] for _, _, a in out], [2])           # 周末只推分数够高的宏观

    def test_daily_caps_leave_room_for_watchlist(self):
        macro = [(3, "宏观", art(i, self.ts)) for i in range(20)]
        st = {}
        pushed = []
        for _ in range(4):
            out, st = N.select(macro, self.ts, st, now=M.now_pt(self.now))
            pushed += out
            macro = [c for c in macro if c[2]["id"] not in {a["id"] for _, _, a in pushed}]
        self.assertEqual(len(pushed), 7)                              # 非自选宏观新闻最多 7 条
        out, st = N.select([(4, "AAPL", art(99, self.ts))], self.ts, st, now=M.now_pt(self.now))
        self.assertEqual(len(out), 1)                                 # 自选股还有名额
        self.assertEqual(st["total"], 8)

    def test_total_cap_ten(self):
        st = {"date": "2026-11-09", "total": 10, "macro": 3}
        out, _ = N.select([(6, "NVDA", art(1, self.ts))], self.ts, st, now=M.now_pt(self.now))
        self.assertEqual(out, [])

    def test_stale_news_ignored(self):
        out, _ = N.select([(5, "宏观", art(1, self.ts - 3 * 3600))], self.ts, {}, now=M.now_pt(self.now))
        self.assertEqual(out, [])


class Stability(unittest.TestCase):
    def test_incumbent_kept_unless_clearly_beaten(self):
        rows = [{"sym": "NEW1", "status": "NEW", "score": 72}, {"sym": "OLD", "status": "STILL_VALID", "score": 69}, {"sym": "NEW2", "status": "NEW", "score": 60}]
        self.assertEqual([r["sym"] for r in S.top_rows(rows, 1, margin=5)], ["OLD"])      # 72 < 69+5,保留旧的
        rows[0]["score"] = 80
        self.assertEqual([r["sym"] for r in S.top_rows(rows, 1, margin=5)], ["NEW1"])     # 明显更好才替换
        self.assertEqual(S.top_rows(rows, 1, margin=5)[0]["score"], 80)                   # 显示的分数不被加分改动


class Messages(unittest.TestCase):
    def setUp(self):
        M.zh = lambda t: t
        self.P = {"version": 2, "dataDate": "2026-11-06", "regime": "NEUTRAL", "presets": [
            {"id": "growth", "name": "激进成长", "confirmedTotal": 7, "confirmed": [{"sym": s, "status": "STILL_VALID"} for s in "ABCDE"]},
            {"id": "pullback", "name": "强势回调", "confirmedTotal": 0, "confirmed": []}]}

    def test_picks_section_marks_changes(self):
        prev = {"presets": [{"id": "growth", "confirmed": [{"sym": s} for s in "ABCDF"]}, {"id": "pullback", "confirmed": []}]}
        txt = "\n".join(M.picks_section(self.P, prev))
        self.assertIn("新进 E", txt)
        self.assertIn("退出 F", txt)
        self.assertIn("今天没有满足全部条件的 ← 与上次相同", txt)
        same = "\n".join(M.picks_section(self.P, self.P))
        self.assertEqual(same.count("与上次相同"), 2)                 # 没变化也照样推送,只是标注

    def test_brief_has_all_sections(self):
        ctx = {"indices": ([("标普期货", {"pct": .3})], ["VIX 25.6(-9.0%)"]), "earnings": [{"sym": "KKR", "when": "盘前"}, {"sym": "OXY", "when": "盘后"}],
               "macro_events": ["CPI 通胀数据"], "news": [(4, "宏观", art(1, 0, "Fed holds rates")), (5, "NVDA", art(2, 0, "Nvidia price target raised"))], "picks": self.P}
        t, m = M.build_brief(datetime.date(2026, 11, 9), ctx)
        for k in ("盘前指数", "标普期货 +0.30%", "今日财报", "KKR", "OXY", "CPI 通胀数据", "Fed holds rates", "自选股要闻", "NVDA", "今日选股"):
            self.assertIn(k, m)

    def test_hourly_and_mid(self):
        ctx = {"indices": [("标普", {"pct": .1})], "watch": ["AAPL 1.00(+1.00%)"], "options": [], "news": [], "picks": self.P, "prev_picks": self.P}
        _, h = M.build_hourly(datetime.datetime(2026, 11, 9, 8, 30), ctx)
        self.assertIn("期权异常】无", h)
        self.assertNotIn("选股更新", h)
        _, mid = M.build_hourly(datetime.datetime(2026, 11, 9, 10, 30), ctx, with_picks=True)
        self.assertIn("选股更新", mid)
        self.assertIn("未收盘", mid)

    def test_option_line_new_positions(self):
        r = {"sym": "NVDA", "exp": "11/09", "kind": "看跌", "strike": 222.5, "vol": 2800, "oi": 0, "notional": 9.6e6}
        self.assertIn("几乎全是新开仓", M.option_line(r))
        r["oi"] = 2300
        self.assertIn("未平仓 2.3k", M.option_line(r))

    def test_weekly_messages(self):
        ctx = {"indices": [("标普", -2.7)], "watch": [("AAPL", -0.7), ("NVDA", -8.8)], "earnings": [{"sym": "KKR", "sur": 8.0}], "macro_snapshot": ["10年债 4.84%"],
               "news": [], "picks_changes": {"growth": {"new": list("ABCDEFG"), "inv": []}}, "picks": self.P}
        _, s = M.build_weekly_summary(datetime.date(2026, 11, 6), ctx)
        self.assertIn("最强 AAPL,最弱 NVDA", s)
        self.assertIn("超预期 +8%", s)
        self.assertIn("等7只", s)                                     # 太长时截断
        pc = {"indices": ([("标普期货", {"pct": .1})], []), "watch": ["NVDA"], "levels": [("VIX", {"price": 26.0})], "picks": self.P,
              "earnings": {datetime.date(2026, 11, 11): [{"sym": "NVDA", "when": "盘后"}] + [{"sym": f"X{i}", "when": "盘前"} for i in range(8)]},
              "macro_events": [(datetime.date(2026, 11, 10), "CPI 通胀数据")]}
        _, p = M.build_weekly_preview(datetime.date(2026, 11, 8), pc)
        for k in ("下周前瞻", "你的自选股财报】NVDA 周三盘后", "CPI 通胀数据", "财报最密集:周三(9家大公司)", "VIX 26.0 偏高"):
            self.assertIn(k, p)
        _, hol = M.build_weekly_preview(datetime.date(2026, 11, 22), dict(pc, earnings={}, macro_events=[]))      # 感恩节所在周
        self.assertIn("休市:11/26", hol)


if __name__ == "__main__":
    unittest.main(verbosity=1)
