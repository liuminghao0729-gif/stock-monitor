"""V2.0 选股规则的自动化测试(不联网)。运行:python3 tools/test_screener_v2.py"""
import os, sys, unittest, copy
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "api")]
import screener_v2 as S
from screener_config import CONFIG as CFG


def mkT(**o):
    T = dict(px=100.0, adv=50e6, sma5=99.0, sma5_prev=98.0, sma20=95.0, sma50=90.0, sma200=80.0, sma50_ago=88.0, sma200_ago=78.0, rsi=52.0, rsi_prev=49.0,
             rsi_min5=46.0, rsi_min15=40.0, adx=30.0, pdi=25.0, mdi=15.0, atr=2.0, slope=0.001, r2=0.6, hi52=105.0, lo52=60.0, range_pos=0.9, dd52=0.05,
             near_high=0.95, dd20=0.07, hh20=107.0, rs63=0.10, rs126=0.15, rs_pre=0.2, atr_pct=0.02, ext_atr=2.5, sma200_slope=0.02, vol_ratio=1.4,
             dn_vol=0.8, updn_vol=1.3, capit_vol=2.0, touch5=True, near5=False, pullback_low=94.0, prev_high=98.0, break_prev_high=0.02, cross_sma5=False,
             above20_2=True, break5=True, break10=True, breakout_pct=0.02, div={"found": False}, date="2026-11-06", day_chg=0.01)
    T.update(o)
    return T


def mkF(**o):
    F = dict(q_yoy=0.30, ttm_yoy=0.22, ttm_fcf=500e6, ttm_rev=3e9, fcf_m=0.15, fcf_m_yoy_q=0.02, runway=None, opinc_yoy=0.3, opm=0.2, opm_yoy_chg=0.02, gm=0.6,
             gm_yoy_chg=0.0, eps_yoy=0.3, roe=0.2, cash_debt=3.0, debt_eq=0.3, sector="Technology", industry="Software", has_data=True)
    F.update(o)
    return F


S1 = {"sym": "TEST", "name": "Test Inc", "cap": 20e9, "type_ok": True}
DIV = {"found": True, "p1": 10, "p2": 80, "signal_idx": 83, "low": 90.0, "strength": 0.5}


