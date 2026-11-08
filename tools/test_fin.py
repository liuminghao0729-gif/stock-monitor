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

if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); n += 1; print("ok", k)
    print(n, "passed")
