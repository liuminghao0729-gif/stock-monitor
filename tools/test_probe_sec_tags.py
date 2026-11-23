"""probe_sec_tags.py 的离线测试(合成数据,不联网)。运行:python3 tools/test_probe_sec_tags.py"""
import io, os, sys, contextlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe_sec_tags as P

def fact(start, end, val, filed): return {"start": start, "end": end, "val": val, "filed": filed}

def quarters(years, base=100):
    out = []
    for y in years:
        out += [fact(f"{y}-01-01", f"{y}-03-31", base, f"{y}-05-01"), fact(f"{y}-04-01", f"{y}-06-30", base + 10, f"{y}-08-01"),
                fact(f"{y}-07-01", f"{y}-09-30", base + 20, f"{y}-11-01"), fact(f"{y}-01-01", f"{y}-12-31", base * 4 + 60, f"{y+1}-02-01")]
    return out

def recent_quarters(n=8, base=100):
    """以今天为基准,往前数 n 个已经结束的自然季度(每个季度都直接给 3 个月的数字),这样「正常公司」的数据永远是新的。"""
    import datetime
    d = datetime.date.today() - datetime.timedelta(days=40)
    qe = datetime.date(d.year, 3 * ((d.month - 1) // 3 + 1), 1)
    ends = []
    for _ in range(n):
        m = qe.month
        end = datetime.date(qe.year + (m == 12), (m % 12) + 1, 1) - datetime.timedelta(days=1)
        ends.append((end - datetime.timedelta(days=89), end))
        qe = datetime.date(qe.year - (m == 3), (m - 3) if m > 3 else 12, 1)
    return [fact(a.isoformat(), b.isoformat(), base + i, (b + datetime.timedelta(days=30)).isoformat()) for i, (a, b) in enumerate(reversed(ends))]

def cf_of(gaap, name="TEST CO"):
    return {"entityName": name, "facts": {"us-gaap": {k: {"units": {"USD": v}} for k, v in gaap.items()}}}

def test_bank_with_new_revenue_tag_is_flagged():
    # 「收入」标签停在 2014;银行实际在用另一个标签,一直更新到 2025
    cf = cf_of({"Revenues": quarters([2013, 2014]), "InterestAndDividendIncomeOperating": quarters([2024, 2025], 500),
                "NetIncomeLoss": quarters([2013, 2014, 2024, 2025], 50)}, "BIG BANK")
    txt = P.report("BNK", cf)
    assert "===== BNK  BIG BANK =====" in txt
    assert "数据太旧" in txt, txt                                              # 程序现在的结果是停在 2014
    assert "★ 发现更新的候选标签" in txt and "InterestAndDividendIncomeOperating" in txt, txt
    assert "Revenues 最新 2014-12-31" in txt                                   # 我们认的标签里,Revenues 只到 2014

def test_company_without_usable_revenue_is_flagged_as_missing():
    cf = cf_of({"NetIncomeLoss": quarters([2024, 2025], 50), "OilAndGasRevenue": quarters([2024, 2025], 900)}, "OIL MAJOR")
    txt = P.report("OIL", cf)
    assert "数据缺失" in txt and "没有任何一个" in txt and "OilAndGasRevenue" in txt and "★" in txt, txt

def test_healthy_company_is_not_flagged():
    cf = cf_of({"Revenues": recent_quarters(), "NetIncomeLoss": recent_quarters(8, 10), "SalesRevenueServicesNet": quarters([2020], 5)})
    txt = P.report("OK", cf)
    assert "★" not in txt and "数据太旧" not in txt, txt
    assert "其他候选标签(都不比现有的新)" in txt and "SalesRevenueServicesNet" in txt

def test_foreign_filer_has_no_us_gaap():
    txt = P.report("FOR", {"entityName": "FOREIGN ADR", "facts": {"ifrs-full": {}, "dei": {}}})
    assert "没有 us-gaap" in txt and "ifrs-full" in txt and "FLOW" not in txt

def test_tag_summary_prefers_quarterly_and_counts():
    g = {"Revenues": {"units": {"USD": quarters([2025])}}}
    s = P.tag_summary(g, "Revenues", "USD")
    assert s["kind"] == "年度" and s["latest_end"] == "2025-12-31" and s["val"] == 460      # 全年数字的结束日比第三季度更晚
    g2 = {"Revenues": {"units": {"USD": quarters([2025])[:3]}}}                              # 只有三个季度时,取最新的季度
    s2 = P.tag_summary(g2, "Revenues", "USD"); assert s2["kind"] == "季度" and s2["latest_end"] == "2025-09-30" and s2["val"] == 120 and s2["n_q_2y"] == 3
    assert P.tag_summary(g, "Nope", "USD") is None

def test_main_requires_contact_and_never_prints_it():
    sys.argv = ["probe_sec_tags.py", "BNK"]
    os.environ.pop("SEC_CONTACT", None)
    try:
        P.main(); assert False, "没有联系邮箱必须退出"
    except SystemExit as e:
        assert "SEC_CONTACT" in str(e)
    secret = "very.secret.person@example.test"
    os.environ["SEC_CONTACT"] = secret
    tk = {"0": {"cik_str": 7, "ticker": "BNK"}}
    cf = cf_of({"Revenues": quarters([2013, 2014])}, "BIG BANK")
    real = P.fetch
    P.fetch = lambda url, contact: tk if "company_tickers" in url else cf
    P.time.sleep = lambda s: None
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            P.main()
    finally:
        P.fetch = real
    out = buf.getvalue()
    assert secret not in out and "example.test" not in out, "输出里不能出现联系邮箱"
    assert "SEC_CONTACT 已设置(不会显示)" in out and "BIG BANK" in out
    os.environ["SEC_CONTACT"] = "中文@例子.com"
    try:
        P.main(); assert False
    except SystemExit:
        pass
    os.environ.pop("SEC_CONTACT", None)

if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); n += 1; print("ok", k)
    print(n, "passed")
