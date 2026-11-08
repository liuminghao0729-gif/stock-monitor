"""财务体检/F 分/Z 分/内在价值的离线测试(不联网)。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))
import _health as H

P = dict(rev=900, gp=300, oi=120, ni=90, ocf=110, capex=-30, fcf=80, cash=100, debt=50, dc=0, equity=400, assets=1000, liab=600, ca=500, cl=250, re=300, shares=100, intexp=5, cr=2.0, dr=60)
Y = dict(P, rev=1000, gp=360, oi=150, ni=120, ocf=140, fcf=110, shares=98, assets=1050, cr=2.2, cash=150, debt=40)

# F 分:构造一个 9 项全过的例子
f = H.fscore(Y, P)
assert f["of"] == 9 and f["score"] == 9, f
# 增发 + 亏损 -> 分数下降
bad = dict(Y, ni=-10, ocf=-5, shares=120)
f2 = H.fscore(bad, P)
fails = {c["name"] for c in f2["checks"] if c["ok"] is False}
assert {"今年赚钱(ROA>0)", "经营现金流为正", "没有增发摊薄股东"} <= fails and f2["score"] == 5, f2
# 缺数据的项不计入分母
f3 = H.fscore({k: v for k, v in Y.items() if k != "shares"}, P)
assert f3["of"] == 8, f3

# Z'' 分数手算:x1=(500-250)/1000=.25, x2=.3, x3=.12, x4=400/600
z = H.zscore(P)
exp = 6.56 * .25 + 3.26 * .3 + 6.72 * .12 + 1.05 * (400 / 600)
assert abs(z["z"] - round(exp, 2)) < 1e-9, (z, exp)
assert H.zscore({"ca": None})["error"] == "n/a"

# 内在价值:负现金流不给,正常情况下 保守 < 中性 < 乐观
yrs = [dict(rev=100 * 1.1 ** i, fcf=10 * 1.1 ** i, cash=50, debt=10, dc=0, end=f"20{20 + i}-12-31") for i in range(6)]
d = H.dcf(yrs, 10, 50)
v = [s["value"] for s in d["scenarios"]]
assert v[0] < v[1] < v[2], v
neg = [dict(y, fcf=-1) for y in yrs]
assert H.dcf(neg, 10, 50)["error"] == "n/a"

# 体检:阈值分档
t = dict(gm=45, om=25, nm=20, rev_yoy=12, ni_yoy=-3, fcf=100, rev=1000, ni=120, eps=3)
items = {i["name"]: i for i in H.checkup(Y, P, t, 98, 60)}
assert items["毛利率"]["rate"] == "good" and items["净利润增速"]["rate"] == "bad"
assert items["利润含金量"]["val"].endswith("%")
assert H._r(None, 1, 2) is None
print("test_health ok")
