"""api/_fin.py 的离线测试(合成数据,不联网)。运行:python3 tools/test_fin.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import _fin

def fact(start, end, val, filed, **kw):
    d = {"end": end, "val": val, "filed": filed}
    if start: d["start"] = start
    d.update(kw); return d

def cf(rev, ni=None, ocf=None, capex=None):
    g = {"Revenues": {"units": {"USD": rev}}}
    if ni: g["NetIncomeLoss"] = {"units": {"USD": ni}}
    if ocf: g["NetCashProvidedByUsedInOperatingActivities"] = {"units": {"USD": ocf}}
    if capex: g["PaymentsToAcquirePropertyPlantAndEquipment"] = {"units": {"USD": capex}}
    return {"facts": {"us-gaap": g}}

def test_q4_derived_and_filed():
    rev = []
    for y in (2023, 2024):                       # 每年:Q1-Q3 直接披露,全年另给
        rev += [fact(f"{y}-01-01", f"{y}-03-31", 100, f"{y}-05-01"), fact(f"{y}-04-01", f"{y}-06-30", 110, f"{y}-08-01"),
                fact(f"{y}-07-01", f"{y}-09-30", 120, f"{y}-11-01"), fact(f"{y}-01-01", f"{y}-12-31", 460, f"{y+1}-02-01")]
    q = _fin.quarters_flow(rev)
    assert q["2023-12-31"] == (130, "2024-02-01", True), q["2023-12-31"]       # 460-330=130,推算
    assert q["2023-03-31"][0] == 100 and q["2023-03-31"][2] is False

def test_cashflow_ytd():
    ocf = [fact("2024-01-01", "2024-03-31", 10, "2024-05-01"), fact("2024-01-01", "2024-06-30", 25, "2024-08-01"),
           fact("2024-01-01", "2024-09-30", 45, "2024-11-01"), fact("2024-01-01", "2024-12-31", 70, "2025-02-01")]
    q = _fin.quarters_flow(ocf)
    assert [q[e][0] for e in ("2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31")] == [10, 15, 20, 25], q

def test_restatement_uses_latest_value_earliest_filed():
    rows = _fin._dedupe([fact("2024-01-01", "2024-03-31", 100, "2024-05-01"), fact("2024-01-01", "2024-03-31", 98, "2025-05-01")])
    assert rows[0]["val"] == 98 and rows[0]["first"] == "2024-05-01"

def test_52_week_quarters_and_ttm():
    ends = ["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31", "2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31"]
    starts = ["2023-01-01", "2023-04-01", "2023-07-01", "2023-10-01", "2024-01-01", "2024-04-01", "2024-07-01", "2024-10-01", "2025-01-01"]
    rev = [fact(s, e, 100 + 10 * i, e[:4] + "-12-01") for i, (s, e) in enumerate(zip(starts, ends))]
    rows, t, _ = _fin.build(cf(rev, ni=[dict(r, val=r["val"] / 10) for r in rev]))
    assert t["rev"] == sum(100 + 10 * i for i in range(5, 9))                        # 最近四季求和
    assert rows[-1]["rev_yoy"] is not None and abs(rows[-1]["rev_yoy"] - (180 / 140 - 1) * 100) < 1e-9

def test_no_gaap_and_error_paths():
    os.environ.pop("SEC_CONTACT", None)
    assert _fin.fin("AAPL") == {"error": "no_contact"}
    os.environ["SEC_CONTACT"] = "中文@例子.com"
    assert _fin.fin("AAPL") == {"error": "bad_contact"}
    os.environ["SEC_CONTACT"] = "a@b.com"
    assert _fin.fin("SPX") == {"error": "not_stock"}

def test_stale_data_is_not_shown():
    """部分银行(如 JPM)的 SEC 数据停在 2014 年:fin() 和 health() 都要拦住,不能把旧数字当最新。"""
    import datetime, _health
    today = datetime.date(2026, 11, 22)
    assert _fin.is_stale("2014-12-31", today) and not _fin.is_stale("2026-09-26", today)
    assert _fin.is_stale("2026-05-05", today) is True and _fin.is_stale("2026-05-06", today) is False       # 刚好 200 天不算旧,201 天算旧
    assert _fin.is_stale("乱码", today) is True and _fin.is_stale(None, today) is True                       # 日期坏了一律当过期
    rev = []
    for y in (2013, 2014):
        rev += [fact(f"{y}-01-01", f"{y}-03-31", 100, f"{y}-05-01"), fact(f"{y}-04-01", f"{y}-06-30", 110, f"{y}-08-01"),
                fact(f"{y}-07-01", f"{y}-09-30", 120, f"{y}-11-01"), fact(f"{y}-01-01", f"{y}-12-31", 460, f"{y+1}-02-01")]
    old = cf(rev, ni=[dict(r, val=r["val"] / 10) for r in rev])
    tk = {"0": {"cik_str": 1, "ticker": "OLD"}}
    real = _fin.C._get
    _fin.C._get = lambda url, ttl=10, headers=None: tk if "company_tickers" in url else old
    os.environ["SEC_CONTACT"] = "a@b.com"
    try:
        f = _fin.fin("OLD")
        assert f["error"] == "stale" and f["asof"] == "2014-12-31" and "rows" not in f, f
        h = _health.health("OLD")
        assert h["error"] == "stale" and h["asof"] == "2014-12-31" and "checkup" not in h and "dcf" not in h, h
    finally:
        _fin.C._get = real

def test_cik_lookup_and_404():
    """BRK-B 以前永远查不到(代码先把 - 换成 . 再去对 SEC 的 BRK-B);SPY 这类有代码但没财报的,不能 500。"""
    import urllib.error, _health
    tk = {"0": {"cik_str": 1067983, "ticker": "BRK-B"}, "1": {"cik_str": 320193, "ticker": "AAPL"}, "2": {"cik_str": 884394, "ticker": "SPY"}, "3": {"cik_str": 9, "ticker": "BF-B"}}
    C = _fin.C
    assert C.sec_cik(tk, "BRK-B") == 1067983 and C.sec_cik(tk, "BRK.B") == 1067983      # 两种写法都认
    assert C.sec_cik(tk, "BF.B") == 9 and C.sec_cik(tk, "AAPL") == 320193 and C.sec_cik(tk, "NOPE") is None
    real = C._get
    def fake(url, ttl=10, headers=None):
        if "company_tickers" in url: return tk
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    C._get = fake
    os.environ["SEC_CONTACT"] = "a@b.com"
    try:
        assert _fin.fin("SPY") == {"error": "no_facts"}
        assert _health.health("SPY") == {"error": "no_facts"}
        assert _fin.fin("BRK.B") == {"error": "no_facts"}                                 # 找到了公司,只是没有财报数据 → 不再是 no_cik
    finally:
        C._get = real

def test_bank_revenue_tag():
    """银行(摩根士丹利、富国、摩根大通)用 RevenuesNetOfInterestExpense 当总收入,不能漏掉。"""
    rev = [fact(f"2026-{a}", f"2026-{b}", v, "2026-11-01") for a, b, v in (("01-01", "03-31", 100), ("04-01", "06-30", 110), ("07-01", "09-30", 120))]
    rev += [fact(f"2025-{a}", f"2025-{b}", 90, "2025-11-01") for a, b in (("01-01", "03-31"), ("04-01", "06-30"), ("07-01", "09-30"), ("10-01", "12-31"))]
    c = {"facts": {"us-gaap": {"RevenuesNetOfInterestExpense": {"units": {"USD": rev}}}}}
    assert _fin._facts(c, _fin.FLOW["rev"], "USD"), "银行总收入标签没被认出"

def test_tag_switch_gap_filled():
    """季度数据在一个标签、全年数据在另一个标签(uniQure、Cerebras 这类):合并后才能推算出第四季度。"""
    q = [fact("2025-01-01", "2025-03-31", 10, "2025-05-01"), fact("2025-04-01", "2025-06-30", 11, "2025-08-01"), fact("2025-07-01", "2025-09-30", 12, "2025-11-01"),
         fact("2026-01-01", "2026-03-31", 13, "2026-05-01"), fact("2026-04-01", "2026-06-30", 14, "2026-08-01"), fact("2026-07-01", "2026-09-30", 15, "2026-11-01")]
    a = [fact("2025-01-01", "2025-12-31", 50, "2026-02-01")]
    c = {"facts": {"us-gaap": {"RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": q}}, "RevenueFromContractWithCustomerIncludingAssessedTax": {"units": {"USD": a}}}}}
    assert _fin.quarters_flow(_fin._facts(c, _fin.FLOW["rev"], "USD"))["2025-12-31"][0] == 17   # 50 - 33

if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); n += 1; print("ok", k)
    print(n, "passed")
