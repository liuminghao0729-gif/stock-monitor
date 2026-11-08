"""强趋势龙头推荐的规则测试(不联网)。运行:python3 tools/test_picks.py"""
import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "api")]
import picks as P


def mk(n=200):
    """n 只合格股票:成交额、离200日线距离、ATR%、3个月涨幅 都互不相同且单调。"""
    return [{"sym": f"S{i}", "adv": 20e6 + i * 1e6, "dist200": i / n, "atrp": i / n * 0.08, "mom63": i / n * 0.5} for i in range(n)]


class Rules(unittest.TestCase):
    def test_rank_pct_ties(self):
        r = P.rank_pct([1, 2, 2, 3])
        self.assertEqual(r[0], 0.0)
        self.assertEqual(r[3], 1.0)
        self.assertAlmostEqual(r[1], r[2])

    def test_entry_needs_all_three_conditions(self):
        rows = mk()
        entry, stay, ranks = P.decide(rows, set())
        self.assertTrue(entry)
        for s in entry:
            self.assertTrue(all(ranks[s][k] >= P.ENTRY[k] for k in P.ENTRY))
        # 只在成交额前 50% 里排名:成交额最低的一半不会入选
        low_half = {r["sym"] for r in rows[:100]}
        self.assertFalse(low_half & set(entry))
        # 某只股票 dist200 很高但 ATR% 很低 → 不入选
        rows[190]["atrp"] = 0.0001
        entry2, _, _ = P.decide(rows, set())
        self.assertNotIn("S190", entry2)

    def test_stay_band_is_wider_than_entry(self):
        rows = mk()
        entry, _, ranks = P.decide(rows, set())
        # 构造一个老成员:排名跌到入选线以下,但仍在保留线以上
        cand = [s for s, r in ranks.items() if P.STAY["dist200"] <= r["dist200"] < P.ENTRY["dist200"] and r["atrp"] >= P.STAY["atrp"] and r["mom63"] >= P.STAY["mom63"]]
        self.assertTrue(cand)
        entry2, stay2, _ = P.decide(rows, {cand[0]})
        self.assertNotIn(cand[0], entry2)
        self.assertIn(cand[0], stay2)                                      # 老成员保留
        _, stay3, _ = P.decide(rows, {"S10"})                              # 排名很低的老成员 → 不保留
        self.assertNotIn("S10", stay3)

    def test_too_few_stocks_gives_nothing(self):
        self.assertEqual(P.decide(mk(20), set())[0], [])

    def test_state_new_then_still_valid_then_invalidated(self):
        r1 = P.update_state({}, ["A", "B"], [], "2026-11-06")
        self.assertEqual((r1["A"]["status"], r1["A"]["first_date"]), ("NEW", "2026-11-06"))
        r1b = P.update_state(r1, ["A", "B"], [], "2026-11-06")             # 同一天重跑:保持 NEW
        self.assertEqual(r1b["A"]["status"], "NEW")
        r2 = P.update_state(r1, ["A"], ["B"], "2026-11-09")                # B 不再入选但仍满足放宽条件 → 保留
        self.assertEqual((r2["A"]["status"], r2["B"]["status"]), ("STILL_VALID", "STILL_VALID"))
        self.assertEqual(r2["B"]["first_date"], "2026-11-06")
        r3 = P.update_state(r2, ["A"], [], "2026-11-10")                   # B 跌出放宽条件 → 失效
        self.assertEqual(r3["B"]["status"], "INVALIDATED")
        r4 = P.update_state(r3, ["A"], [], "2026-11-20")                   # 失效超过 5 天后从记录里清掉
        self.assertNotIn("B", r4)
        r5 = P.update_state(r3, ["A", "B"], [], "2026-11-11")              # 失效的股票重新入选 → 当作新的
        self.assertEqual((r5["B"]["status"], r5["B"]["first_date"]), ("NEW", "2026-11-11"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
