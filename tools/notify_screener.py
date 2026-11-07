"""每日选股更新后,通过 ntfy 给手机发一条摘要。
- 需要环境变量 NTFY_TOPIC(和新闻推送是同一个主题;只在 GitHub Secrets 里,不写进文件)。
- 用法:python3 tools/notify_screener.py            (行情日期有更新才发)
      python3 tools/notify_screener.py --force    (不管有没有更新都发)
      python3 tools/notify_screener.py --dry      (只打印内容,不发送)
仅为条件筛选结果摘要,不构成投资建议。"""
import json, os, subprocess, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://stock-monitor-kappa-three.vercel.app"


def prev_data_date():
    """上一次的行情日期(用来判断今天有没有新行情)。工作流会在跑选股之前把它存进环境变量 PREV_DATA_DATE。"""
    if os.environ.get("PREV_DATA_DATE"):
        return os.environ["PREV_DATA_DATE"]
    try:
        out = subprocess.run(["git", "show", "HEAD:public/screener.json"], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout
        return json.loads(out).get("dataDate")
    except Exception:
        return None


def build(d):
    lines = []
    for p in d["presets"]:
        new = [r["sym"] for r in p["confirmed"] if r["status"] == "NEW"]
        inv = [x["sym"] for x in p.get("invalidated", [])]
        s = f"{p['name']}:确认 {p['confirmedTotal']} 只"
        if new:
            s += f",新入选 {'、'.join(new[:5])}"
        if inv:
            s += f",失效 {'、'.join(inv[:3])}"
        lines.append(s)
    lines.append(f"行情日期 {d['dataDate']} · 仅为条件筛选,不构成投资建议")
    return f"每日选股更新 {d['dataDate']}", "\n".join(lines)


def main():
    d = json.load(open(os.path.join(ROOT, "public", "screener.json")))
    if "--force" not in sys.argv and "--dry" not in sys.argv and prev_data_date() == d["dataDate"]:
        print("行情日期没有变化,不推送")
        return
    title, msg = build(d)
    if "--dry" in sys.argv:
        print(title + "\n" + msg)
        return
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("没有设置 NTFY_TOPIC,跳过推送")
        return
    body = json.dumps({"topic": topic, "title": title, "message": msg, "click": SITE + "/#picks", "priority": 3}).encode()
    urllib.request.urlopen(urllib.request.Request("https://ntfy.sh/", data=body, headers={"Content-Type": "application/json"}), timeout=20).read()
    print("已推送")


if __name__ == "__main__":
    main()
