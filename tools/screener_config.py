"""选股 V2.0 的全部可调参数。所有数值都集中在这里,代码里不再硬编码。
这些是初始参数,不是经过统计验证的最优值。"""

CONFIG = {
    # ---- Layer 1:股票池 R1–R5 ----
    "universe": {
        "cap_min": {"growth": 5e9, "pullback": 5e9, "reversal": 10e9},    # R1 市值下限(美元)
        "cap_tiers": {"mid": (5e9, 10e9), "large": (10e9, 100e9), "mega": (100e9, float("inf"))},
        "adv_min": 20e6,            # R2 近 60 日平均成交额(美元)
        "adv_days": 60,
        "price_min": 10.0,          # R3
        "min_history": 252,         # R5 至少 252 个交易日
        "exchanges": ("NMS", "NYQ"),
        "unsupported_sectors": ("Financial Services", "Real Estate"),     # 银行/保险/REIT 暂不套用 FCF、毛利率模型
        "exclude_name_words": ("warrant", "preferred", " etf", " etn", "acquisition corp", "trust"),
    },
    # ---- 技术指标窗口(Wilder 算法 RSI/ADX/ATR;均线用 SMA)----
    "ind": {"rsi": 14, "adx": 14, "atr": 14, "boll_n": 20, "boll_k": 2.0, "trend_n": 60, "range_days": 252},
    # ---- 激进成长 ----
    "growth": {
        "g1_q_yoy": 0.25,                     # G1-A:最新季度营收同比
        "g1b_enabled": False,                 # G1-B 需要"前一季度同比",免费数据拿不到 → 关闭并如实披露
        "fcf_b_q_yoy": 0.35, "fcf_b_margin_improve": 0.03, "runway_months": 18,   # 财务安全 B 路径
        "adx_min": 20, "sma50_slope_days": 20, "rs_days": 63,
        "r2_bonus": 0.35, "adx_bonus": 25, "near_high_pct": 0.90,
        "extended_atr_mult": 2.0,
        "watch_max_miss": 1,                  # 趋势条件(AG4–AG7)只差 1 项 → WATCHING
    },
    # ---- 强势回调 ----
    "pullback": {
        "g1_q_yoy": 0.20, "g1_ttm_yoy": 0.15,
        "sma200_slope_days": 20,
        "touch_days": 5, "atr_touch_mult": 0.5, "dd20_min": 0.04, "dd20_max": 0.12, "dd_window": 20,
        "rsi_min5_max": 50, "rsi_bounce": 3.0,
        "vol_bonus_mult": 1.0,
    },
    # ---- 超跌反转 ----
    "reversal": {
        "range_pos_max": 0.35, "dd52_min": 0.25,
        "rsi_lookback": 15, "rsi_min_max": 35, "rsi_now_min": 40,
        "runway_months": 18,
        "pivot_window": 3, "pivot_gap": 10, "pivot_lookback": 90, "pivot_recent": 20,
        "vol_mult_A": 1.2, "breakout_A": 5,
        "pathB_rsi_min": 30, "pathB_breakout": 10, "pathB_vol_mult": 1.5, "pathB_closes_above_sma20": 2,
    },
    # ---- 评分:总分 0–100,三个组合权重各自独立 ----
    # 子项 (指标, 类型 p=池内百分位 / d=已归一化的 0–1 直接值, 越高越好?, 子权重)
    "score": {
        "growth": [
            ("增长与加速", 0.25, [("q_yoy", "p", True, .40), ("opinc_yoy", "p", True, .20), ("eps_yoy", "p", True, .20), ("opm_yoy_chg", "p", True, .20)]),
            ("盈利与现金流质量", 0.20, [("fcf_m", "p", True, .40), ("opm", "p", True, .20), ("gm", "p", True, .20), ("gm_yoy_chg", "p", True, .20)]),
            ("相对强度与预期变化", 0.20, [("rs63", "p", True, .40), ("rs126", "p", True, .20), ("eps_rev30", "p", True, .20), ("surprise", "p", True, .20)]),
            ("技术趋势与动量", 0.20, [("adx", "p", True, .30), ("r2", "p", True, .30), ("near_high", "p", True, .40)]),
            ("估值与下行风险", 0.15, [("ev_rev", "p", False, .25), ("fcf_yield", "p", True, .25), ("peg", "p", False, .15), ("atr_pct", "p", False, .20), ("ext_atr", "p", False, .15)]),
        ],
        "pullback": [
            ("企业基本面质量", 0.25, [("fcf_m", "p", True, .30), ("q_yoy", "p", True, .25), ("opm", "p", True, .15), ("roe", "p", True, .15), ("gm", "p", True, .15)]),
            ("回调前相对强度", 0.15, [("rs_pre", "p", True, .60), ("rs126", "p", True, .40)]),
            ("回调健康程度", 0.25, [("depth_fit", "d", True, .30), ("dn_vol", "p", False, .35), ("sma200_slope", "p", True, .35)]),
            ("止跌和买盘确认", 0.20, [("rsi_bounce", "p", True, .30), ("vol_ratio", "p", True, .40), ("break_prev_high", "p", True, .30)]),
            ("估值与下行风险", 0.15, [("ev_rev", "p", False, .25), ("fcf_yield", "p", True, .25), ("peg", "p", False, .15), ("atr_pct", "p", False, .20), ("ext_atr", "p", False, .15)]),
        ],
        "reversal": [
            ("资产负债表与财务安全", 0.25, [("cash_debt", "p", True, .30), ("debt_eq", "p", False, .20), ("fcf_m", "p", True, .30), ("runway_score", "d", True, .20)]),
            ("抛售衰竭程度", 0.20, [("rsi_min15", "p", False, .35), ("dd52", "p", True, .25), ("capit_vol", "p", True, .40)]),
            ("技术反转确认强度", 0.30, [("path_score", "d", True, .50), ("div_strength", "d", True, .25), ("breakout_pct", "p", True, .25)]),
            ("上涨成交量确认", 0.15, [("vol_ratio", "p", True, .60), ("updn_vol", "p", True, .40)]),
            ("估值修复空间", 0.10, [("fcf_yield", "p", True, .30), ("ev_rev", "p", False, .20), ("dd52", "p", True, .50)]),
        ],
    },
    "score_min_coverage": 0.80,
    "pool_min_group": 30,          # 行业样本不足 30,逐级用更大分类
    "winsor": (0.05, 0.95),        # 极端值截尾
    # ---- 输出 ----
    "stickiness_margin": 5,        # 名单稳定性:已在名单里的股票排序时加 5 分,新候选必须明显更好才会替换(显示的分数不变)
    "max_confirmed": 5, "max_watching": 5, "invalidated_keep_days": 5,
    "risk": {"gm_drop": -0.05, "high_debt_eq": 2.0, "high_atr_pct": 0.06},
}
