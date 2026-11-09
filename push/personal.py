"""按人推送:盘中每小时摘要里「你的自选股和持仓」部分,发到每个人自己的 Telegram。
数据来自 Supabase 的 user_data 表(用户登录网站后自己填的自选股、持仓、Telegram Id)。
环境变量(保密信息,只放在 GitHub Secrets,绝不写进代码):
  SUPABASE_URL           项目地址
  SUPABASE_SERVICE_KEY   服务端密钥(能读所有人的行,只给推送任务用,绝不能放进网页或代码)
  TELEGRAM_BOT_TOKEN     机器人令牌
没配置时什么都不做。只含信息,不是买卖建议。"""
import datetime, json, os, urllib.request, urllib.parse

MAX_USERS = 20           # 保险:一次最多处理这么多人
MAX_SYMS = 60            # 每人最多看这么多只


def configured():
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"))


def fetch_users():
    """所有填了 Telegram Id 并且开启了摘要的用户。"""
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/user_data?" + urllib.parse.urlencode(
        {"select": "user_id,watch,holdings,tg_chat_id,tg_hourly", "tg_chat_id": "not.is.null", "tg_hourly": "eq.true", "limit": str(MAX_USERS)})
    key = os.environ["SUPABASE_SERVICE_KEY"]
    req = urllib.request.Request(url, headers={"apikey": key, "Authorization": "Bearer " + key})
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode())


def clean(u):
    """整理一个用户的数据,过滤掉格式不对的内容。"""
    chat = str(u.get("tg_chat_id") or "").strip()
    if not (chat.lstrip("-").isdigit() and 5 <= len(chat.lstrip("-")) <= 15):
        return None
    watch = [s.upper() for s in (u.get("watch") or []) if isinstance(s, str)][:MAX_SYMS]
    hold = [{"sym": h["sym"].upper(), "qty": float(h["qty"]), "cost": float(h["cost"])} for h in (u.get("holdings") or [])
            if isinstance(h, dict) and isinstance(h.get("sym"), str) and float(h.get("qty") or 0) > 0 and float(h.get("cost") or 0) > 0][:MAX_SYMS]
    return {"chat": chat, "watch": watch, "hold": hold}


def usd(x, sign=False):
    s = f"{abs(x):,.0f}"
    return ("+" if sign and x >= 0 else "-" if x < 0 else "") + "$" + s


def build(t, u, quotes, news=None, head=None, extra=None):
    """u: clean() 的结果;quotes: {代码: {"price","pct"}}(取不到的不在里面);news: [(标签, 标题)]。返回 (标题, 正文) 或 None。"""
    held = {h["sym"] for h in u["hold"]}
    lines = [f"我的持仓与自选 {t.strftime('%H:%M')} 美西"] + list(head or [])
    if u["hold"]:
        tv = tc = day = 0.0
        rows, missing = [], []
        for h in u["hold"]:
            q = quotes.get(h["sym"])
            if not q:
                missing.append(h["sym"]); continue
            px, pct = q["price"], q["pct"]
            prev = px / (1 + pct / 100) if pct is not None and pct > -100 else px
            v, c, d = h["qty"] * px, h["qty"] * h["cost"], h["qty"] * (px - prev)
            tv += v; tc += c; day += d
            rows.append((abs(d), f"· {h['sym']} {px:,.2f}({pct:+.2f}%) 今日 {usd(d, True)},累计 {(px / h['cost'] - 1) * 100:+.1f}%"))
        lines.append("【持仓】今日 " + usd(day, True) + (f"({day / (tv - day) * 100:+.2f}%)" if tv - day > 0 else "") + f",总市值 {usd(tv)},累计盈亏 {usd(tv - tc, True)}({(tv / tc - 1) * 100:+.1f}%)" if rows else "【持仓】暂时取不到报价")
        lines += [r for _, r in sorted(rows, key=lambda r: -r[0])]
        if missing:
            lines.append("(没取到报价:" + "、".join(missing) + ")")
    rest = [s for s in u["watch"] if s not in held]
    if rest:
        parts = [f"{s} {quotes[s]['price']:,.2f}({quotes[s]['pct']:+.2f}%)" for s in rest if s in quotes]
        lines.append("【自选】" + ("  ".join(parts) if parts else "暂时取不到报价"))
    if not u["hold"] and not u["watch"]:
        return None
    if news:
        lines.append("【和你的股票有关的要闻】")
        lines += [f"· [{tag}] {head}" for tag, head in news[:3]]
    lines += list(extra or [])
    lines.append("只含信息,不是买卖建议;模型信号不保证收益,可能亏损,请自行判断风险")
    return f"我的持仓 {t.strftime('%H:%M')}", "\n".join(lines)


def run(t, quote_fn, news_fn=None, send_fn=None, dry=False, users=None, head=None, extra=None):
    """给每个开启了摘要的用户发一条。quote_fn(代码)->{"price","pct"}|None;news_fn(代码列表)->{代码:[(标签,标题)]};
    head:每个人消息开头都带的共用行(指数、期权异常);extra:结尾的共用行(盘中选股更新)。
    返回「已经成功发给个人版的聊天编号」集合,共用摘要不再重复发给他们。任何一个人出错不影响其他人。"""
    if users is None:
        if not configured():
            print("没有设置 SUPABASE_URL / SUPABASE_SERVICE_KEY,跳过按人推送")
            return set()
        users = fetch_users()
    people = [p for p in (clean(u) for u in users) if p]
    syms = sorted({s for p in people for s in p["watch"] + [h["sym"] for h in p["hold"]]})
    quotes = {}
    for s in syms:                                   # 所有人的股票合并后只查一次
        q = quote_fn(s)
        if q:
            quotes[s] = q
    news = news_fn(syms) if news_fn else {}
    served = set()
    for p in people:
        try:
            mine = p["watch"] + [h["sym"] for h in p["hold"]]
            nl = [(s, h) for s in dict.fromkeys(mine) for h in news.get(s, [])]
            r = build(t, p, quotes, nl, head, extra)
            if not r:
                continue
            if dry or os.environ.get("DRY_RUN"):
                print("====", r[0], "→ chat", p["chat"][:3] + "***", "====\n" + r[1] + "\n")
            else:
                (send_fn or _send)(r[0], r[1], p["chat"])
            served.add(p["chat"])
        except Exception as e:
            print("按人推送失败(跳过这个人):", type(e).__name__, str(e)[:80])
    print(f"按人推送:{len(people)} 人,发送 {len(served)} 条")
    return served


def _send(title, message, chat):
    import tg
    old = os.environ.get("TELEGRAM_CHAT_ID")
    os.environ["TELEGRAM_CHAT_ID"] = chat            # 只发给这个人
    try:
        tg.send_tg(title, message)
    finally:
        if old is None:
            os.environ.pop("TELEGRAM_CHAT_ID", None)
        else:
            os.environ["TELEGRAM_CHAT_ID"] = old


def remaining_chats(all_ids, served):
    """共用摘要还要发给谁:TELEGRAM_CHAT_ID 里的人,去掉已经收到个人版的。返回逗号分隔的字符串,空表示都不用发。"""
    return ",".join(c.strip() for c in (all_ids or "").split(",") if c.strip() and c.strip() not in served)
