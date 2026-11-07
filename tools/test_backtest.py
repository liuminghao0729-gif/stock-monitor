"""回测引擎的正确性测试(不联网)。运行:python3 tools/test_backtest.py"""
import os, random, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "api")]
import backtest as B
import screener_v2 as S


class Engine(unittest.TestCase):
    def test_wilder_series_matches_screener_indicators(self):
        random.seed(7)
        c, h, l = [], [], []
        x = 100.0
        for _ in range(300):
            x *= 1 + random.uniform(-.02, .021)
            c.append(x); h.append(x * (1 + random.uniform(0, .01))); l.append(x * (1 - random.uniform(0, .01)))
        atr, adx, pdi, mdi = B.wilder_series(h, l, c)
        _, a2, p2, m2 = S.wilder_atr_adx(h, l, c)
        self.assertAlmostEqual(adx[-1], a2, places=6)
        self.assertAlmostEqual(pdi[-1], p2, places=6)
        self.assertAlmostEqual(mdi[-1], m2, places=6)

    def test_trade_return_includes_costs(self):
        ev = {"path": [0.10, 0.0, 0.10]}                                  # 入场当天 +10%,之后不动,再 +10%
        gross = 1.1 * 1.0 * 1.1 - 1
        net = B.trade_ret(ev, 2)
        self.assertAlmostEqual(net, (1 + gross) * (1 - B.COST_SIDE) / (1 + B.COST_SIDE) - 1, places=9)
        self.assertLess(net, gross)
        self.assertIsNone(B.trade_ret(ev, 5))                              # 数据不够不计入

    def test_divergence_uses_only_confirmed_pivots(self):
        c = [100.0] * 150 + [100 - 1.5 * i for i in range(1, 21)] + [70 + 1.0 * i for i in range(1, 13)] + [82 - 0.55 * i for i in range(1, 24)]
        c += [c[-1] + 0.7 * i for i in range(1, 6)]
        mc = S.macd_line(c)
        piv = B.pivot_lows(c, 3)
        p2 = 150 + 20 + 12 + 23 - 1                                            # 第二个低点的位置
        self.assertIn(p2, piv)
        self.assertFalse(B.div_signal(c, mc, piv, p2 + 2, 3, 90, 10, 20))   # 右侧只有 2 根,还没确认
        self.assertTrue(B.div_signal(c, mc, piv, p2 + 3, 3, 90, 10, 20))    # 第 3 根出现,刚好确认
        self.assertFalse(B.div_signal(c, mc, piv, p2 + 25, 3, 90, 10, 20))  # 太久以前的不算

    def test_portfolio_mdd(self):
        idx = {f"d{i}": i for i in range(10)}
        ev = [{"date": "d0", "path": [-0.10, -0.10, 0.0]}]
        mdd = B.portfolio_mdd(ev, 2, idx)
        self.assertLess(mdd, -0.19)                                         # 先跌 10% 再跌 10% ≈ -19%(再加成本)

    def test_regime(self):
        spy = {"d": [f"{i}" for i in range(400)], "c": [100 + i * .2 for i in range(400)]}
        r = B.regime_map(spy)
        self.assertEqual(r["399"], "BULL")


if __name__ == "__main__":
    unittest.main(verbosity=1)
