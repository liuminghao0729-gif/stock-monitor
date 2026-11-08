"""检查 public/profiles_gen.json:格式必须完整,否则页面上所有自动写的解读都会读不出来。写完解读、提交之前必须跑一遍。"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIELDS = {"one": str, "money": list, "strong": str, "choke": str, "orders": str, "risk": list, "watch": str, "grade": str, "note": str, "date": str, "by": str}


def check(path=os.path.join(ROOT, "public", "profiles_gen.json")):
    d = json.load(open(path, encoding="utf8"))
    errs = []
    for sym, p in d.items():
        for k, t in FIELDS.items():
            if k not in p or not isinstance(p[k], t) or (t is str and not p[k].strip()) or (t is list and not p[k]):
                errs.append(f"{sym}.{k} 缺失或格式不对")
        if p.get("grade") not in ("A", "B", "C"):
            errs.append(f"{sym}.grade 必须是 A/B/C")
        if p.get("by") not in ("chat", "night"):
            errs.append(f"{sym}.by 必须是 chat 或 night")
        if isinstance(p.get("one"), str) and len(p["one"]) > 80:
            errs.append(f"{sym}.one 太长(要一句话,80 字内)")
        if len(p.get("risk") or []) > 5 or len(p.get("money") or []) > 5:
            errs.append(f"{sym}.money/risk 最多 5 条")
    return d, errs


if __name__ == "__main__":
    d, errs = check()
    print(f"{len(d)} 家,", "全部通过" if not errs else f"{len(errs)} 个问题")
    for e in errs:
        print("  -", e)
    sys.exit(1 if errs else 0)