class Rules(unittest.TestCase):
    def test_01_growth_ok_but_fcf_negative_and_unsafe(self):
        F = mkF(q_yoy=0.30, ttm_fcf=-100e6, fcf_m_yoy_q=0.01, runway=10)
        self.assertEqual(S.eval_growth(S1, mkT(), F)["status"], "NONE")

    def test_02_growth_fcf_negative_but_fast_growth_and_cash(self):
        F = mkF(q_yoy=0.40, ttm_fcf=-100e6, fcf_m_yoy_q=0.05, runway=30)
        self.assertEqual(S.eval_growth(S1, mkT(), F)["status"], "CONFIRMED")

    def test_03_pullback_rsi46_reasonable_pullback_and_bounce(self):
        T = mkT(rsi_min5=46.0, rsi=51.0, rsi_prev=47.0, dd20=0.07, touch5=False, near5=False, px=100, prev_high=98)
        self.assertEqual(S.eval_pullback(S1, T, mkF(q_yoy=0.25, ttm_yoy=0.2))["status"], "CONFIRMED")

    def test_04_touch_lower_band_but_still_falling(self):
        T = mkT(px=75.0, sma200=80.0, sma50=82.0, touch5=True, rsi=30.0, rsi_prev=32.0)     # 跌破 200 日线,没有止跌
        self.assertEqual(S.eval_pullback(S1, T, mkF())["status"], "NONE")
        T2 = mkT(rsi=47.0, rsi_prev=49.0, px=96.0, prev_high=98.0, cross_sma5=False)        # 长期趋势在,但没有止跌 → 只能观察
        self.assertEqual(S.eval_pullback(S1, T2, mkF())["status"], "WATCHING")

    def test_05_macd_divergence_without_price_confirmation(self):
        T = mkT(div=DIV, break5=False, above20_2=False, rsi_min15=33, rsi=41, rsi_prev=38, dd52=0.4, range_pos=0.2, vol_ratio=0.9)
        ev = S.eval_reversal(dict(S1, cap=20e9), T, mkF())
        self.assertEqual(ev["status"], "WATCHING")

    def test_06_no_divergence_but_strict_path_b(self):
        T = mkT(div={"found": False}, rsi_min15=28, rsi=41, rsi_prev=38, break10=True, above20_2=True, vol_ratio=1.6, dd52=0.4, range_pos=0.2)
        ev = S.eval_reversal(S1, T, mkF())
        self.assertEqual((ev["status"], ev["path"]), ("CONFIRMED", "PRICE_VOLUME_REVERSAL"))
        T2 = mkT(div={"found": False}, rsi_min15=33, rsi=41, rsi_prev=38, break10=True, above20_2=True, vol_ratio=1.6, dd52=0.4, range_pos=0.2)   # RSI 最低 33 > 30
        self.assertNotEqual(S.eval_reversal(S1, T2, mkF())["status"], "CONFIRMED")

    def test_07_volume_up_mostly_on_down_days(self):
        # 近几天下跌日放量很大,但确认日(今天)自己的量能不足 → 不能确认
        T = mkT(div=DIV, dn_vol=2.5, updn_vol=0.4, vol_ratio=0.9, rsi_min15=33, rsi=41, rsi_prev=38, dd52=0.4, range_pos=0.2)
        self.assertNotEqual(S.eval_reversal(S1, T, mkF())["status"], "CONFIRMED")

    def test_08_negative_roe_pe_not_applicable(self):
        raw = {"series": {"quarterlyStockholdersEquity": [("2026-06-30", -5e9)], "quarterlyTotalDebt": [("2026-06-30", 8e9)]}, "qs": {"defaultKeyStatistics": {}, "financialData": {"returnOnEquity": {"raw": 0.9}}}}
        F = S.derive(raw)
        self.assertTrue(F["neg_equity"])
        self.assertIsNone(F["roe"])                         # 负净资产的 ROE 不参与评分
        self.assertIsNone(F["fpe"])
        self.assertIsNone(F["debt_eq"])
        stocks = [dict(S1, sym=f"S{i}", sector="Technology", industry="Software", M={"fcf_m": i / 10, "roe": None, "q_yoy": 0.3}) for i in range(5)]
        pool = S.Pool(stocks)
        sc, cov, det = S.score(stocks[0], "growth", pool, {})
        self.assertLess(cov, 1.0)                           # 缺失项不当作 0,也不当作达标,覆盖度如实下降

    def test_09_missing_data_never_passes(self):
        self.assertEqual(S.eval_growth(S1, mkT(), None)["status"], "DATA_INSUFFICIENT")
        self.assertEqual(S.eval_growth(S1, mkT(), {"has_data": False})["status"], "DATA_INSUFFICIENT")
        self.assertEqual(S.eval_growth(S1, None, mkF())["status"], "NONE")                      # 没有行情(R5)
        r = S.eval_pullback(S1, mkT(), mkF(ttm_yoy=None))
        self.assertEqual(r["status"], "DATA_INSUFFICIENT")                                      # TTM 同比缺失 → 不默认通过
        self.assertTrue(r["need_ttm"])
        stocks = [dict(S1, sym="X", sector=None, industry=None, M={"fcf_m": 0.1})]
        self.assertIsNotNone(S.Pool(stocks).pct(stocks[0], "fcf_m"))                            # 行业缺失 → 回退到全体,不报错

    def test_10_only_two_confirmed_shows_two(self):
        rows = [{"sym": "A", "status": "NEW", "score": 80}, {"sym": "B", "status": "STILL_VALID", "score": 70}, {"sym": "C", "status": "WATCHING", "score": 99}]
        top = S.top_rows(rows, 5)
        self.assertEqual([r["sym"] for r in top], ["A", "B"])                                    # 不凑数;观察的不计入

    def test_11_same_stock_two_strategies(self):
        T, F = mkT(), mkF(q_yoy=0.40)
        g, p = S.eval_growth(S1, T, F), S.eval_pullback(S1, T, F)
        self.assertEqual((g["status"], p["status"]), ("CONFIRMED", "CONFIRMED"))
        self.assertNotEqual([c["id"] for c in g["conds"]], [c["id"] for c in p["conds"]])        # 各自展示各自的通过理由

    def test_12_macd_pivot_needs_right_side_confirmation(self):
        c = [100.0] * 150
        c += [100 - 1.5 * i for i in range(1, 21)]                      # 急跌到 70(第一个低点,MACD 很负)
        c += [70 + 1.0 * i for i in range(1, 13)]                       # 反弹
        c += [82 - 0.55 * i for i in range(1, 24)]                      # 缓跌到更低(第二个低点,动能更弱)
        c += [c[-1] + 0.7 * i for i in range(1, 6)]                     # 之后上涨 5 根
        full = S.macd_divergence(c, S.macd_line(c))
        self.assertTrue(full["found"], "合成数据应形成底背离")
        p2, w = full["p2"], CFG["reversal"]["pivot_window"]
        at_signal = c[:p2 + w + 1]                                      # 第 p2+3 天:刚好完成右侧确认
        too_early = c[:p2 + w]                                          # 差 1 根:还不能识别
        ok = S.macd_divergence(at_signal, S.macd_line(at_signal))
        early = S.macd_divergence(too_early, S.macd_line(too_early))
        self.assertTrue(ok["found"] and ok["p2"] == p2 and ok["signal_idx"] == p2 + w)
        self.assertFalse(early["found"] and early["p2"] == p2)
        # 之后价格创出更低的新低 → 原背离被破坏
        broken = c[:p2 + 1 + 6] + [c[p2] - 1.0, c[p2] - 2.0]
        self.assertFalse(S.macd_divergence(broken, S.macd_line(broken))["found"] and S.macd_divergence(broken, S.macd_line(broken))["p2"] == p2)

    def test_13_previously_confirmed_now_invalid(self):
        hist = {"AAA|reversal": {"latest_status": "NEW", "first_confirmed_date": "2026-11-03", "invalid_below": 90.0}}
        today = {"AAA|reversal": {"status": "NONE", "score": None, "invalid_below": None, "px": 88.0}}
        h, st = S.update_history(hist, {}, "2026-11-06")
        self.assertEqual(st["AAA|reversal"], "INVALIDATED")
        h2, st2 = S.update_history(hist, {"AAA|reversal": {"status": "WATCHING", "score": 50, "px": 88.0}}, "2026-11-06")
        self.assertIn(st2["AAA|reversal"], ("WATCHING",))                                         # 今天仍在观察名单 → 以今天状态为准
        # 连续确认 → STILL_VALID,而不是每天都 NEW
        h3, s3 = S.update_history({}, {"BBB|growth": {"status": "CONFIRMED", "score": 70, "px": 10}}, "2026-11-05")
        h4, s4 = S.update_history(h3, {"BBB|growth": {"status": "CONFIRMED", "score": 71, "px": 11}}, "2026-11-06")
        self.assertEqual((s3["BBB|growth"], s4["BBB|growth"]), ("NEW", "STILL_VALID"))

    def test_16_same_day_rerun_keeps_new(self):
        t = {"BBB|growth": {"status": "CONFIRMED", "score": 70, "px": 10}}
        h1, s1 = S.update_history({}, t, "2026-11-06")
        h2, s2 = S.update_history(h1, t, "2026-11-06")                                           # 同一个数据日重跑
        h3, s3 = S.update_history(h2, t, "2026-11-09")                                           # 下一个交易日
        self.assertEqual((s1["BBB|growth"], s2["BBB|growth"], s3["BBB|growth"]), ("NEW", "NEW", "STILL_VALID"))

    def test_17_extra_risks_flag_late_entries(self):
        r = S.extra_risks("pullback", {"price": 120.0, "pullbackLow": 100.0, "rr": 0.2, "rsi": 72})
        self.assertEqual(len(r), 3)
        self.assertEqual(S.extra_risks("reversal", {"price": 130.0, "invalidBelow": 100.0, "rsi": 50}), ["价格已较确认低点上涨 30%,反转可能已经走了很远"])

    def test_14_capex_sign_not_double_subtracted(self):
        base = lambda cap: {"series": {"quarterlyTotalRevenue": [("d", 100.0)] * 5, "quarterlyOperatingCashFlow": [("d", 30.0)] * 5, "quarterlyCapitalExpenditure": [("d", cap)] * 5}, "qs": {}}
        neg, pos = S.derive(base(-5.0)), S.derive(base(5.0))                                     # CAPEX 记为负数或正数,结果一致:30-5=25 每季
        self.assertAlmostEqual(neg["ttm_fcf"], 100.0)
        self.assertAlmostEqual(pos["ttm_fcf"], 100.0)

    def test_15_five_quarters_only_limits_are_explicit(self):
        raw = {"series": {"quarterlyTotalRevenue": [("a", 100.0), ("b", 110.0), ("c", 120.0), ("d", 130.0), ("e", 150.0)]}, "qs": {}}
        F = S.derive(raw)
        self.assertAlmostEqual(F["q_yoy"], 0.5)
        self.assertIsNone(F["ttm_yoy"])                     # 免费数据算不出 TTM 同比,不编造


if __name__ == "__main__":
    unittest.main(verbosity=2)
