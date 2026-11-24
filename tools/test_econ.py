"""经济日历后端(api/_core.py 的 econ / fomc_events)的离线测试:不联网,FRED 用假数据。运行:python3 tools/test_econ.py"""
import datetime, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import _core as C

def rd(date, name): return {"release_id": 1, "release_name": name, "date": date}

def test_fomc_dates_and_minutes_rule_match_the_fed_page():
    # 美联储页面上 2026 年已公布的纪要日期:我们按「决议后三周」推算的结果必须和它一致
    ev = C.fomc_events("2026-01-01", "2026-12-31")
    mins = sorted(e["date"] for e in ev if e["key"] == "fomc_min")
    for d in ("2026-02-18", "2026-04-08", "2026-05-20", "2026-07-08", "2026-08-19", "2026-10-07", "2026-11-18"):
        assert d in mins, (d, mins)
    dec = [e for e in ev if e["key"] == "fomc" and e["date"] == "2026-12-09"][0]
    assert dec["imp"] == 3 and "12-08 至 12-09" in dec["desc"] and "经济预测摘要" in dec["desc"], dec          # 12 月会议带经济预测
    jan = [e for e in ev if e["key"] == "fomc" and e["date"] == "2026-01-28"][0]
    assert "经济预测摘要" not in jan["desc"], jan                                                            # 1 月会议不带
    assert len([e for e in ev if e["key"] == "fomc"]) == 8                                                 # 2026 年共 8 次例会

def test_fomc_2027_has_no_projection_claim():
    ev = C.fomc_events("2027-01-01", "2027-12-31")
    f = [e for e in ev if e["key"] == "fomc"]
    assert len(f) == 8 and all("经济预测摘要" not in e["desc"] for e in f)        # 页面还没标 2027 年哪些会议带经济预测,我们不替它说
    assert [e["date"] for e in f][:2] == ["2027-01-27", "2027-03-17"] and f[-1]["date"] == "2027-11-17"

def test_fomc_range_filter():
    assert C.fomc_events("2026-11-22", "2026-12-08") == []                                                  # 12-09 还没到
    ev = C.fomc_events("2026-11-22", "2026-12-31")
    assert [(e["key"], e["date"]) for e in ev] == [("fomc", "2026-12-09"), ("fomc_min", "2026-12-30")]

def test_econ_merges_fred_and_fomc_sorted_and_deduped():
    real = C._fred
    C._fred = lambda path, params, ttl: {"release_dates": [
        rd("2026-12-10", "Consumer Price Index"), rd("2026-12-05", "Employment Situation"), rd("2026-12-05", "Employment Situation"),   # 重复:只留一条
        rd("2026-12-18", "Gross Domestic Product"), rd("2026-12-18", "Gross Domestic Product: Advance Estimate"),                      # 同一天两个 GDP 名字:只留一条
        rd("2026-12-09", "FOMC Press Release"),                                                                                       # FOMC 以美联储官网日程为准,忽略 FRED 的
        rd("2026-12-11", "Producer Price Index"), rd("2026-12-12", "Some Obscure Release"), rd("2027-02-01", "Consumer Price Index"),    # 不认识的、范围外的忽略
        rd("2026-11-20", "Job Openings and Labor Turnover Survey")]}
    try:
        r = C.econ("2026-12-01", "2026-12-31")
    finally:
        C._fred = real
    assert r["fred"] is True
    got = [(i["date"], i["key"], i["imp"]) for i in r["items"]]
    assert got == [("2026-12-05", "jobs", 3), ("2026-12-09", "fomc", 3), ("2026-12-10", "cpi", 3), ("2026-12-11", "ppi", 2), ("2026-12-18", "gdp", 3), ("2026-12-30", "fomc_min", 2)], got
    assert all(i["desc"] and i["src"] for i in r["items"])

