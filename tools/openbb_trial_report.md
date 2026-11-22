# OpenBB 离线试用报告(2026-11-22)

环境:`.tools/openbbvenv/`(Python 3.12,约 959MB,已被 .gitignore 忽略;HOME 指到 `.tools/openbbhome`,未写项目外目录)。
OpenBB 5.0 按数据商分模块(obb.sec / obb.nasdaq / obb.finra …),不带 yfinance 和 FMP 扩展。只测了免费、无需 Key 的接口。
复现:`HOME=$PWD/.tools/openbbhome .tools/openbbvenv/bin/python tools/openbb_probe.py`(和 openbb_probe2.py)

| 数据 | 接口 | 结果 | 我们现有 |
|---|---|---|---|
| 内部人交易 | sec.insider_trading | ✅ 8 条,3 秒,官方 | Yahoo 有 |
| 机构持仓(谁持有 NVDA) | nasdaq.equity.ownership.institutional | ✅ 50 条,含持股变化 | 没有 |
| 做空数据 | finra.equity.shorts / nasdaq short_interest | ✅ 24~213 条,含 days_to_cover | Yahoo 有当前值,无历史 |
| 10 年日线 | nasdaq.equity.historical | ✅ 2514 行 | 回测数据来源待确认 |
| 分析师目标价共识 | nasdaq.estimates.consensus | ✅ 高/低/均值/买入数 | FMP 需 Key |
| 升降级 | nasdaq.estimates.price_target | ❌ 常为空 | FMP |
| Cboe 日线 | cboe.equity.historical | ❌ 403 | - |
| sec.form_13f(symbol=NVDA) | | 返回的是 NVDA 自己作为机构的持仓,不是谁持有 NVDA | - |

注意:Nasdaq、FINRA 接口非官方 API,可能改版失效;13F 是季度数据,有延迟。