def test_econ_without_fred_still_returns_fomc():
    real, key = C._fred, os.environ.pop("FRED_KEY", None)
    try:
        C._fred = real                                        # 真实的 _fred:没有 Key 返回 None
        r = C.econ("2026-12-01", "2026-12-31")
        assert r["fred"] is False and [i["key"] for i in r["items"]] == ["fomc", "fomc_min"], r
        C._fred = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        r = C.econ("2026-12-01", "2026-12-31")
        assert r["fred"] is False and len(r["items"]) == 2, r
    finally:
        C._fred = real
        if key: os.environ["FRED_KEY"] = key

def test_fred_pagination():
    calls = []
    def fake(path, params, ttl):
        calls.append(params["offset"])
        return {"release_dates": [rd("2026-12-10", "Noise")] * 1000} if params["offset"] == 0 else {"release_dates": [rd("2026-12-20", "Consumer Price Index")]}
    real = C._fred; C._fred = fake
    try:
        r = C.econ("2026-12-01", "2026-12-31")
    finally:
        C._fred = real
    assert calls == [0, 1000] and any(i["key"] == "cpi" and i["date"] == "2026-12-20" for i in r["items"]), calls      # 第一页满了要继续翻页

def test_route_validation():
    real = C._fred; C._fred = lambda *a, **k: {"release_dates": []}
    try:
        ok = C.route("macro", {"part": "econ", "from": "2026-11-22", "to": "2026-12-22"})
        assert ok[0] == 200 and ok[1]["from"] == "2026-11-22" and ok[2] == 21600 and any(i["key"] == "fomc" for i in ok[1]["items"])
        assert C.route("macro", {"part": "econ", "from": "2026-12-22", "to": "2026-11-22"})[:2] == (400, {"error": "bad range"})
        assert C.route("macro", {"part": "econ", "from": "2026-01-01", "to": "2026-12-31"})[:2] == (400, {"error": "bad range"})     # 超过 62 天
        assert C.route("macro", {"part": "econ", "from": "乱码", "to": "2026-12-31"})[:2] == (400, {"error": "bad date"})
        d = C.route("macro", {"part": "econ"})                                                                                      # 不带参数:今天起 30 天
        assert d[0] == 200 and d[1]["from"] == str(datetime.date.today())
    finally:
        C._fred = real

def test_fast_path_one_call_per_release_and_fallback():
    """快路径:先取发布清单,再只对关心的发布各查一次;出错时 econ() 回到慢路径,结果一样。"""
    calls = []
    rels = {"releases": [{"id": 10, "name": "Consumer Price Index"}, {"id": 99, "name": "Some Other Release"}, {"id": 50, "name": "Employment Situation"},
                         {"id": 7, "name": "FOMC Press Release"}]}
    def fake(path, params, ttl):
        calls.append(path)
        if path == "releases":
            return rels
        if path == "release/dates":
            return {"release_dates": [{"release_id": params["release_id"], "date": "2026-12-10" if params["release_id"] == 10 else "2026-12-04"}]}
        return {"release_dates": [rd("2026-12-10", "Consumer Price Index")]}          # 慢路径(releases/dates)
    old = C._fred; C._fred = fake
    try:
        r = C.econ("2026-11-22", "2026-12-22")
        assert [(i["key"], i["date"]) for i in r["items"] if i["key"] in ("cpi", "jobs")] == [("jobs", "2026-12-04"), ("cpi", "2026-12-10")], r
        assert calls.count("release/dates") == 2 and "releases/dates" not in calls, calls    # 只查了 CPI 和非农,没查无关发布和 FOMC,也没走慢路径
        calls.clear()
        def broken(path, params, ttl):
            calls.append(path)
            if path == "release/dates": raise RuntimeError("boom")
            return fake(path, params, ttl)
        C._fred = broken
        r = C.econ("2026-11-22", "2026-12-22")
        assert r["fred"] is True and any(i["key"] == "cpi" for i in r["items"]) and "releases/dates" in calls, (r, calls)   # 快路径出错 -> 慢路径兜底
    finally:
        C._fred = old

if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); n += 1; print("ok", k)
    print(n, "passed")
